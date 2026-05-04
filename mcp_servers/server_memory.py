"""Servidor MCP que expone memoria de largo plazo y vault."""

from __future__ import annotations

from typing import Any

from memory.long_term import MemoriaLargoPlazo
from memory.vault import Vault


class ServidorMemoria:
    """Bridge MCP <-> memoria de largo plazo + vault markdown."""

    nombre = "memory"

    def __init__(
        self,
        memoria: MemoriaLargoPlazo | None = None,
        vault: Vault | None = None,
    ) -> None:
        self._memoria = memoria or MemoriaLargoPlazo()
        self._vault = vault or Vault()

    def herramientas(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "memoria_guardar",
                "description": "Guarda un texto en la memoria de largo plazo.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "texto": {"type": "string"},
                        "metadatos": {"type": "object"},
                    },
                    "required": ["texto"],
                },
            },
            {
                "name": "memoria_buscar",
                "description": "Busca semánticamente en la memoria.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "consulta": {"type": "string"},
                        "k": {"type": "integer", "default": 5},
                    },
                    "required": ["consulta"],
                },
            },
            {
                "name": "vault_leer",
                "description": "Lee una nota del vault personal.",
                "input_schema": {
                    "type": "object",
                    "properties": {"ruta": {"type": "string"}},
                    "required": ["ruta"],
                },
            },
            {
                "name": "vault_escribir",
                "description": "Escribe (o sobrescribe) una nota del vault.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "ruta": {"type": "string"},
                        "contenido": {"type": "string"},
                    },
                    "required": ["ruta", "contenido"],
                },
            },
        ]

    async def ejecutar(self, herramienta: str, argumentos: dict[str, Any]) -> Any:
        match herramienta:
            case "memoria_guardar":
                ident = await self._memoria.guardar(
                    argumentos["texto"], argumentos.get("metadatos")
                )
                return {"id": ident}
            case "memoria_buscar":
                fragmentos = await self._memoria.buscar(
                    argumentos["consulta"], k=argumentos.get("k", 5)
                )
                return [f.__dict__ for f in fragmentos]
            case "vault_leer":
                nota = await self._vault.leer(argumentos["ruta"])
                return {"titulo": nota.titulo, "contenido": nota.contenido}
            case "vault_escribir":
                ruta = await self._vault.escribir(
                    argumentos["ruta"], argumentos["contenido"]
                )
                return {"ruta": str(ruta)}
            case _:
                raise ValueError(f"Herramienta desconocida: {herramienta}")
