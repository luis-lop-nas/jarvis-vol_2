"""Servidor FastAPI de JARVIS — único punto de entrada público.

Puerto 8765. Expone REST + SSE para el overlay SwiftUI.
El WebSocket vive en /ws dentro de la misma app.
"""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import time
from collections import defaultdict, deque
from typing import Any, AsyncGenerator
from uuid import uuid4

import httpx
import orjson
import psutil
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from core.agent import ActualizacionAgente, Agente
from interface.api_models import (
    AgentUpdate,
    ChatRequest,
    ChatResponse,
    ConfirmRequest,
    SystemStatus,
)
from interface.websocket import ConnectionManager

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Estado de sesiones (module-level, compartido en el proceso)
# ---------------------------------------------------------------------------

_session_queues: dict[str, asyncio.Queue] = {}
_session_history: dict[str, list[AgentUpdate]] = {}
_session_tasks: dict[str, asyncio.Task] = {}

# Rate limiting: timestamps de requests por session_id (ventana deslizante 1s)
_rate_state: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=20))
RATE_LIMIT = 10       # req/s por session_id
MAX_HISTORY = 50
MAX_SESSIONS = 500    # evita DoS por acumulación de sesiones

# Validación de session_id — solo alfanumérico + guiones
_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


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
) -> None:
    """Tarea de fondo: ejecuta el agente y distribuye updates a SSE y WebSocket."""
    queue = _session_queues[session_id]
    try:
        async for update in agente.run(message, session_id):
            api_update = _map_update(update)
            hist = _session_history.setdefault(session_id, [])
            hist.append(api_update)
            if len(hist) > MAX_HISTORY:
                del hist[0]
            await queue.put(api_update)
            await manager.send(session_id, api_update.model_dump())
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


def crear_servidor(agente: Agente, manager: ConnectionManager) -> FastAPI:
    """Construye la aplicación FastAPI completa con todas las rutas."""

    app = FastAPI(
        title="JARVIS",
        version="8.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
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

    @app.middleware("http")
    async def _log_requests(request: Request, call_next: Any) -> Any:
        log.info("→ %s %s", request.method, request.url.path)
        resp = await call_next(request)
        log.debug("← %d", resp.status_code)
        return resp

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

        if not _SESSION_ID_RE.match(session_id):
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

        _session_queues[session_id] = asyncio.Queue()
        task = asyncio.create_task(
            _run_agent_task(agente, manager, session_id, req.message)
        )
        _session_tasks[session_id] = task

        return ChatResponse(session_id=session_id, status="started")

    # ------------------------------------------------------------------
    # GET /stream/{session_id} — SSE con updates del agente
    # ------------------------------------------------------------------

    @app.get("/stream/{session_id}")
    async def stream_sse(session_id: str, request: Request) -> EventSourceResponse:
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
                except asyncio.TimeoutError:
                    yield {"data": orjson.dumps({"type": "ping"}).decode()}

        return EventSourceResponse(generator())

    # ------------------------------------------------------------------
    # POST /confirm/{session_id} — desbloquea al agente en WAIT_USER
    # ------------------------------------------------------------------

    @app.post("/confirm/{session_id}")
    async def confirm(session_id: str, req: ConfirmRequest) -> dict[str, str]:
        if not _check_rate(session_id):
            raise HTTPException(status_code=429, detail="Rate limit excedido")

        respuesta = "si" if req.confirmed else "no"
        ok = await agente.resume(session_id, respuesta)
        if not ok:
            raise HTTPException(status_code=404, detail="Sesión no activa o no esperando")
        return {"status": "ok"}

    # ------------------------------------------------------------------
    # POST /cancel/{session_id} — cancela tarea activa
    # ------------------------------------------------------------------

    @app.post("/cancel/{session_id}")
    async def cancel(session_id: str) -> dict[str, str]:
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
        try:
            async with httpx.AsyncClient(timeout=2.0) as c:
                r = await c.get("http://localhost:8000/api/v1/heartbeat")
                chroma_ok = r.status_code == 200
        except Exception:
            pass

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
            res = subprocess.run(["op", "--version"], capture_output=True, timeout=2)
            op_ok = res.returncode == 0
        except Exception:
            pass

        return SystemStatus(
            api_running=True,
            chroma_connected=chroma_ok,
            ollama_running=ollama_ok,
            available_models=models,
            ram_available_gb=ram_gb,
            onepassword_available=op_ok,
        )

    # ------------------------------------------------------------------
    # GET /history/{session_id} — últimos N mensajes
    # ------------------------------------------------------------------

    @app.get("/history/{session_id}")
    async def history(session_id: str, n: int = 20) -> list[dict]:
        hist = _session_history.get(session_id, [])
        return [u.model_dump() for u in hist[-n:]]

    # ------------------------------------------------------------------
    # POST /screenshot — captura pantalla en base64
    # ------------------------------------------------------------------

    @app.post("/screenshot")
    async def screenshot() -> dict[str, str]:
        try:
            from perception.screenshot import capture_screen, encode_for_vision

            img = await capture_screen()
            encoded = encode_for_vision(img)
            return {"image": encoded, "status": "ok"}
        except Exception:
            log.exception("Error capturando pantalla")
            raise HTTPException(status_code=500, detail="No se pudo capturar pantalla")

    # ------------------------------------------------------------------
    # WS /ws — canal bidireccional con el overlay SwiftUI
    # ------------------------------------------------------------------

    @app.websocket("/ws")
    async def ws_endpoint(
        websocket: WebSocket,
        session_id: str = "default",
    ) -> None:
        await manager.connect(websocket, session_id)
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
                sid = payload.get("session_id", session_id)

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
                    _session_queues[sid] = asyncio.Queue()
                    task = asyncio.create_task(
                        _run_agent_task(agente, manager, sid, content)
                    )
                    _session_tasks[sid] = task

                elif tipo == "confirm":
                    confirmed = bool(payload.get("confirmed", False))
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
