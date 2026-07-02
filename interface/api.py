"""Servidor FastAPI de JARVIS — único punto de entrada público.

Puerto 8765. Expone REST + SSE para el overlay SwiftUI.
El WebSocket vive en /ws dentro de la misma app.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from collections import defaultdict, deque
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Annotated, Any
from uuid import uuid4

import httpx
import orjson
import psutil
from fastapi import Depends, FastAPI, HTTPException, Path, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from sse_starlette.sse import EventSourceResponse

if TYPE_CHECKING:
    from core.mcp_bus import MCPBus
    from core.router import ModelRouter
    from security.audit_log import AuditLog
    from security.auth import AuthManager
    from security.confirmation import ConfirmationManager

from config import settings
from core.agent import ActualizacionAgente, Agente
from interface.api_auth import SESSION_ID_RE, check_ip_rate, require_auth
from interface.api_models import (
    AgentUpdate,
    ChatRequest,
    ChatResponse,
    ConfirmRequest,
    SkillInfo,
    SkillsResponse,
    SystemStatus,
)
from interface.dashboard import build_dashboard_html
from interface.session_store import SessionStore
from interface.websocket import ConnectionManager
from security.confirmation import SecurityError

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Estado de sesiones (module-level, compartido en el proceso)
# ---------------------------------------------------------------------------

_session_queues: dict[str, asyncio.Queue] = {}
_session_history: dict[str, deque[AgentUpdate]] = {}
_session_tasks: dict[str, asyncio.Task] = {}

# Rate limiting: timestamps de requests por session_id (ventana deslizante 1s)
_rate_state: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=20))
RATE_LIMIT = 10       # req/s por session_id
MAX_HISTORY = 50
MAX_SESSIONS = 500    # evita DoS por acumulación de sesiones
MAX_BODY_SIZE = 16 * 1024  # 16 KB
PERSIST_DEBOUNCE_S = 2.0   # mínimo entre persistencias de pasos intermedios


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------


def _check_rate(session_id: str) -> bool:
    now = time.monotonic()
    times = _rate_state[session_id]
    while times and now - times[0] >= 1.0:
        times.popleft()
    if len(times) >= RATE_LIMIT:
        return False
    times.append(now)
    return True


_TIPO_A_TYPE: dict[str, str] = {
    "pensando": "thinking",
    "actuando": "acting",
    "esperando": "waiting",
    "listo": "done",
    "error": "error",
}

_TIPO_A_ESTADO: dict[str, str] = {
    "pensando": "notch",
    "actuando": "edge",
    "esperando": "modal",
    "listo": "silent",
    "error": "silent",
}


def _map_update(u: ActualizacionAgente) -> AgentUpdate:
    return AgentUpdate(
        type=_TIPO_A_TYPE.get(u.tipo, u.tipo),
        message=u.mensaje,
        progress=u.progreso,
        step=u.paso.model_dump() if u.paso else None,
        result=u.resultado.model_dump() if u.resultado else None,
        state=_TIPO_A_ESTADO.get(u.tipo, "silent"),
    )


async def _run_agent_task(
    agente: Agente,
    manager: ConnectionManager,
    session_id: str,
    message: str,
    session_store: SessionStore | None = None,
    initial_state: Any = None,
) -> None:
    """Tarea de fondo: ejecuta el agente y distribuye updates a SSE y WebSocket."""
    queue = _session_queues[session_id]
    # La persistencia a disco NO va en el camino caliente: guardar tras cada
    # update mete un write por token en el streaming. Persistimos solo en
    # estados que importa restaurar (esperando/listo/error) o, para pasos
    # intermedios, como mucho una vez cada PERSIST_DEBOUNCE_S.
    ultimo_guardado = 0.0
    try:
        async for update in agente.run(message, session_id, initial_state=initial_state):
            api_update = _map_update(update)
            hist = _session_history.setdefault(session_id, deque(maxlen=MAX_HISTORY))
            hist.append(api_update)
            await queue.put(api_update)
            await manager.send(session_id, api_update.model_dump())
            # Persistir estado (best-effort, fuera del camino caliente)
            if session_store is not None:
                ahora = time.monotonic()
                critico = update.tipo in ("esperando", "listo", "error")
                if critico or ahora - ultimo_guardado >= PERSIST_DEBOUNCE_S:
                    state = agente.get_state(session_id)
                    if state is not None:
                        await session_store.save(session_id, state)
                        ultimo_guardado = ahora
    except Exception:
        log.exception("Error en tarea de agente sesión=%s", session_id)
        err = AgentUpdate(type="error", message="Error interno.", state="silent")
        _session_history.setdefault(session_id, []).append(err)
        await queue.put(err)
        await manager.send(session_id, err.model_dump())
    finally:
        await queue.put(None)  # sentinel: cierra el generador SSE
        _session_tasks.pop(session_id, None)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def crear_servidor(
    agente: Agente,
    manager: ConnectionManager,
    confirmation_manager: ConfirmationManager | None = None,
    audit_log: AuditLog | None = None,
    bus: MCPBus | None = None,
    session_store: SessionStore | None = None,
    router: ModelRouter | None = None,
    auth_manager: AuthManager | None = None,
    skill_registry: Any | None = None,
) -> FastAPI:
    """Construye la aplicación FastAPI completa con todas las rutas."""

    @asynccontextmanager
    async def _lifespan(application: FastAPI):  # type: ignore[type-arg]
        if session_store is not None:
            asyncio.create_task(session_store.cleanup_expired())
        yield

    app = FastAPI(
        title="JARVIS",
        version="8.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=_lifespan,
    )

    # CORS — solo localhost
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost",
            "http://127.0.0.1",
            "http://localhost:8765",
            "http://127.0.0.1:8765",
        ],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------------
    # GET / — dashboard web
    # ------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    async def dashboard() -> HTMLResponse:
        return HTMLResponse(content=build_dashboard_html())

    @app.middleware("http")
    async def _log_requests(request: Request, call_next: Any) -> Any:
        log.info("→ %s %s", request.method, request.url.path)
        resp = await call_next(request)
        log.debug("← %d", resp.status_code)
        return resp

    @app.middleware("http")
    async def _limit_body_size(request: Request, call_next: Any) -> Any:
        cl = request.headers.get("content-length")
        if cl and int(cl) > MAX_BODY_SIZE:
            return JSONResponse(status_code=413, content={"detail": "Cuerpo demasiado grande"})
        return await call_next(request)

    @app.middleware("http")
    async def _ip_rate_limit(request: Request, call_next: Any) -> Any:
        ip = request.client.host if request.client else "testclient"
        if not check_ip_rate(ip):
            return JSONResponse(status_code=429, content={"detail": "Rate limit por IP excedido"})
        return await call_next(request)

    @app.exception_handler(Exception)
    async def _global_error(request: Request, exc: Exception) -> JSONResponse:
        log.exception("Error no manejado en %s", request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Error interno del servidor."},
        )

    # ------------------------------------------------------------------
    # POST /chat — inicia tarea async, devuelve session_id inmediatamente
    # ------------------------------------------------------------------

    @app.post("/chat", response_model=ChatResponse)
    async def chat(req: ChatRequest) -> ChatResponse:
        session_id = req.session_id or uuid4().hex

        if not SESSION_ID_RE.match(session_id):
            raise HTTPException(status_code=400, detail="session_id inválido")

        if not _check_rate(session_id):
            raise HTTPException(status_code=429, detail="Rate limit excedido")

        # Límite global de sesiones activas para prevenir DoS
        active = sum(1 for t in _session_tasks.values() if not t.done())
        if active >= MAX_SESSIONS:
            raise HTTPException(status_code=503, detail="Servidor saturado")

        old = _session_tasks.get(session_id)
        if old and not old.done():
            await agente.cancel(session_id)

        # Restaurar sesión desde disco si existe (y no hay tarea activa)
        initial_state = None
        if session_store is not None and (old is None or old.done()):
            initial_state = await session_store.load(session_id)
            if initial_state is not None:
                log.info("Sesión %s restaurada desde disco.", session_id)

        _session_queues[session_id] = asyncio.Queue()
        task = asyncio.create_task(
            _run_agent_task(agente, manager, session_id, req.message,
                            session_store=session_store, initial_state=initial_state)
        )
        _session_tasks[session_id] = task

        return ChatResponse(session_id=session_id, status="started")

    # ------------------------------------------------------------------
    # GET /stream/{session_id} — SSE con updates del agente
    # ------------------------------------------------------------------

    @app.get("/stream/{session_id}")
    async def stream_sse(
        session_id: Annotated[str, Path(pattern=r"^[a-zA-Z0-9_-]{1,64}$")],
        request: Request,
    ) -> EventSourceResponse:
        if not _check_rate(session_id):
            raise HTTPException(status_code=429, detail="Rate limit excedido")

        queue = _session_queues.get(session_id)
        if queue is None:
            raise HTTPException(status_code=404, detail="Sesión no encontrada")

        async def generator() -> AsyncGenerator[dict, None]:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    update = await asyncio.wait_for(queue.get(), timeout=25.0)
                    if update is None:
                        break
                    yield {"data": orjson.dumps(update.model_dump()).decode()}
                except TimeoutError:
                    yield {"data": orjson.dumps({"type": "ping"}).decode()}

        return EventSourceResponse(generator())

    # ------------------------------------------------------------------
    # POST /confirm/{session_id} — desbloquea al agente en WAIT_USER
    # ------------------------------------------------------------------

    @app.post("/confirm/{session_id}", dependencies=[Depends(require_auth)])
    async def confirm(
        session_id: Annotated[str, Path(pattern=r"^[a-zA-Z0-9_-]{1,64}$")],
        req: ConfirmRequest,
    ) -> dict[str, str]:
        if not _check_rate(session_id):
            raise HTTPException(status_code=429, detail="Rate limit excedido")

        # Desbloquea confirmaciones de seguridad. El overlay usa `action_id`;
        # `request_id` es un alias histórico. Ambos portan el confirmation_id.
        conf_id = req.request_id or req.action_id
        if confirmation_manager is not None and conf_id:
            try:
                confirmation_manager.resolve(conf_id, req.confirmed, session_id)
            except SecurityError:
                raise HTTPException(status_code=403, detail="Violación de seguridad: sesión incorrecta") from None

        respuesta = "si" if req.confirmed else "no"
        ok = await agente.resume(session_id, respuesta)
        if not ok and (confirmation_manager is None or not conf_id):
            raise HTTPException(status_code=404, detail="Sesión no activa o no esperando")
        return {"status": "ok"}

    # ------------------------------------------------------------------
    # POST /cancel/{session_id} — cancela tarea activa
    # ------------------------------------------------------------------

    @app.post("/cancel/{session_id}", dependencies=[Depends(require_auth)])
    async def cancel(
        session_id: Annotated[str, Path(pattern=r"^[a-zA-Z0-9_-]{1,64}$")],
    ) -> dict[str, str]:
        if not _check_rate(session_id):
            raise HTTPException(status_code=429, detail="Rate limit excedido")

        ok = await agente.cancel(session_id)
        return {"status": "ok" if ok else "not_found"}

    # ------------------------------------------------------------------
    # GET /status — health check completo
    # ------------------------------------------------------------------

    @app.get("/status", response_model=SystemStatus)
    async def status_check() -> SystemStatus:
        chroma_ok = False
        if settings.chroma_mode == "docker":
            try:
                base = f"http://{settings.chroma_host}:{settings.chroma_port}"
                async with httpx.AsyncClient(timeout=2.0) as c:
                    # ChromaDB >=1.0 expone /api/v2; versiones antiguas /api/v1.
                    for ruta in ("/api/v2/heartbeat", "/api/v1/heartbeat"):
                        r = await c.get(f"{base}{ruta}")
                        if r.status_code == 200:
                            chroma_ok = True
                            break
            except Exception:
                pass
        else:
            # Modo embebido (PersistentClient): sin servidor HTTP. Chroma está
            # "conectado" si la colección se creó al arrancar el cliente local.
            with contextlib.suppress(Exception):
                chroma_ok = agente._memoria._long_term._coleccion is not None

        ollama_ok = False
        models: list[str] = []
        try:
            async with httpx.AsyncClient(timeout=2.0) as c:
                r = await c.get("http://localhost:11434/api/tags")
                if r.status_code == 200:
                    ollama_ok = True
                    models = [m["name"] for m in r.json().get("models", [])]
        except Exception:
            pass

        mem = psutil.virtual_memory()
        ram_gb = round(mem.available / (1024**3), 2)

        op_ok = False
        try:
            proc = await asyncio.create_subprocess_exec(
                "op", "--version",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=2.0)
            op_ok = proc.returncode == 0
        except Exception:
            pass

        mcp_health: dict[str, bool] = {}
        if bus is not None:
            with contextlib.suppress(Exception):
                mcp_health = await bus.health_check()

        return SystemStatus(
            api_running=True,
            chroma_connected=chroma_ok,
            ollama_running=ollama_ok,
            available_models=models,
            ram_available_gb=ram_gb,
            onepassword_available=op_ok,
            mcp_health=mcp_health,
            total_cost_usd=router.total_cost_usd if router is not None else 0.0,
        )

    # ------------------------------------------------------------------
    # GET /skills — lista de skills registrados
    # ------------------------------------------------------------------

    @app.get("/skills", response_model=SkillsResponse)
    async def list_skills() -> SkillsResponse:
        if skill_registry is None:
            return SkillsResponse(total=0, skills=[])
        raw = skill_registry.listar()
        skills = [SkillInfo(**s) for s in raw]
        return SkillsResponse(total=len(skills), skills=skills)

    # ------------------------------------------------------------------
    # POST /debug/inject — inyecta estados sintéticos en el overlay (solo QA)
    # ------------------------------------------------------------------
    # Solo activo si la variable de entorno JARVIS_DEBUG_OVERLAY está a "1".
    # Permite recorrer los colores del notch, el edge log y la confirmation card
    # sin depender del LLM (que en 8GB no planea). No deja superficie en
    # producción: sin el flag devuelve 404. Requiere token de API.

    _DEBUG_FRAMES: dict[str, dict[str, Any]] = {
        "thinking": {
            "type": "thinking",
            "message": "Analizando tu petición…",
            "progress": 0.15,
            "state": "thinking",
            "step": {"modelo": "kimi-k2", "tokens": 1280, "cost_usd": 0.0021},
        },
        "acting": {
            "type": "acting",
            "message": "Ejecutando herramienta",
            "progress": 0.55,
            "state": "acting",
            "step": {
                "id": "paso-1",
                "descripcion": "Leyendo config/settings.py",
                "herramienta": "filesystem.leer",
            },
        },
        "done": {
            "type": "done",
            "message": "Listo. He completado la tarea correctamente.",
            "progress": 1.0,
            "state": "done",
        },
        "error": {
            "type": "error",
            "message": "Timeout al contactar con la API del modelo",
            "progress": 0.0,
            "state": "error",
        },
        "inline": {
            "type": "inline",
            "message": "¿Quieres que ejecute los tests del archivo abierto?",
            "progress": 0.0,
            "state": "inline",
            "step": {"app": "com.microsoft.VSCode"},
        },
        "confirm": {
            "type": "waiting",
            "data": {
                "confirmation_id": "debug-conf-1",
                "action": "Eliminar 4 archivos temporales del escritorio",
                "command": "rm -rf ~/Desktop/tmp_a ~/Desktop/tmp_b ~/Desktop/tmp_c ~/Desktop/tmp_d",
                "action_type": "filesystem.eliminar",
                "risk_level": "dangerous",
                "affected_items": [
                    "~/Desktop/tmp_a.log",
                    "~/Desktop/tmp_b.log",
                    "~/Desktop/tmp_c.log",
                    "~/Desktop/tmp_d.log",
                ],
                "affected_count": 4,
                "expires_in": 60,
            },
        },
    }

    @app.post("/debug/inject/{frame}", dependencies=[Depends(require_auth)])
    async def debug_inject(
        frame: Annotated[str, Path(pattern=r"^[a-z]{1,16}$")],
    ) -> dict[str, Any]:
        if os.getenv("JARVIS_DEBUG_OVERLAY") != "1":
            raise HTTPException(status_code=404, detail="No encontrado")
        payload = _DEBUG_FRAMES.get(frame)
        if payload is None:
            raise HTTPException(
                status_code=400,
                detail=f"frame desconocido; usa uno de {sorted(_DEBUG_FRAMES)}",
            )
        # broadcast llega al overlay independientemente de su session_id.
        await manager.broadcast(payload)
        return {"injected": frame, "sessions": manager.get_active_sessions()}

    # ------------------------------------------------------------------
    # GET /sessions — metadatos de sesiones persistidas en disco
    # ------------------------------------------------------------------

    @app.get("/sessions", dependencies=[Depends(require_auth)])
    async def list_sessions() -> list[dict]:
        if session_store is None:
            return []
        return await asyncio.to_thread(session_store.list_sessions)

    # ------------------------------------------------------------------
    # GET /history/{session_id} — últimos N mensajes
    # ------------------------------------------------------------------

    @app.get("/history/{session_id}", dependencies=[Depends(require_auth)])
    async def history(
        session_id: Annotated[str, Path(pattern=r"^[a-zA-Z0-9_-]{1,64}$")],
        n: int = 20,
    ) -> list[dict]:
        hist = _session_history.get(session_id, deque())
        return [u.model_dump() for u in list(hist)[-n:]]

    # ------------------------------------------------------------------
    # GET /audit — consulta filtrada del audit log (requiere auth)
    # ------------------------------------------------------------------

    @app.get("/audit", dependencies=[Depends(require_auth)])
    async def audit_query(
        action_type: str | None = None,
        hours: int = 24,
        limit: int = 100,
    ) -> list[dict]:
        if audit_log is None:
            raise HTTPException(status_code=503, detail="Audit log no disponible")
        since = datetime.now(UTC) - timedelta(hours=hours)
        entries = await audit_log.query(action_type=action_type, since=since, limit=limit)
        return [e.model_dump(mode="json") for e in entries]

    # ------------------------------------------------------------------
    # POST /screenshot — captura pantalla en base64 (token + Face ID)
    # ------------------------------------------------------------------

    @app.post("/screenshot", dependencies=[Depends(require_auth)])
    async def screenshot() -> dict[str, str]:
        if auth_manager is not None:
            from security.auth import AuthError
            try:
                await auth_manager.require_auth("JARVIS: captura de pantalla")
            except AuthError as exc:
                raise HTTPException(status_code=403, detail=str(exc)) from None
        try:
            from perception.screenshot import capture_screen, encode_for_vision

            img = await capture_screen()
            encoded = encode_for_vision(img)
            return {"image": encoded, "status": "ok"}
        except Exception:
            log.exception("Error capturando pantalla")
            raise HTTPException(status_code=500, detail="No se pudo capturar pantalla") from None

    # ------------------------------------------------------------------
    # WS /ws — canal bidireccional con el overlay SwiftUI
    # ------------------------------------------------------------------

    @app.websocket("/ws")
    async def ws_endpoint(
        websocket: WebSocket,
        session_id: str = "default",
        token: str | None = None,
    ) -> None:
        from interface.api_auth import get_api_token
        if token != get_api_token():
            await websocket.close(code=1008, reason="No autorizado")
            return
        if not SESSION_ID_RE.match(session_id):
            await websocket.close(code=1008, reason="session_id inválido")
            return
        await manager.connect(websocket, session_id)

        # Enviar estado actual de la sesión inmediatamente tras reconectar
        last_hist = list(_session_history.get(session_id, deque()))
        last_update = last_hist[-1] if last_hist else None
        task_active = session_id in _session_tasks and not _session_tasks[session_id].done()
        if last_update is not None:
            ws_state = last_update.type
        elif task_active:
            ws_state = "thinking"
        else:
            ws_state = "idle"
        current_step = (last_update.step.get("id") if last_update and last_update.step else None)
        pending_conf = None
        if confirmation_manager is not None:
            for req in confirmation_manager.get_pending():
                if req.session_id == session_id:
                    pending_conf = {
                        "request_id": req.id,
                        "action_description": req.action_description,
                        "command": req.command,
                        "risk_level": req.risk_level,
                        "requires_auth": req.requires_auth,
                    }
                    break
        with contextlib.suppress(Exception):
            await websocket.send_text(orjson.dumps({
                "type": "session_state",
                "session_state": ws_state,
                "current_step": current_step,
                "pending_confirmation": pending_conf,
            }).decode())

        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    payload = orjson.loads(raw)
                except orjson.JSONDecodeError:
                    await websocket.send_text(
                        orjson.dumps({"type": "error", "message": "JSON inválido"}).decode()
                    )
                    continue

                tipo = payload.get("type")
                raw_sid = payload.get("session_id", session_id)
                sid = str(raw_sid) if raw_sid is not None else session_id
                if not SESSION_ID_RE.match(sid):
                    await websocket.send_text(
                        orjson.dumps({"type": "error", "message": "session_id inválido"}).decode()
                    )
                    continue

                if tipo == "message":
                    content = payload.get("content", "").strip()
                    if not content:
                        continue
                    if not _check_rate(sid):
                        await websocket.send_text(
                            orjson.dumps({"type": "error", "message": "Rate limit excedido"}).decode()
                        )
                        continue
                    old = _session_tasks.get(sid)
                    if old and not old.done():
                        await agente.cancel(sid)
                    ws_initial = None
                    if session_store is not None and (old is None or old.done()):
                        ws_initial = await session_store.load(sid)
                    _session_queues[sid] = asyncio.Queue()
                    task = asyncio.create_task(
                        _run_agent_task(agente, manager, sid, content,
                                        session_store=session_store, initial_state=ws_initial)
                    )
                    _session_tasks[sid] = task

                elif tipo == "confirm":
                    confirmed = bool(payload.get("confirmed", False))
                    # El overlay envía la clave `action_id`; el `request_id` es un
                    # alias histórico. Para la confirmación MCP ambos portan el
                    # confirmation_id real, así que aceptamos cualquiera de las dos.
                    req_id = payload.get("request_id") or payload.get("action_id")
                    if confirmation_manager is not None and req_id:
                        try:
                            # Siempre usar el session_id de la conexión (URL param),
                            # nunca el del payload — evita suplantación cross-session.
                            confirmation_manager.resolve(str(req_id), confirmed, session_id)
                        except SecurityError:
                            await websocket.send_text(
                                orjson.dumps({"type": "error", "message": "Violación de seguridad: sesión incorrecta"}).decode()
                            )
                            continue
                    respuesta = "si" if confirmed else "no"
                    await agente.resume(sid, respuesta)

                elif tipo == "cancel":
                    await agente.cancel(sid)

                elif tipo == "ping":
                    await websocket.send_text(
                        orjson.dumps({"type": "pong"}).decode()
                    )

        except WebSocketDisconnect:
            pass
        finally:
            manager.disconnect(session_id)

    return app
