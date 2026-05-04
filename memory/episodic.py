"""Memoria episódica: registro temporal de sesiones y aprendizajes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from memory.long_term import FragmentoMemoria, MemoriaLargoPlazo


@dataclass(slots=True)
class Episodio:
    """Una sesión completa o un evento significativo."""

    titulo: str
    resumen: str
    inicio: datetime
    fin: datetime | None = None
    tags: list[str] | None = None


class MemoriaEpisodica:
    """Wrapper sobre `MemoriaLargoPlazo` con la convención de tipo=`episodio`."""

    def __init__(self, almacen: MemoriaLargoPlazo | None = None) -> None:
        self._almacen = almacen or MemoriaLargoPlazo(coleccion="jarvis_episodic")

    async def registrar(self, episodio: Episodio) -> str:
        """Persiste un episodio en la memoria de largo plazo."""
        metadatos: dict[str, Any] = {
            "tipo": "episodio",
            "titulo": episodio.titulo,
            "inicio": episodio.inicio.isoformat(),
            "fin": (episodio.fin or datetime.now(timezone.utc)).isoformat(),
            "tags": ",".join(episodio.tags or []),
        }
        return await self._almacen.guardar(episodio.resumen, metadatos)

    async def guardar_aprendizaje(self, texto: str) -> str:
        """Atajo para registrar un aprendizaje extraído por el reflector."""
        return await self._almacen.guardar(
            texto,
            {"tipo": "aprendizaje", "fecha": datetime.now(timezone.utc).isoformat()},
        )

    async def buscar(self, consulta: str, k: int = 5) -> list[FragmentoMemoria]:
        return await self._almacen.buscar(consulta, k=k, filtro={"tipo": "episodio"})
