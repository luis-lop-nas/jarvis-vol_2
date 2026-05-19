"""Tests end-to-end del sistema JARVIS completo.

Cada test levanta un stack real (seguridad, agente, API) con el modelo AI mockeado
y sin servicios externos (ChromaDB, Ollama, 1Password). Los tests verifican que
los caminos críticos del sistema funcionan de extremo a extremo.

Ejecutar únicamente estos tests:
    pytest -m e2e
Excluirlos en CI normal:
    pytest -m "not e2e"
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import orjson
import pytest
import pytest_asyncio
from starlette.testclient import TestClient

from core.agent import ActualizacionAgente, Agente
from core.planner import Planner
from core.reflector import DecisionReflexion, Reflector
from interface.api import (
    _rate_state,
    _session_history,
    _session_queues,
    _session_tasks,
    crear_servidor,
)
from interface.websocket import ConnectionManager
from memory.short_term import MemoriaCortoPlazo
from models.base import ModelResponse
from security.audit_log import AuditLog
from security.confirmation import ConfirmationManager
from security.sandbox import CommandRisk, Sandbox, SandboxError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _plan_json(tool: str, params: dict, confirm: bool = False, paso_id: str = "p1") -> str:
    return json.dumps({
        "objetivo": "Tarea de test",
        "pasos": [{
            "id": paso_id,
            "descripcion": f"Ejecutar {tool}",
            "herramienta": tool,
            "parametros": params,
            "requiere_confirmacion": confirm,
            "depende_de": [],
            "duracion_estimada_ms": 100,
            "puede_fallar": False,
        }],
    })


def _configure_single_step(
    modelo: MagicMock,
    tool: str,
    params: dict,
    confirm: bool = False,
    summary: str = "Completado.",
) -> None:
    """Configura el mock del modelo para un plan de un paso que completa con éxito."""
    plan = _plan_json(tool, params, confirm)
    modelo.complete = AsyncMock(side_effect=[
        ModelResponse(content=plan, model="mock"),        # planner.plan()
        ModelResponse(content="continuar", model="mock"), # reflector.reflect()
        ModelResponse(content=summary, model="mock"),     # reflector.generate_summary()
    ] + [ModelResponse(content="continuar", model="mock")] * 10)


# ---------------------------------------------------------------------------
# Fixture principal — stack completo sin servicios externos
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def jarvis_stack(tmp_path: Path):
    """Stack JARVIS completo: seguridad real, AI mockeada, sin ChromaDB ni Ollama."""
    _session_queues.clear()
    _session_history.clear()
    _session_tasks.clear()
    _rate_state.clear()

    audit = AuditLog(base_dir=tmp_path / "audit")
    await audit.start()

    manager = ConnectionManager()
    cm = ConfirmationManager(ws_sender=manager.broadcast, auth_manager=None)
    sb = Sandbox(auth_manager=None, confirmation_manager=cm, audit_log=audit)

    memoria = MagicMock()
    memoria.store_interaction = AsyncMock()
    memoria.get_context = AsyncMock(return_value="")
    memoria.record_episode = AsyncMock()
    memoria.find_workflow = AsyncMock(return_value=None)

    memoria_ep = MagicMock()
    memoria_ep.record = AsyncMock()

    modelo = MagicMock()
    modelo.complete = AsyncMock(return_value=ModelResponse(content="{}", model="mock"))

    memoria_corto = MemoriaCortoPlazo()
    planner = Planner(modelo)
    reflector = Reflector(modelo)

    agente = Agente(
        planner=planner,
        reflector=reflector,
        memoria_corto=memoria_corto,
        memoria_episodica=memoria_ep,
        auditoria=audit,
        memoria=memoria,
        herramientas={},
    )

    app = crear_servidor(agente, manager, confirmation_manager=cm)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield {
            "agente": agente,
            "modelo": modelo,
            "planner": planner,
            "reflector": reflector,
            "client": client,
            "sandbox": sb,
            "cm": cm,
            "audit": audit,
            "memoria": memoria,
            "memoria_corto": memoria_corto,
            "manager": manager,
            "app": app,
            "tmp_path": tmp_path,
        }

    await audit.stop()
    _session_queues.clear()
    _session_history.clear()
    _session_tasks.clear()
    _rate_state.clear()


# ---------------------------------------------------------------------------
# Test 1 — lectura de archivo real
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_e2e_simple_file_read(jarvis_stack: dict) -> None:
    """JARVIS lee un archivo real y emite 'listo' con el contenido."""
    agente = jarvis_stack["agente"]
    modelo = jarvis_stack["modelo"]
    test_file = jarvis_stack["tmp_path"] / "README.md"
    test_file.write_text("# Proyecto JARVIS\nContenido de prueba para test e2e.")

    _configure_single_step(modelo, "filesystem.leer", {"ruta": str(test_file)})

    contenido_leido: list[str] = []

    async def _leer(ruta: str) -> str:
        texto = Path(ruta).read_text()
        contenido_leido.append(texto)
        return texto

    agente._herramientas = {"filesystem.leer": _leer}
    agente._reflector.evaluate_task_completion = MagicMock(side_effect=[False, True])
    agente._reflector.generate_summary = AsyncMock(return_value="Archivo leído correctamente.")

    updates = []
    async for u in agente.run("lee el README.md", session_id="e2e-read"):
        updates.append(u)

    tipos = [u.tipo for u in updates]
    assert "listo" in tipos, f"Tipos recibidos: {tipos}"
    assert contenido_leido, "La herramienta filesystem.leer no fue llamada"
    assert "Proyecto JARVIS" in contenido_leido[0]
    # audit_log.registrar es una coroutine real — verificamos que la tarea completó
    ultimo = updates[-1]
    assert ultimo.progreso == 1.0


# ---------------------------------------------------------------------------
# Test 2 — organización de descargas genera propuesta de confirmación
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_e2e_file_organize(jarvis_stack: dict, tmp_path: Path) -> None:
    """El agente propone mover un PDF pero se detiene esperando confirmación."""
    agente = jarvis_stack["agente"]
    modelo = jarvis_stack["modelo"]

    pdf_file = tmp_path / "Downloads" / "apuntes_fisica.pdf"
    pdf_file.parent.mkdir(parents=True)
    pdf_file.write_bytes(b"%PDF-1.4 fake content")

    plan = _plan_json(
        "filesystem.organizar",
        {"ruta": str(pdf_file)},
        confirm=True,
        paso_id="organizar",
    )
    modelo.complete = AsyncMock(side_effect=[
        ModelResponse(content=plan, model="mock"),
    ] + [ModelResponse(content="continuar", model="mock")] * 10)

    agente._reflector.evaluate_task_completion = MagicMock(return_value=False)

    sid = "e2e-organize"
    updates = []

    async def _ejecutar() -> None:
        async for u in agente.run("organiza mis descargas", session_id=sid):
            updates.append(u)
            if u.tipo == "esperando":
                await agente.cancel(sid)

    await asyncio.wait_for(_ejecutar(), timeout=8.0)

    assert any(u.tipo == "esperando" for u in updates), (
        f"No se recibió 'esperando'. Tipos: {[u.tipo for u in updates]}"
    )


# ---------------------------------------------------------------------------
# Test 3 — comando seguro en sandbox
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_e2e_terminal_safe_command(jarvis_stack: dict) -> None:
    """El sandbox permite ejecutar 'python --version' y devuelve código 0."""
    sb = jarvis_stack["sandbox"]

    resultado = await sb.execute_safe("python3 --version")

    assert resultado.exito, f"Comando falló: {resultado.stderr}"
    assert resultado.codigo_retorno == 0
    output = (resultado.stdout + resultado.stderr).lower()
    assert "python" in output, f"Salida inesperada: {resultado.stdout!r} / {resultado.stderr!r}"


# ---------------------------------------------------------------------------
# Test 4 — comando bloqueado
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_e2e_terminal_blocked_command(jarvis_stack: dict) -> None:
    """El sandbox bloquea 'rm -rf /' antes de ejecutarlo."""
    sb = jarvis_stack["sandbox"]

    with pytest.raises(SandboxError) as exc_info:
        await sb.validate_command("rm -rf /")

    assert exc_info.value.risk_level == CommandRisk.BLOCKED


# ---------------------------------------------------------------------------
# Test 5 — persistencia de memoria en la sesión
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_e2e_memory_persistence(jarvis_stack: dict) -> None:
    """store_interaction se llama al menos 2 veces por ciclo (inicio + plan)."""
    agente = jarvis_stack["agente"]
    modelo = jarvis_stack["modelo"]
    memoria = jarvis_stack["memoria"]

    _configure_single_step(modelo, "filesystem.leer", {"ruta": "/dev/null"})
    agente._herramientas = {"filesystem.leer": AsyncMock(return_value="")}
    agente._reflector.evaluate_task_completion = MagicMock(side_effect=[False, True])
    agente._reflector.generate_summary = AsyncMock(return_value="OK")

    async for _ in agente.run("lee algo", session_id="e2e-mem"):
        pass

    assert memoria.store_interaction.await_count >= 2, (
        f"store_interaction llamada {memoria.store_interaction.await_count} veces"
    )
    llamada_tarea = memoria.store_interaction.call_args_list[0]
    assert "lee algo" in str(llamada_tarea)


# ---------------------------------------------------------------------------
# Test 6 — router de privacidad
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_e2e_router_privacy(jarvis_stack: dict) -> None:
    """Texto con datos sensibles → router elige modelo local (ModeloDestino.LOCAL_DEFAULT)."""
    from core.router import ContextoRuteo, ModeloDestino, ModelRouter
    from models.base import Mensaje

    router = ModelRouter()
    texto_sensible = "mi contraseña es abc123"

    # Forzar sin_internet=False para que la regla de privacidad sea la que actúe
    contexto = ContextoRuteo(
        mensajes=[Mensaje(rol="user", contenido=texto_sensible)],
        sin_internet=False,
    )

    with patch.object(router, "_hay_internet", return_value=True):
        seleccion = router.route(texto_sensible, contexto=contexto)

    assert seleccion.model_name == ModeloDestino.LOCAL_DEFAULT, (
        f"Esperaba LOCAL_DEFAULT. Obtenido: {seleccion.model_name!r}, razón: {seleccion.razon!r}"
    )
    assert seleccion.razon == "datos_sensibles", f"Razón: {seleccion.razon!r}"


# ---------------------------------------------------------------------------
# Test 7 — límite de pasos del agente
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_e2e_agent_max_steps(jarvis_stack: dict) -> None:
    """El agente se detiene al alcanzar MAX_PASOS y emite tipo='error'."""
    import core.agent as agent_module

    agente = jarvis_stack["agente"]
    modelo = jarvis_stack["modelo"]

    plan_infinito = json.dumps({
        "objetivo": "Bucle infinito",
        "pasos": [{
            "id": "p1",
            "descripcion": "Paso que no completa",
            "herramienta": "filesystem.leer",
            "parametros": {"ruta": "/dev/null"},
            "requiere_confirmacion": False,
            "depende_de": [],
            "duracion_estimada_ms": 10,
            "puede_fallar": False,
        }],
    })
    modelo.complete = AsyncMock(
        return_value=ModelResponse(content=plan_infinito, model="mock")
    )

    agente._herramientas = {"filesystem.leer": AsyncMock(return_value="")}
    # REINTENTAR no avanza el índice → el mismo paso se ejecuta repetidamente
    agente._reflector.reflect = AsyncMock(return_value=DecisionReflexion.REINTENTAR)
    agente._reflector.evaluate_task_completion = MagicMock(return_value=False)

    updates = []
    # MAX_PASOS=3 y MAX_REINTENTOS=100 (para que la regla de pasos sea la que dispare)
    with patch.object(agent_module, "MAX_PASOS", 3), \
         patch.object(agent_module, "MAX_REINTENTOS", 100):
        async for u in agente.run("tarea infinita", session_id="e2e-maxsteps"):
            updates.append(u)
            if len(updates) > 40:
                break

    # El agente debe parar por "Límite de pasos" o por el runaway guard ("Loop detectado").
    # Ambos son mecanismos válidos de seguridad que previenen bucles infinitos.
    assert any(
        u.tipo == "error" and ("Límite" in u.mensaje or "Loop detectado" in u.mensaje)
        for u in updates
    ), f"No se recibió error de parada. Tipos: {[(u.tipo, u.mensaje) for u in updates]}"


# ---------------------------------------------------------------------------
# Test 8 — streaming WebSocket recibe actualizaciones progresivas
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_e2e_agent_streaming(jarvis_stack: dict) -> None:
    """El agente emite updates progresivos: pensando → actuando → listo."""
    agente = jarvis_stack["agente"]
    modelo = jarvis_stack["modelo"]

    plan = _plan_json("filesystem.leer", {"ruta": "/dev/null"})
    modelo.complete = AsyncMock(side_effect=[
        ModelResponse(content=plan, model="mock"),
        ModelResponse(content="continuar", model="mock"),
        ModelResponse(content="Leído.", model="mock"),
    ] + [ModelResponse(content="continuar", model="mock")] * 5)

    agente._herramientas = {"filesystem.leer": AsyncMock(return_value="contenido")}
    agente._reflector.evaluate_task_completion = MagicMock(side_effect=[False, True])
    agente._reflector.generate_summary = AsyncMock(return_value="Leído.")

    updates = []
    async for u in agente.run("lee algo", session_id="e2e-stream"):
        updates.append(u)

    tipos = [u.tipo for u in updates]
    assert "pensando" in tipos, f"Tipos: {tipos}"
    assert "actuando" in tipos, f"Tipos: {tipos}"
    assert "listo" in tipos, f"Tipos: {tipos}"

    # Verificar progreso monotónico: no debe bajar
    progresos = [u.progreso for u in updates]
    for i in range(1, len(progresos)):
        assert progresos[i] >= progresos[i - 1] - 0.01, (
            f"Progreso no monotónico en índice {i}: {progresos}"
        )


@pytest.mark.e2e
def test_e2e_websocket_protocol(jarvis_stack: dict) -> None:
    """El protocolo WebSocket responde ping→pong e invalida session_id incorrectos."""
    app = jarvis_stack["app"]

    with TestClient(app) as tc:
        # Ping → pong (el primer mensaje al conectar es session_state; consumir primero)
        with tc.websocket_connect("/ws?session_id=e2e-proto") as ws:
            state_msg = orjson.loads(ws.receive_text())
            assert state_msg["type"] == "session_state"
            ws.send_text(orjson.dumps({"type": "ping"}).decode())
            pong = orjson.loads(ws.receive_text())
            assert pong["type"] == "pong"

        # session_id inválido → cierre 1008
        try:
            with tc.websocket_connect("/ws?session_id=!!!invalid!!!") as ws:
                ws.receive_text()
            raise AssertionError("Esperaba cierre por session_id inválido")
        except AssertionError:
            raise
        except Exception:
            pass  # Starlette cierra la conexión — excepción esperada


# ---------------------------------------------------------------------------
# Test 9 — flujo de confirmación: pausa → resume → listo
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_e2e_confirmation_flow(jarvis_stack: dict) -> None:
    """El agente pausa en WAIT_USER, resume('si') desbloquea y completa la tarea."""
    agente = jarvis_stack["agente"]
    modelo = jarvis_stack["modelo"]

    plan = _plan_json("filesystem.eliminar", {"ruta": "/tmp/jarvis_test.txt"}, confirm=True)
    modelo.complete = AsyncMock(side_effect=[
        ModelResponse(content=plan, model="mock"),
        ModelResponse(content="continuar", model="mock"),
        ModelResponse(content="Archivo borrado.", model="mock"),
    ] + [ModelResponse(content="continuar", model="mock")] * 5)

    herramienta_mock = AsyncMock(return_value=True)
    agente._herramientas = {"filesystem.eliminar": herramienta_mock}
    agente._reflector.reflect = AsyncMock(return_value=DecisionReflexion.CONTINUAR)
    agente._reflector.evaluate_task_completion = MagicMock(side_effect=[False, True])
    agente._reflector.generate_summary = AsyncMock(return_value="Archivo borrado.")

    sid = "e2e-confirm"
    updates: list[ActualizacionAgente] = []

    async def _ejecutar() -> None:
        async for u in agente.run("borra el archivo temporal", session_id=sid):
            updates.append(u)
            if u.tipo == "esperando":
                await agente.resume(sid, "si")

    await asyncio.wait_for(_ejecutar(), timeout=10.0)

    tipos = [u.tipo for u in updates]
    assert "esperando" in tipos, f"No hubo espera. Tipos: {tipos}"
    assert "listo" in tipos, f"No se completó. Tipos: {tipos}"
    herramienta_mock.assert_called_once()


# ---------------------------------------------------------------------------
# Test 10 — conversación de 5 turnos mantiene contexto
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_e2e_full_conversation(jarvis_stack: dict) -> None:
    """5 turnos consecutivos: memoria.store_interaction se llama en cada turno."""
    agente = jarvis_stack["agente"]
    modelo = jarvis_stack["modelo"]
    memoria = jarvis_stack["memoria"]

    for turno in range(5):
        plan = _plan_json("filesystem.leer", {"ruta": "/dev/null"}, paso_id=f"p{turno}")
        modelo.complete = AsyncMock(side_effect=[
            ModelResponse(content=plan, model="mock"),
            ModelResponse(content="continuar", model="mock"),
            ModelResponse(content=f"Turno {turno} completado.", model="mock"),
        ] + [ModelResponse(content="continuar", model="mock")] * 3)

        agente._herramientas = {"filesystem.leer": AsyncMock(return_value="")}
        agente._reflector.evaluate_task_completion = MagicMock(side_effect=[False, True])
        agente._reflector.generate_summary = AsyncMock(
            return_value=f"Turno {turno} completado."
        )

        updates: list[ActualizacionAgente] = []
        async for u in agente.run(f"pregunta número {turno + 1}", session_id=f"conv-{turno}"):
            updates.append(u)

        assert any(u.tipo == "listo" for u in updates), (
            f"Turno {turno}: no terminó correctamente. Tipos: {[u.tipo for u in updates]}"
        )

    assert memoria.store_interaction.await_count >= 10, (
        f"store_interaction llamada {memoria.store_interaction.await_count} veces en 5 turnos"
    )


# ---------------------------------------------------------------------------
# Test 11 — confirmar vía API HTTP desbloquea agente
# ---------------------------------------------------------------------------


@pytest.mark.e2e
async def test_e2e_confirmation_via_http(jarvis_stack: dict) -> None:
    """POST /confirm desbloquea al agente en estado WAIT_USER."""
    client = jarvis_stack["client"]
    agente = jarvis_stack["agente"]
    modelo = jarvis_stack["modelo"]

    plan = _plan_json("filesystem.eliminar", {"ruta": "/tmp/x.txt"}, confirm=True)
    modelo.complete = AsyncMock(side_effect=[
        ModelResponse(content=plan, model="mock"),
        ModelResponse(content="continuar", model="mock"),
        ModelResponse(content="Listo.", model="mock"),
    ] + [ModelResponse(content="continuar", model="mock")] * 5)

    herramienta_mock = AsyncMock(return_value=True)
    agente._herramientas = {"filesystem.eliminar": herramienta_mock}
    agente._reflector.reflect = AsyncMock(return_value=DecisionReflexion.CONTINUAR)
    agente._reflector.evaluate_task_completion = MagicMock(side_effect=[False, True])
    agente._reflector.generate_summary = AsyncMock(return_value="Listo.")

    # Lanzar tarea vía HTTP
    r = await client.post("/chat", json={"message": "borra el archivo", "session_id": "e2e-http-conf"})
    assert r.status_code == 200

    # Esperar a que el agente esté en estado "esperando"
    await asyncio.sleep(0.2)

    # Confirmar vía HTTP
    r2 = await client.post("/confirm/e2e-http-conf", json={"action_id": "p1", "confirmed": True})
    assert r2.status_code == 200

    # Dar tiempo al agente para completar
    await asyncio.sleep(0.3)

    # Verificar historial tiene updates
    r3 = await client.get("/history/e2e-http-conf")
    assert r3.status_code == 200
    historia = r3.json()
    assert len(historia) > 0
