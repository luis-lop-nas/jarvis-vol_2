"""Servidor MCP que expone operaciones de filesystem como herramientas."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from actions.filesystem import SistemaArchivos


class ServidorFilesystem:
    """Adaptador entre el bus MCP y `SistemaArchivos`."""

    nombre = "filesystem"

    def __init__(self, raiz: Path | None = None) -> None:
        self._fs = SistemaArchivos(raiz)

    def herramientas(self) -> list[dict[str, Any]]:
        """Devuelve la descripción JSON-Schema de las herramientas expuestas."""
        return [
            {
                "name": "fs_leer",
                "description": "Lee el contenido textual de un archivo.",
                "input_schema": {
                    "type": "object",
                    "properties": {"ruta": {"type": "string"}},
                    "required": ["ruta"],
                },
            },
            {
                "name": "fs_escribir",
                "description": "Crea o sobrescribe un archivo.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "ruta": {"type": "string"},
                        "contenido": {"type": "string"},
                    },
                    "required": ["ruta", "contenido"],
                },
            },
            {
                "name": "fs_listar",
                "description": "Lista archivos en una carpeta.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "ruta": {"type": "string"},
                        "patron": {"type": "string", "default": "*"},
                    },
                    "required": ["ruta"],
                },
            },
        ]

    async def ejecutar(self, herramienta: str, argumentos: dict[str, Any]) -> Any:
        """Despacha la llamada a la operación correspondiente."""
        match herramienta:
            case "fs_leer":
                return await self._fs.leer(Path(argumentos["ruta"]))
            case "fs_escribir":
                ruta = await self._fs.escribir(
                    Path(argumentos["ruta"]), argumentos["contenido"]
                )
                return {"ruta": str(ruta)}
            case "fs_listar":
                rutas = await self._fs.listar(
                    Path(argumentos["ruta"]), argumentos.get("patron", "*")
                )
                return [str(r) for r in rutas]
            case _:
                raise ValueError(f"Herramienta desconocida: {herramienta}")
