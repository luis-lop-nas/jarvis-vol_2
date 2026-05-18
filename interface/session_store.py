"""Persistencia de sesiones del agente en disco.

Serializa AgentState a JSON en ~/.jarvis/sessions/{session_id}.json tras cada
paso. Al arrancar el servidor, limpia sesiones expiradas (TTL configurado por
session_ttl_hours en settings).

Limitación documentada: si el servidor se reinicia mientras hay un paso en
estado "actuando" o "esperando", el resultado es desconocido. El paso pendiente
se marca como fallido para que el agente replanifique desde el último estado
conocido.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import orjson

from config import settings

if TYPE_CHECKING:
    from core.agent import AgentState

log = logging.getLogger(__name__)

_SESSIONS_DIR = Path.home() / ".jarvis" / "sessions"


class SessionStore:
    """Persiste y restaura AgentState en ~/.jarvis/sessions/{session_id}.json.

    Tras cada paso del agente se llama a save(). Al recibir un session_id
    conocido en POST /chat se llama a load() para restaurar el contexto.
    Las sesiones expiradas (>= session_ttl_hours) se eliminan en cleanup_expired().

    Ejemplo::
        store = SessionStore()
        await store.save("abc123", state)
        restored = await store.load("abc123")
        if restored:
            print("sesión restaurada")
    """

    def __init__(self, sessions_dir: Path | None = None) -> None:
        self._dir = sessions_dir or _SESSIONS_DIR
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, session_id: str) -> Path:
        return self._dir / f"{session_id}.json"

    def _serialize_state(self, state: AgentState) -> dict[str, Any]:
        """Convierte AgentState a dict serializable a JSON."""
        from core.planner import PasoAccion, PlanEjecucion
        from core.reflector import ResultadoPaso

        def _ser_mensaje(m: Any) -> dict:
            return asdict(m) if hasattr(m, "__dataclass_fields__") else dict(m)

        def _ser_pydantic(obj: Any) -> dict | None:
            if obj is None:
                return None
            return obj.model_dump(mode="json")

        return {
            "messages": [_ser_mensaje(m) for m in state.get("messages", [])],
            "current_task": state.get("current_task"),
            "current_plan": _ser_pydantic(state.get("current_plan")),
            "completed_steps": [_ser_pydantic(r) for r in state.get("completed_steps", [])],
            "failed_steps": [_ser_pydantic(r) for r in state.get("failed_steps", [])],
            "retry_count": state.get("retry_count", 0),
            "replan_count": state.get("replan_count", 0),
            "memory_context": state.get("memory_context", ""),
            "waiting_for_user": state.get("waiting_for_user", False),
            "paso_pendiente_confirmacion": _ser_pydantic(state.get("paso_pendiente_confirmacion")),
            "abort_reason": state.get("abort_reason"),
            "session_id": state.get("session_id", ""),
            "indice_paso_actual": state.get("indice_paso_actual", 0),
            "tarea_completada": state.get("tarea_completada", False),
            # system_context se omite — contiene datos del sistema que caducan
        }

    def _deserialize_state(self, data: dict[str, Any]) -> AgentState:
        """Reconstruye AgentState desde dict JSON.

        Si waiting_for_user=True y hay un paso pendiente, lo marca como fallido
        (el servidor se reinició antes de recibir respuesta del usuario).
        """
        from core.planner import PasoAccion, PlanEjecucion
        from core.reflector import ResultadoPaso
        from models.base import Mensaje

        messages = [
            Mensaje(
                rol=m["rol"],
                contenido=m["contenido"],
                nombre=m.get("nombre"),
                imagenes_base64=m.get("imagenes_base64", []),
                metadatos=m.get("metadatos", {}),
            )
            for m in data.get("messages", [])
        ]

        current_plan = (
            PlanEjecucion.model_validate(data["current_plan"])
            if data.get("current_plan")
            else None
        )
        completed_steps = [
            ResultadoPaso.model_validate(r)
            for r in data.get("completed_steps", [])
            if r is not None
        ]
        failed_steps = [
            ResultadoPaso.model_validate(r)
            for r in data.get("failed_steps", [])
            if r is not None
        ]
        paso_pendiente = (
            PasoAccion.model_validate(data["paso_pendiente_confirmacion"])
            if data.get("paso_pendiente_confirmacion")
            else None
        )

        state: AgentState = {
            "messages": messages,
            "current_task": data.get("current_task"),
            "current_plan": current_plan,
            "completed_steps": completed_steps,
            "failed_steps": failed_steps,
            "retry_count": data.get("retry_count", 0),
            "replan_count": data.get("replan_count", 0),
            "system_context": {},
            "memory_context": data.get("memory_context", ""),
            "waiting_for_user": data.get("waiting_for_user", False),
            "paso_pendiente_confirmacion": paso_pendiente,
            "abort_reason": data.get("abort_reason"),
            "session_id": data.get("session_id", ""),
            "indice_paso_actual": data.get("indice_paso_actual", 0),
            "tarea_completada": data.get("tarea_completada", False),
        }

        # Limitación documentada: paso interrumpido durante confirmación/ejecución
        # → se marca como fallido para forzar replanificación.
        if state.get("waiting_for_user") and paso_pendiente is not None:
            interrupted = ResultadoPaso(
                id_paso=paso_pendiente.id,
                exito=False,
                error="Servidor reiniciado durante confirmación pendiente — replanificando.",
                duracion_ms=0,
            )
            state["failed_steps"] = list(failed_steps) + [interrupted]
            state["waiting_for_user"] = False
            state["paso_pendiente_confirmacion"] = None

        return state

    async def save(self, session_id: str, state: AgentState) -> None:
        """Serializa y persiste el estado de la sesión en disco.

        Operación no bloqueante: usa asyncio.to_thread para la escritura.
        Los errores se registran pero no se propagan — la persistencia es best-effort.

        Ejemplo::
            await store.save("abc123", estado)
        """
        path = self._path(session_id)
        try:
            payload = {
                "saved_at": datetime.now(UTC).isoformat(),
                "state": self._serialize_state(state),
            }
            data = orjson.dumps(payload)
            await asyncio.to_thread(path.write_bytes, data)
        except Exception:
            log.warning("No se pudo persistir sesión %s", session_id, exc_info=True)

    async def load(self, session_id: str) -> AgentState | None:
        """Carga y deserializa el estado de una sesión desde disco.

        Devuelve None si la sesión no existe, está expirada o no se puede leer.

        Ejemplo::
            state = await store.load("abc123")
        """
        path = self._path(session_id)
        if not path.exists():
            return None
        try:
            raw = await asyncio.to_thread(path.read_bytes)
            payload = orjson.loads(raw)
            saved_at = datetime.fromisoformat(payload["saved_at"])
            ttl = timedelta(hours=settings.session_ttl_hours)
            if datetime.now(UTC) - saved_at > ttl:
                log.info("Sesión %s expirada (saved_at=%s), descartando.", session_id, saved_at)
                await self.delete(session_id)
                return None
            return self._deserialize_state(payload["state"])
        except Exception:
            log.warning("No se pudo restaurar sesión %s", session_id, exc_info=True)
            return None

    async def delete(self, session_id: str) -> None:
        """Elimina el fichero de sesión del disco.

        Ejemplo::
            await store.delete("abc123")
        """
        path = self._path(session_id)
        try:
            await asyncio.to_thread(path.unlink, missing_ok=True)
        except Exception:
            log.warning("No se pudo eliminar sesión %s", session_id, exc_info=True)

    async def cleanup_expired(self) -> int:
        """Elimina sesiones expiradas. Devuelve el número eliminadas.

        Se llama automáticamente como tarea background al arrancar el servidor.
        Las sesiones corruptas (JSON inválido) también se eliminan.

        Ejemplo::
            n = await store.cleanup_expired()
            print(f"{n} sesiones expiradas eliminadas")
        """
        ttl = timedelta(hours=settings.session_ttl_hours)
        now = datetime.now(UTC)
        eliminadas = 0

        def _scan() -> list[tuple[Path, bool]]:
            """Lee todos los ficheros y decide cuáles eliminar (I/O en thread)."""
            resultado: list[tuple[Path, bool]] = []
            for p in self._dir.glob("*.json"):
                try:
                    payload = orjson.loads(p.read_bytes())
                    saved_at = datetime.fromisoformat(payload["saved_at"])
                    resultado.append((p, now - saved_at > ttl))
                except Exception:
                    resultado.append((p, True))  # corrupto → eliminar
            return resultado

        entries = await asyncio.to_thread(_scan)
        for path, expired in entries:
            if expired:
                try:
                    await asyncio.to_thread(path.unlink, missing_ok=True)
                    eliminadas += 1
                except Exception:
                    log.warning("Error eliminando sesión expirada %s", path.name, exc_info=True)

        if eliminadas:
            log.info("Cleanup sesiones: %d expiradas eliminadas.", eliminadas)
        return eliminadas

    def list_sessions(self) -> list[dict[str, Any]]:
        """Devuelve metadatos de las sesiones en disco (sincrónico, para el dashboard).

        Ejemplo::
            sessions = store.list_sessions()
            for s in sessions:
                print(s["session_id"], s["saved_at"])
        """
        sessions: list[dict[str, Any]] = []
        for path in sorted(self._dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                payload = orjson.loads(path.read_bytes())
                state = payload.get("state", {})
                sessions.append({
                    "session_id": path.stem,
                    "saved_at": payload.get("saved_at"),
                    "current_task": state.get("current_task"),
                    "tarea_completada": state.get("tarea_completada", False),
                    "waiting_for_user": state.get("waiting_for_user", False),
                    "indice_paso_actual": state.get("indice_paso_actual", 0),
                })
            except Exception:
                pass
        return sessions
