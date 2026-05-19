"""Tests de la capa interface — API REST, SSE y WebSocket."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

import httpx
import orjson
import pytest
from starlette.testclient import TestClient

from core.agent import ActualizacionAgente
from interface.api import (
    _rate_state,
    _session_history,
    _session_queues,
    _session_tasks,
    crear_servidor,
)
from interface.api_auth import _IP_RATE, get_api_token
from interface.websocket import ConnectionManager

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_agente(updates: list[ActualizacionAgente] | None = None) -> MagicMock:
    """Agente mock con secuencia de updates predefinida."""
    _updates = updates or [
        ActualizacionAgente(tipo="pensando", mensaje="Analizando…", progreso=0.1),
        ActualizacionAgente(tipo="actuando", mensaje="Ejecutando", progreso=0.5),
        ActualizacionAgente(tipo="listo", mensaje="Completado.", progreso=1.0),
    ]

    agente = MagicMock()

    async def _run(
        tarea: str, session_id: str = "", initial_state=None
    ) -> AsyncGenerator[ActualizacionAgente, None]:
        for u in _updates:
            yield u

    agente.run = _run
    agente.get_state = MagicMock(return_value=None)
    agente.resume = AsyncMock(return_value=True)
    agente.cancel = AsyncMock(return_value=True)
    return agente


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _limpiar_estado():
    """Borra el estado de módulo entre tests para evitar interferencias."""
    _session_queues.clear()
    _session_history.clear()
    _session_tasks.clear()
    _rate_state.clear()
    _IP_RATE.clear()
    yield
    _session_queues.clear()
    _session_history.clear()
    _session_tasks.clear()
    _rate_state.clear()
    _IP_RATE.clear()


@pytest.fixture
def agente():
    return make_agente()


@pytest.fixture
def manager():
    return ConnectionManager()


@pytest.fixture
def app(agente, manager):
    return crear_servidor(agente, manager)


@pytest.fixture
async def client(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"X-JARVIS-Token": get_api_token()},
    ) as c:
        yield c


@pytest.fixture
async def unauth_client(app):
    """Cliente sin token — para tests de 401."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        yield c


# ---------------------------------------------------------------------------
# POST /chat
# ---------------------------------------------------------------------------


async def test_chat_endpoint_devuelve_session_id(client):
    r = await client.post("/chat", json={"message": "hola"})
    assert r.status_code == 200
    data = r.json()
    assert "session_id" in data
    assert data["status"] == "started"


async def test_chat_respeta_session_id_enviado(client):
    r = await client.post(
        "/chat", json={"message": "prueba", "session_id": "mi-sesion"}
    )
    assert r.status_code == 200
    assert r.json()["session_id"] == "mi-sesion"


async def test_chat_crea_queue_para_sse(client):
    await client.post("/chat", json={"message": "tarea", "session_id": "q-test"})
    assert "q-test" in _session_queues


async def test_chat_cancela_tarea_previa(manager):
    """Si hay una tarea activa al llegar una nueva, se cancela la anterior."""
    bloqueado = asyncio.Event()

    async def _run_infinito(tarea: str, session_id: str = "", initial_state=None):
        # Bloquea hasta que el test lo libere — simula tarea larga
        await bloqueado.wait()
        yield ActualizacionAgente(tipo="listo", mensaje="OK", progreso=1.0)

    agente = make_agente()
    agente.run = _run_infinito

    app = crear_servidor(agente, manager)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        # Primera petición: tarea queda bloqueada (activa)
        await c.post("/chat", json={"message": "primera", "session_id": "cancel-prev"})
        await asyncio.sleep(0.02)  # deja que la tarea arranque
        # Segunda petición: debe cancelar la primera
        await c.post("/chat", json={"message": "segunda", "session_id": "cancel-prev"})

    bloqueado.set()
    agente.cancel.assert_awaited_with("cancel-prev")


# ---------------------------------------------------------------------------
# GET /stream/{session_id}
# ---------------------------------------------------------------------------


async def test_stream_404_sesion_desconocida(client):
    r = await client.get("/stream/no-existe")
    assert r.status_code == 404


async def test_stream_devuelve_event_source(client):
    await client.post("/chat", json={"message": "x", "session_id": "sse-ok"})
    await asyncio.sleep(0.05)
    # Solo verificamos que el endpoint no falla al conectar
    async with client.stream("GET", "/stream/sse-ok") as resp:
        assert resp.status_code == 200


