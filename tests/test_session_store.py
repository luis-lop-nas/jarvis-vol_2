"""Tests de persistencia de sesiones — SessionStore."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import orjson
import pytest

from core.planner import PasoAccion, PlanEjecucion
from core.reflector import ResultadoPaso
from interface.session_store import SessionStore
from models.base import Mensaje


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(session_id: str = "test-abc") -> dict:
    """Estado mínimo válido compatible con AgentState."""
    return {
        "messages": [Mensaje(rol="user", contenido="organiza mis descargas")],
        "current_task": "organiza mis descargas",
        "current_plan": None,
        "completed_steps": [],
        "failed_steps": [],
        "retry_count": 0,
        "replan_count": 0,
        "system_context": {},
        "memory_context": "contexto de prueba",
        "waiting_for_user": False,
        "paso_pendiente_confirmacion": None,
        "abort_reason": None,
        "session_id": session_id,
        "indice_paso_actual": 2,
        "tarea_completada": False,
    }


def _make_state_with_plan(session_id: str = "test-plan") -> dict:
    plan = PlanEjecucion(
        id="plan-1",
        tarea="organiza mis descargas",
        pasos=[
            PasoAccion(
                id="paso_1",
                descripcion="Leer descargas",
                herramienta="filesystem.listar",
                parametros={"ruta": "~/Downloads"},
            ),
            PasoAccion(
                id="paso_2",
                descripcion="Mover PDFs",
                herramienta="filesystem.mover",
                parametros={"origen": "~/Downloads/doc.pdf", "destino": "~/Documents/"},
                requiere_confirmacion=True,
            ),
        ],
        complejidad=0.4,
        herramientas_necesarias=["filesystem.listar", "filesystem.mover"],
    )
    state = _make_state(session_id)
    state["current_plan"] = plan
    state["completed_steps"] = [
        ResultadoPaso(id_paso="paso_1", exito=True, salida=["doc.pdf", "foto.png"])
    ]
    state["indice_paso_actual"] = 1
    return state


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path) -> SessionStore:
    return SessionStore(sessions_dir=tmp_path / "sessions")


# ---------------------------------------------------------------------------
# test_session_persists_across_restart
# ---------------------------------------------------------------------------


async def test_session_persists_across_restart(tmp_path: Path) -> None:
    """Los datos guardados por un store son legibles por otro (simula reinicio)."""
    sessions_dir = tmp_path / "sessions"
    state = _make_state("restart-test")

    store1 = SessionStore(sessions_dir=sessions_dir)
    await store1.save("restart-test", state)

    # Nuevo store (simula reinicio del proceso)
    store2 = SessionStore(sessions_dir=sessions_dir)
    restored = await store2.load("restart-test")

    assert restored is not None
    assert restored["session_id"] == "restart-test"
    assert restored["current_task"] == "organiza mis descargas"
    assert restored["indice_paso_actual"] == 2
    assert restored["memory_context"] == "contexto de prueba"


# ---------------------------------------------------------------------------
# test_session_restores_agent_state
# ---------------------------------------------------------------------------


async def test_session_restores_agent_state(store: SessionStore) -> None:
    """El estado restaurado coincide campo a campo con el guardado."""
    state = _make_state_with_plan("full-restore")

    await store.save("full-restore", state)
    restored = await store.load("full-restore")

    assert restored is not None
    assert restored["indice_paso_actual"] == 1
    assert len(restored["completed_steps"]) == 1
    assert restored["completed_steps"][0].id_paso == "paso_1"
    assert restored["completed_steps"][0].exito is True

    plan = restored["current_plan"]
    assert plan is not None
    assert len(plan.pasos) == 2
    assert plan.pasos[0].herramienta == "filesystem.listar"
    assert plan.pasos[1].requiere_confirmacion is True


async def test_session_restores_messages(store: SessionStore) -> None:
    """Los mensajes (dataclass Mensaje) se serializan y restauran correctamente."""
    state = _make_state("msg-test")
    state["messages"] = [
        Mensaje(rol="user", contenido="hola"),
        Mensaje(rol="assistant", contenido="¿en qué puedo ayudarte?"),
    ]
    await store.save("msg-test", state)
    restored = await store.load("msg-test")

    assert restored is not None
    assert len(restored["messages"]) == 2
    assert restored["messages"][0].rol == "user"
    assert restored["messages"][1].contenido == "¿en qué puedo ayudarte?"


async def test_session_waiting_for_user_marked_failed(store: SessionStore) -> None:
    """Si la sesión tenía waiting_for_user=True, el paso pendiente se marca como fallido."""
    paso = PasoAccion(
        id="paso_peligroso",
        descripcion="Eliminar archivos",
        herramienta="filesystem.eliminar",
        requiere_confirmacion=True,
    )
    state = _make_state("interrupted")
    state["waiting_for_user"] = True
    state["paso_pendiente_confirmacion"] = paso

    await store.save("interrupted", state)
    restored = await store.load("interrupted")

    assert restored is not None
    assert restored["waiting_for_user"] is False
    assert restored["paso_pendiente_confirmacion"] is None
    fallidos = restored["failed_steps"]
    assert len(fallidos) == 1
    assert fallidos[0].id_paso == "paso_peligroso"
    assert fallidos[0].exito is False
    assert "replanificando" in fallidos[0].error.lower()


# ---------------------------------------------------------------------------
# test_session_ttl_cleanup
# ---------------------------------------------------------------------------


async def test_session_ttl_cleanup(tmp_path: Path) -> None:
    """Las sesiones expiradas se eliminan en cleanup_expired()."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True)

    # Crear sesión expirada manualmente (saved_at hace 25h)
    expired_data = {
        "saved_at": (datetime.now(UTC) - timedelta(hours=25)).isoformat(),
        "state": {"session_id": "old-session", "current_task": "vieja"},
    }
    (sessions_dir / "old-session.json").write_bytes(orjson.dumps(expired_data))

    # Crear sesión válida (saved_at hace 1h)
    fresh_data = {
        "saved_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        "state": {"session_id": "new-session", "current_task": "nueva"},
    }
    (sessions_dir / "new-session.json").write_bytes(orjson.dumps(fresh_data))

    store = SessionStore(sessions_dir=sessions_dir)
    n = await store.cleanup_expired()

    assert n == 1
    assert not (sessions_dir / "old-session.json").exists()
    assert (sessions_dir / "new-session.json").exists()


