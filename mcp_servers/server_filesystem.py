"""Servidor MCP para operaciones seguras de filesystem."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable

from actions.filesystem import SistemaArchivos
from mcp_servers.base import MCPTool, campo, schema_objeto, serializar_dato
from security.audit_log import AuditLog


class ServidorFilesystem:
    """Adaptador MCP sobre `actions.filesystem.SistemaArchivos`."""

    nombre = "filesystem"

    def __init__(
        self,
        raiz: Path | None = None,
        *,
        filesystem: SistemaArchivos | None = None,
        callback_confirmacion: Callable[[str], Awaitable[bool]] | None = None,
        audit_log: AuditLog | None = None,
    ) -> None:
        self._fs = filesystem or SistemaArchivos(
            raiz,
            callback_confirmacion=callback_confirmacion,
            audit_log=audit_log,
        )

    def herramientas(self) -> list[MCPTool]:
        """Declara las herramientas filesystem con nombres canónicos del planner."""
        return [
            MCPTool(
                name="filesystem.leer",
                description="Lee un archivo de texto dentro del sandbox.",
                input_schema=schema_objeto({
                    "ruta": campo("string", "Ruta del archivo a leer."),
                }, ["ruta"]),
            ),
            MCPTool(
                name="filesystem.escribir",
                description="Escribe texto en un archivo dentro del sandbox.",
                input_schema=schema_objeto({
                    "ruta": campo("string", "Ruta del archivo a escribir."),
                    "contenido": campo("string", "Contenido completo que se escribirá."),
                }, ["ruta", "contenido"]),
                requires_confirmation=True,
                side_effects=["filesystem.write"],
            ),
            MCPTool(
                name="filesystem.listar",
                description="Lista el contenido de un directorio.",
                input_schema=schema_objeto({
                    "ruta": campo("string", "Directorio a listar."),
                }, ["ruta"]),
            ),
            MCPTool(
                name="filesystem.buscar",
                description="Busca archivos por nombre dentro de un directorio.",
                input_schema=schema_objeto({
                    "consulta": campo("string", "Texto a buscar en nombres de archivo."),
                    "directorio": campo("string", "Directorio base de búsqueda."),
                    "recursivo": campo("boolean", "Indica si debe buscar en subdirectorios."),
                }, ["consulta", "directorio"]),
            ),
            MCPTool(
                name="filesystem.mover",
                description="Mueve un archivo dentro del sandbox.",
                input_schema=schema_objeto({
                    "origen": campo("string", "Ruta actual del archivo."),
                    "destino": campo("string", "Ruta destino."),
                }, ["origen", "destino"]),
                requires_confirmation=True,
                side_effects=["filesystem.move"],
            ),
            MCPTool(
                name="filesystem.copiar",
                description="Copia un archivo dentro del sandbox.",
                input_schema=schema_objeto({
                    "origen": campo("string", "Ruta actual del archivo."),
                    "destino": campo("string", "Ruta destino."),
                }, ["origen", "destino"]),
                side_effects=["filesystem.copy"],
            ),
            MCPTool(
                name="filesystem.eliminar",
                description="Elimina un archivo o directorio dentro del sandbox.",
                input_schema=schema_objeto({
                    "ruta": campo("string", "Ruta a eliminar."),
                    "directorio": campo("boolean", "Marca que la ruta es un directorio."),
                    "recursivo": campo("boolean", "Permite eliminar directorios recursivamente."),
                }, ["ruta"]),
                requires_confirmation=True,
                side_effects=["filesystem.delete"],
            ),
        ]

    async def ejecutar(self, tool_name: str, params: dict[str, Any]) -> Any:
        """Ejecuta una herramienta filesystem.

        Args:
            tool_name: Nombre canónico de herramienta.
            params: Parámetros validados por el planner/bus.

        Returns:
            Resultado serializable de la acción.
        """
        match tool_name:
            case "filesystem.leer":
                return await self._fs.leer_archivo(Path(params["ruta"]))
            case "filesystem.escribir":
                return await self._fs.escribir_archivo(Path(params["ruta"]), str(params["contenido"]))
            case "filesystem.listar":
                entradas = await self._fs.listar_directorio(Path(params["ruta"]))
                return serializar_dato(entradas)
            case "filesystem.buscar":
                entradas = await self._fs.buscar_archivos(
                    str(params["consulta"]),
                    Path(params["directorio"]),
                    recursivo=bool(params.get("recursivo", True)),
                )
                return serializar_dato(entradas)
            case "filesystem.mover":
                return await self._fs.mover_archivo(Path(params["origen"]), Path(params["destino"]))
            case "filesystem.copiar":
                return await self._fs.copiar_archivo(Path(params["origen"]), Path(params["destino"]))
            case "filesystem.eliminar":
                ruta = Path(params["ruta"])
                if bool(params.get("directorio", False)):
                    return await self._fs.eliminar_directorio(
                        ruta,
                        recursivo=bool(params.get("recursivo", False)),
                    )
                return await self._fs.eliminar_archivo(ruta)
            case _:
                raise ValueError(f"Herramienta filesystem desconocida: {tool_name}")