async def test_stream_recibe_updates(app):
    """Los updates del agente llegan al consumidor SSE."""
    manager = ConnectionManager()
    agente = make_agente([
        ActualizacionAgente(tipo="listo", mensaje="Hecho.", progreso=1.0),
    ])
    app2 = crear_servidor(agente, manager)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app2), base_url="http://test"
    ) as c:
        await c.post("/chat", json={"message": "tarea", "session_id": "sse-data"})
        # Esperar a que la tarea corra
        await asyncio.sleep(0.1)

        recibidos: list[dict] = []
        async with c.stream("GET", "/stream/sse-data") as resp:
            async for line in resp.aiter_lines():
                if line.startswith("data:"):
                    payload = orjson.loads(line[len("data:"):].strip())
                    recibidos.append(payload)
                    if payload.get("type") in ("done", "error", "ping"):
                        break

    assert any(u.get("type") == "done" for u in recibidos)


# ---------------------------------------------------------------------------
# POST /confirm/{session_id}
# ---------------------------------------------------------------------------


async def test_confirm_llama_resume_con_si(agente, client):
    await client.post("/chat", json={"message": "borrar", "session_id": "conf-ok"})
    r = await client.post(
        "/confirm/conf-ok", json={"action_id": "paso_1", "confirmed": True}
    )
    assert r.status_code == 200
    agente.resume.assert_awaited_with("conf-ok", "si")


async def test_confirm_llama_resume_con_no(agente, client):
    await client.post("/chat", json={"message": "mover", "session_id": "conf-no"})
    r = await client.post(
        "/confirm/conf-no", json={"action_id": "paso_1", "confirmed": False}
    )
    assert r.status_code == 200
    agente.resume.assert_awaited_with("conf-no", "no")


async def test_confirm_404_cuando_resume_falla(manager):
    agente = make_agente()
    agente.resume = AsyncMock(return_value=False)
    app2 = crear_servidor(agente, manager)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app2),
        base_url="http://test",
        headers={"X-JARVIS-Token": get_api_token()},
    ) as c:
        await c.post("/chat", json={"message": "test", "session_id": "conf-fail"})
        r = await c.post(
            "/confirm/conf-fail", json={"action_id": "x", "confirmed": True}
        )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# POST /cancel/{session_id}
# ---------------------------------------------------------------------------


async def test_cancel_llama_cancel_en_agente(agente, client):
    await client.post("/chat", json={"message": "tarea", "session_id": "can-ok"})
    r = await client.post("/cancel/can-ok")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    agente.cancel.assert_awaited_with("can-ok")


async def test_cancel_not_found_cuando_cancel_falla(manager):
    agente = make_agente()
    agente.cancel = AsyncMock(return_value=False)
    app2 = crear_servidor(agente, manager)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app2),
        base_url="http://test",
        headers={"X-JARVIS-Token": get_api_token()},
    ) as c:
        r = await c.post("/cancel/inexistente")
    assert r.status_code == 200
    assert r.json()["status"] == "not_found"


# ---------------------------------------------------------------------------
# GET /status
# ---------------------------------------------------------------------------


async def test_status_devuelve_api_running(client):
    r = await client.get("/status")
    assert r.status_code == 200
    data = r.json()
    assert data["api_running"] is True
    assert "ram_available_gb" in data
    assert "available_models" in data


# ---------------------------------------------------------------------------
# GET /history/{session_id}
# ---------------------------------------------------------------------------


async def test_history_acumula_updates(app):
    manager = ConnectionManager()
    agente = make_agente([
        ActualizacionAgente(tipo="listo", mensaje="OK", progreso=1.0),
    ])
    app2 = crear_servidor(agente, manager)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app2),
        base_url="http://test",
        headers={"X-JARVIS-Token": get_api_token()},
    ) as c:
        await c.post("/chat", json={"message": "x", "session_id": "hist-ok"})
        await asyncio.sleep(0.15)
        r = await c.get("/history/hist-ok")

    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) >= 1


async def test_history_sesion_vacia_devuelve_lista_vacia(client):
    r = await client.get("/history/sin-sesion")
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


