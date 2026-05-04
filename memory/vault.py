"""Vault personal: integración con un Obsidian vault u otro almacén markdown."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from config import settings


@dataclass(slots=True)
class Nota:
    """Nota markdown del vault."""

    ruta: Path
    titulo: str
    contenido: str


class Vault:
    """Lectura y escritura de notas en una carpeta markdown."""

    def __init__(self, raiz: Path | None = None) -> None:
        self._raiz = (raiz or settings.vault_path).expanduser().resolve()
        self._raiz.mkdir(parents=True, exist_ok=True)

    async def leer(self, ruta_relativa: str) -> Nota:
        """Lee una nota dada su ruta relativa al vault."""
        ruta = self._validar(ruta_relativa)
        contenido = await asyncio.to_thread(ruta.read_text, "utf-8")
        return Nota(ruta=ruta, titulo=ruta.stem, contenido=contenido)

    async def escribir(self, ruta_relativa: str, contenido: str) -> Path:
        """Crea o sobrescribe una nota dentro del vault."""
        ruta = self._validar(ruta_relativa)
        await asyncio.to_thread(ruta.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(ruta.write_text, contenido, "utf-8")
        return ruta

    async def listar(self, subcarpeta: str = "") -> list[Path]:
        """Lista las notas .md de una subcarpeta del vault."""
        base = self._validar(subcarpeta) if subcarpeta else self._raiz
        return await asyncio.to_thread(lambda: list(base.rglob("*.md")))

    async def buscar_texto(self, termino: str) -> list[Nota]:
        """Búsqueda lineal de un término en todas las notas (case-insensitive)."""
        notas: list[Nota] = []
        termino_low = termino.lower()
        for ruta in await self.listar():
            contenido = await asyncio.to_thread(ruta.read_text, "utf-8")
            if termino_low in contenido.lower():
                notas.append(Nota(ruta=ruta, titulo=ruta.stem, contenido=contenido))
        return notas

    def _validar(self, ruta_relativa: str) -> Path:
        candidato = (self._raiz / ruta_relativa).resolve()
        if not candidato.is_relative_to(self._raiz):
            raise PermissionError(f"Ruta fuera del vault: {ruta_relativa}")
        return candidato