async def test_session_load_returns_none_if_expired(tmp_path: Path) -> None:
    """load() devuelve None y elimina el fichero si la sesión está expirada."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True)

    expired_data = {
        "saved_at": (datetime.now(UTC) - timedelta(hours=48)).isoformat(),
        "state": _make_state("expired")
    }
    # Serializar messages manualmente para compatibilidad
    expired_state = dict(_make_state("expired"))
    expired_state["messages"] = []
    expired_data["state"] = expired_state

    (sessions_dir / "expired.json").write_bytes(orjson.dumps(expired_data))

    store = SessionStore(sessions_dir=sessions_dir)
    result = await store.load("expired")

    assert result is None
    assert not (sessions_dir / "expired.json").exists()


async def test_session_load_returns_none_if_not_found(store: SessionStore) -> None:
    """load() devuelve None si la sesión no existe en disco."""
    result = await store.load("nonexistent-session")
    assert result is None


async def test_session_delete_removes_file(store: SessionStore) -> None:
    """delete() elimina el fichero de sesión."""
    state = _make_state("delete-me")
    await store.save("delete-me", state)

    path = store._path("delete-me")
    assert path.exists()

    await store.delete("delete-me")
    assert not path.exists()


async def test_session_cleanup_removes_corrupt_files(tmp_path: Path) -> None:
    """cleanup_expired() elimina ficheros corruptos (JSON inválido)."""
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True)
    (sessions_dir / "corrupt.json").write_bytes(b"esto no es json{{{")

    store = SessionStore(sessions_dir=sessions_dir)
    n = await store.cleanup_expired()

    assert n == 1
    assert not (sessions_dir / "corrupt.json").exists()


async def test_list_sessions_returns_metadata(store: SessionStore) -> None:
    """list_sessions() devuelve metadatos de las sesiones en disco."""
    state_a = _make_state("sess-a")
    state_b = _make_state("sess-b")
    state_b["tarea_completada"] = True

    await store.save("sess-a", state_a)
    await store.save("sess-b", state_b)

    sessions = store.list_sessions()
    ids = {s["session_id"] for s in sessions}
    assert "sess-a" in ids
    assert "sess-b" in ids

    b = next(s for s in sessions if s["session_id"] == "sess-b")
    assert b["tarea_completada"] is True