async def test_rate_limit_429_al_superar_10_por_segundo(manager):
    agente = make_agente([])
    app2 = crear_servidor(agente, manager)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app2), base_url="http://test"
    ) as c:
        statuses = []
        for _ in range(13):
            r = await c.post("/chat", json={"message": "x", "session_id": "rate-sid"})
            statuses.append(r.status_code)

    assert 429 in statuses, f"Esperaba 429, obtenidos: {set(statuses)}"


# ---------------------------------------------------------------------------
# WebSocket /ws
# ---------------------------------------------------------------------------


def _ws_url(session_id: str) -> str:
    return f"/ws?session_id={session_id}&token={get_api_token()}"


def test_websocket_ping_pong(app):
    with TestClient(app) as tc, tc.websocket_connect(_ws_url("ws-ping")) as ws:
        session_state = orjson.loads(ws.receive_text())
        assert session_state["type"] == "session_state"
        ws.send_text(orjson.dumps({"type": "ping"}).decode())
        data = orjson.loads(ws.receive_text())
        assert data["type"] == "pong"


def test_websocket_json_invalido_devuelve_error(app):
    with TestClient(app) as tc, tc.websocket_connect(_ws_url("ws-json")) as ws:
        session_state = orjson.loads(ws.receive_text())
        assert session_state["type"] == "session_state"
        ws.send_text("esto no es json{{{")
        data = orjson.loads(ws.receive_text())
        assert data["type"] == "error"


def test_websocket_reconexion_recibe_buffer(manager):
    """Al reconectar, el cliente recibe el buffer y luego el session_state."""
    manager._buffers["buf-sid"] = deque(
        [{"type": "done", "message": "Completado.", "progress": 1.0, "state": "silent"}],
        maxlen=50,
    )
    agente = make_agente()
    app2 = crear_servidor(agente, manager)

    with TestClient(app2) as tc, tc.websocket_connect(_ws_url("buf-sid")) as ws:
        buf_msg = orjson.loads(ws.receive_text())
        assert buf_msg["message"] == "Completado."
        state_msg = orjson.loads(ws.receive_text())
        assert state_msg["type"] == "session_state"


# ---------------------------------------------------------------------------
# WebSocket — session_state al reconectar
# ---------------------------------------------------------------------------


def test_websocket_reconnect_sends_state(manager):
    """Al conectar, el servidor envía un mensaje session_state tras el buffer."""
    agente = make_agente()
    app2 = crear_servidor(agente, manager)

    with TestClient(app2) as tc, tc.websocket_connect(_ws_url("state-sid")) as ws:
        msg = orjson.loads(ws.receive_text())
        assert msg["type"] == "session_state"
        assert "session_state" in msg
        assert msg["session_state"] == "idle"
        assert "current_step" in msg
        assert "pending_confirmation" in msg


def test_websocket_reconnect_sends_last_known_state(manager):
    """Si hay historial en _session_history, session_state refleja el último tipo."""
    from interface.api import _session_history
    from interface.api_models import AgentUpdate

    # _session_history guarda la historia para derivar estado; manager._buffers
    # guarda lo que se envía al reconectar. Son independientes: aquí solo
    # el session_state se envía (no el buffer porque manager._buffers está vacío).
    _session_history["hist-ws"] = deque(
        [AgentUpdate(type="thinking", message="Analizando…", state="notch")],
        maxlen=50,
    )
    agente = make_agente()
    app2 = crear_servidor(agente, manager)

    with TestClient(app2) as tc, tc.websocket_connect(_ws_url("hist-ws")) as ws:
        msg = orjson.loads(ws.receive_text())
        assert msg["type"] == "session_state"
        assert msg["session_state"] == "thinking"


def test_websocket_reconnect_pending_confirmation(manager):
    """Si hay una confirmación pendiente para la sesión, se incluye en session_state."""
    from unittest.mock import MagicMock

    from security.confirmation import ConfirmationRequest

    pending_req = ConfirmationRequest(
        id="req-123",
        session_id="conf-ws",
        action_description="Eliminar archivos temporales",
        risk_level="moderate",
        requires_auth=False,
    )
    cm = MagicMock()
    cm.get_pending.return_value = [pending_req]

    agente = make_agente()
    app2 = crear_servidor(agente, manager, confirmation_manager=cm)

    with TestClient(app2) as tc, tc.websocket_connect(_ws_url("conf-ws")) as ws:
        msg = orjson.loads(ws.receive_text())
        assert msg["type"] == "session_state"
        assert msg["pending_confirmation"] is not None
        assert msg["pending_confirmation"]["request_id"] == "req-123"
        assert msg["pending_confirmation"]["action_description"] == "Eliminar archivos temporales"


