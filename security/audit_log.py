"""Registro append-only de todas las acciones del agente."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import orjson

from config import settings


class AuditLog:
    """Log estructurado en JSONL, append-only y con flush por línea."""

    def __init__(self, ruta: Path | None = None) -> None:
        self._ruta = (ruta or settings.audit_log_path).expanduser().resolve()
        self._ruta.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()

    async def registrar(self, evento: str, datos: dict[str, Any] | None = None) -> None:
        """Añade un evento al log con timestamp UTC."""
        entrada = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "evento": evento,
            "datos": datos or {},
        }
        linea = orjson.dumps(entrada).decode("utf-8") + "\n"
        async with self._lock:
            await asyncio.to_thread(self._append_sync, linea)

    def _append_sync(self, linea: str) -> None:
        with self._ruta.open("a", encoding="utf-8") as f:
            f.write(linea)

    async def leer_recientes(self, n: int = 100) -> list[dict[str, Any]]:
        """Devuelve las últimas `n` entradas del log."""
        if not self._ruta.exists():
            return []
        contenido = await asyncio.to_thread(self._ruta.read_text, "utf-8")
        lineas = contenido.strip().splitlines()[-n:]
        return [orjson.loads(l) for l in lineas]
