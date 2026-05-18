"""Log inmutable de todo lo que hace JARVIS.

Escrito en JSONL — una línea JSON por entrada.
Ruta: ~/Library/Logs/JARVIS/audit_YYYY-MM-DD.jsonl
Retención: 90 días. Nunca loggear secrets.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import orjson
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

_LOG_BASE_DEFAULT = Path.home() / "Library" / "Logs" / "JARVIS"

_SECRET_KEYS = re.compile(
    r"(password|token|secret|api_key|apikey|private_key|credential|auth)",
    re.IGNORECASE,
)


class AuditEntry(BaseModel):
    """Entrada del log de auditoría."""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    session_id: str
    action_type: str   # "filesystem" | "terminal" | "browser" | "comms" | "system"
    action: str
    details: dict[str, Any] = Field(default_factory=dict)
    result: str        # "success" | "failed" | "blocked" | "cancelled"
    risk_level: str    # "safe" | "moderate" | "dangerous" | "blocked"
    confirmed_by_user: bool = False
    authenticated: bool = False
    model_used: str | None = None
    duration_ms: int = 0
    error: str | None = None


class AuditLog:
    """Log append-only en JSONL con rotación diaria.

    Escribe en background via asyncio.Queue — nunca bloquea el agente.
    El log es local y privado; nunca se envía a servicios externos.

    Ejemplo::
        audit = AuditLog()
        await audit.start()
        await audit.log_action(
            session_id="sess-1", action_type="filesystem",
            action="eliminar_archivo", details={"ruta": "~/a.pdf"},
            result="success", risk_level="moderate",
            confirmed=True, authenticated=False, duration_ms=12
        )
    """

    def __init__(self, ruta: Path | None = None, base_dir: Path | None = None) -> None:
        # ruta se acepta por compatibilidad con código existente (legacy path)
        if ruta is not None:
            self._base = ruta.expanduser().parent.resolve()
        elif base_dir is not None:
            self._base = base_dir.expanduser().resolve()
        else:
            self._base = _LOG_BASE_DEFAULT
        self._base.mkdir(parents=True, exist_ok=True)

        self._queue: asyncio.Queue[AuditEntry | None] = asyncio.Queue()
        self._writer_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Ciclo de vida
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Inicia el writer en background. Llamar desde main.py."""
        if self._writer_task is None or self._writer_task.done():
            self._writer_task = asyncio.create_task(
                self._writer_loop(), name="audit-log-writer"
            )

    async def stop(self) -> None:
        """Para el writer de forma limpia."""
        await self._queue.put(None)
        if self._writer_task is not None:
            await self._writer_task

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    async def log(self, entry: AuditEntry) -> None:
        """Añade una entrada al log (fire-and-forget).

        Ejemplo::
            await audit.log(AuditEntry(session_id="s1", ...))
        """
        await self._queue.put(entry)

    async def log_action(
        self,
        *,
        session_id: str,
        action_type: str,
        action: str,
        details: dict[str, Any] | None = None,
        result: str,
        risk_level: str,
        confirmed: bool,
        authenticated: bool,
        duration_ms: int,
        error: str | None = None,
        model_used: str | None = None,
    ) -> None:
        """Helper para loggear desde cualquier módulo.

        Ejemplo::
            await audit.log_action(
                session_id="s1", action_type="comms", action="enviar_email",
                details={"dest": "x@x.com"}, result="success",
                risk_level="dangerous", confirmed=True, authenticated=True,
                duration_ms=230
            )
        """
        entry = AuditEntry(
            session_id=session_id,
            action_type=action_type,
            action=action,
            details=self._sanitize(details or {}),
            result=result,
            risk_level=risk_level,
            confirmed_by_user=confirmed,
            authenticated=authenticated,
            duration_ms=duration_ms,
            error=error,
            model_used=model_used,
        )
        await self.log(entry)

    async def registrar(self, evento: str, datos: dict[str, Any] | None = None) -> None:
        """Compatibilidad con la API anterior — registra un evento simple.

        Ejemplo::
            await audit.registrar("eliminar_archivo", {"ruta": "~/a.txt"})
        """
        entry = AuditEntry(
            session_id="",
            action_type="legacy",
            action=evento,
            details=self._sanitize(datos or {}),
            result="success",
            risk_level="safe",
        )
        await self.log(entry)

    async def get_entries(
        self,
        *,
        fecha: date | None = None,
        session_id: str | None = None,
        action_type: str | None = None,
        result: str | None = None,
    ) -> list[AuditEntry]:
        """Consulta el log del día especificado (hoy si no se indica).

        Ejemplo::
            entries = await audit.get_entries(action_type="comms", result="success")
        """
        target = fecha or date.today()
        ruta = self._daily_path(target)
        if not ruta.exists():
            return []

        texto = await asyncio.to_thread(ruta.read_text, "utf-8")
        entradas: list[AuditEntry] = []
        for linea in texto.strip().splitlines():
            if not linea:
                continue
            try:
                data = orjson.loads(linea)
                entry = AuditEntry.model_validate(data)
                if session_id and entry.session_id != session_id:
                    continue
                if action_type and entry.action_type != action_type:
                    continue
                if result and entry.result != result:
                    continue
                entradas.append(entry)
            except Exception:
                pass
        return entradas

    async def get_session_summary(self, session_id: str) -> dict[str, int]:
        """Resumen de una sesión: totales, fallidas, bloqueadas.

        Ejemplo::
            summary = await audit.get_session_summary("sess-abc")
        """
        entries = await self.get_entries(session_id=session_id)
        return {
            "total": len(entries),
            "failed": sum(1 for e in entries if e.result == "failed"),
            "blocked": sum(1 for e in entries if e.result == "blocked"),
            "success": sum(1 for e in entries if e.result == "success"),
        }

    async def search(
        self,
        query: str,
        date_range: tuple[date, date] | None = None,
    ) -> list[AuditEntry]:
        """Búsqueda en los logs por texto libre.

        Ejemplo::
            results = await audit.search("eliminar")
        """
        start = date_range[0] if date_range else date.today()
        end = date_range[1] if date_range else date.today()
        query_lower = query.lower()
        resultados: list[AuditEntry] = []

        current = start
        while current <= end:
            for entry in await self.get_entries(fecha=current):
                if query_lower in entry.action.lower() or query_lower in str(entry.details).lower():
                    resultados.append(entry)
            current += timedelta(days=1)
        return resultados

    async def export_csv(self, date_range: tuple[date, date] | None = None) -> Path:
        """Exporta entradas a CSV para revisión humana.

        Ejemplo::
            csv_path = await audit.export_csv()
        """
        start = date_range[0] if date_range else date.today()
        end = date_range[1] if date_range else date.today()

        all_entries: list[AuditEntry] = []
        current = start
        while current <= end:
            all_entries.extend(await self.get_entries(fecha=current))
            current += timedelta(days=1)

        out_path = self._base / f"export_{start}_{end}.csv"
        buf = io.StringIO()
        if all_entries:
            writer = csv.DictWriter(buf, fieldnames=list(all_entries[0].model_fields.keys()))
            writer.writeheader()
            for e in all_entries:
                writer.writerow(e.model_dump())
        await asyncio.to_thread(out_path.write_text, buf.getvalue(), "utf-8")
        return out_path

    async def leer_recientes(self, n: int = 100) -> list[dict[str, Any]]:
        """Compatibilidad con API antigua — devuelve últimas n entradas del día."""
        entries = await self.get_entries()
        return [e.model_dump(mode="json") for e in entries[-n:]]

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------

    def _daily_path(self, d: date) -> Path:
        return self._base / f"audit_{d.isoformat()}.jsonl"

    def _sanitize(self, datos: dict[str, Any]) -> dict[str, Any]:
        """Elimina valores cuyas claves sugieren secrets. Nunca loggear passwords."""
        resultado: dict[str, Any] = {}
        for k, v in datos.items():
            if _SECRET_KEYS.search(str(k)):
                resultado[k] = "***REDACTED***"
            elif isinstance(v, dict):
                resultado[k] = self._sanitize(v)
            else:
                resultado[k] = v
        return resultado

    async def _writer_loop(self) -> None:
        """Consumidor de la cola — escribe en el fichero JSONL diario."""
        while True:
            item = await self._queue.get()
            if item is None:
                self._queue.task_done()
                break
            try:
                linea = orjson.dumps(item.model_dump(mode="json")).decode("utf-8") + "\n"
                ruta = self._daily_path(date.today())
                ruta.parent.mkdir(parents=True, exist_ok=True)
                await asyncio.to_thread(self._append_sync, ruta, linea)
            except Exception:
                log.exception("Error escribiendo en audit log")
            finally:
                self._queue.task_done()

    @staticmethod
    def _append_sync(ruta: Path, linea: str) -> None:
        import os
        # O_APPEND para garantizar atomicidad; 0o600 para privacidad
        fd = os.open(str(ruta), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, linea.encode("utf-8"))
        finally:
            os.close(fd)