# ---------------------------------------------------------------------------
# Dashboard y /sessions
# ---------------------------------------------------------------------------


async def test_dashboard_devuelve_html(client):
    r = await client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "JARVIS" in r.text


async def test_sessions_sin_store_devuelve_lista_vacia(client):
    r = await client.get("/sessions")
    assert r.status_code == 200
    assert r.json() == []


# ---------------------------------------------------------------------------
# Seguridad — autenticación (401) y WebSocket sin token
# ---------------------------------------------------------------------------


async def test_audit_sin_token_devuelve_401(unauth_client):
    r = await unauth_client.get("/audit")
    assert r.status_code == 401


async def test_sessions_sin_token_devuelve_401(unauth_client):
    r = await unauth_client.get("/sessions")
    assert r.status_code == 401


async def test_history_sin_token_devuelve_401(unauth_client):
    r = await unauth_client.get("/history/cualquier-sesion")
    assert r.status_code == 401


async def test_screenshot_sin_token_devuelve_401(unauth_client):
    r = await unauth_client.post("/screenshot")
    assert r.status_code == 401


async def test_confirm_sin_token_devuelve_401(unauth_client):
    r = await unauth_client.post(
        "/confirm/test-sid", json={"action_id": "x", "confirmed": True}
    )
    assert r.status_code == 401


async def test_cancel_sin_token_devuelve_401(unauth_client):
    r = await unauth_client.post("/cancel/test-sid")
    assert r.status_code == 401


async def test_token_incorrecto_devuelve_401(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"X-JARVIS-Token": "token-falso-00000000"},
    ) as c:
        r = await c.get("/audit")
    assert r.status_code == 401


async def test_endpoints_publicos_no_requieren_token(unauth_client):
    """chat, status y dashboard no requieren autenticación."""
    r_status = await unauth_client.get("/status")
    r_dash = await unauth_client.get("/")
    assert r_status.status_code == 200
    assert r_dash.status_code == 200


# ---------------------------------------------------------------------------
# Seguridad — body size limit (413)
# ---------------------------------------------------------------------------


async def test_body_demasiado_grande_devuelve_413(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as c:
        payload = "x" * (17 * 1024)
        r = await c.post(
            "/chat",
            content=payload,
            headers={"content-type": "application/json", "content-length": str(len(payload))},
        )
    assert r.status_code == 413


# ---------------------------------------------------------------------------
# Seguridad — session_id inválido en path params (422)
# ---------------------------------------------------------------------------


async def test_stream_session_id_invalido_devuelve_error(client):
    # Path traversal bloqueado por Starlette (404) o por validación (422)
    r = await client.get("/stream/../../etc/passwd")
    assert r.status_code in (400, 404, 422)


async def test_stream_session_id_con_caracteres_invalidos(client):
    r = await client.get("/stream/inv@lid!chars")
    assert r.status_code in (400, 422)


async def test_history_session_id_invalido_devuelve_error(client):
    r = await client.get("/history/../../invalid")
    assert r.status_code in (400, 401, 404, 422)


# ---------------------------------------------------------------------------
# Seguridad — screenshot con biométrica mockeada
# ---------------------------------------------------------------------------


async def test_screenshot_con_auth_biometrica_fallida_devuelve_403(agente, manager):
    from unittest.mock import AsyncMock

    from security.auth import AuthError, AuthManager

    mock_auth = AsyncMock(spec=AuthManager)
    mock_auth.require_auth.side_effect = AuthError("Face ID rechazado")

    app2 = crear_servidor(agente, manager, auth_manager=mock_auth)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app2),
        base_url="http://testserver",
        headers={"X-JARVIS-Token": get_api_token()},
    ) as c:
        r = await c.post("/screenshot")
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Seguridad — WebSocket sin token
# ---------------------------------------------------------------------------


def test_websocket_sin_token_cierra_conexion(app):
    with TestClient(app) as tc:
        with pytest.raises(Exception):
            with tc.websocket_connect("/ws?session_id=no-auth") as ws:
                ws.receive_text()
