"""Servidor MCP para control del sistema macOS."""

from __future__ import annotations

from typing import Any

from actions.system import ControlSistema
from mcp_servers.base import MCPTool, campo, schema_objeto, serializar_dato


class ServidorSistema:
    """Adaptador MCP sobre `actions.system.ControlSistema`."""

    nombre = "sistema"

    def __init__(self, control: ControlSistema | None = None) -> None:
        self._control = control or ControlSistema()

    def herramientas(self) -> list[MCPTool]:
        """Declara herramientas de sistema compatibles con el planner."""
        return [
            MCPTool(
                name="sistema.abrir_app",
                description="Abre una aplicación.",
                input_schema=schema_objeto({
                    "nombre": campo("string", "Nombre de aplicación opcional."),
                    "nombre_app": campo("string", "Nombre de aplicación usado por el prompt."),
                }),
            ),
            MCPTool(
                name="sistema.cerrar_app",
                description="Cierra una aplicación.",
                input_schema=schema_objeto({
                    "nombre": campo("string", "Nombre de aplicación opcional."),
                    "nombre_app": campo("string", "Nombre de aplicación usado por el prompt."),
                    "bundle_id": campo("string", "Bundle identifier opcional."),
                }),
            ),
            MCPTool(
                name="sistema.volumen",
                description="Obtiene o establece volumen.",
                input_schema=schema_objeto({
                    "nivel": campo("integer", "Nivel de volumen entre 0 y 100.", minimum=0, maximum=100),
                }),
            ),
            MCPTool(
                name="sistema.brillo",
                description="Obtiene o establece brillo.",
                input_schema=schema_objeto({
                    "nivel": campo("integer", "Nivel de brillo entre 0 y 100.", minimum=0, maximum=100),
                }),
            ),
            MCPTool(
                name="sistema.clipboard",
                description="Lee o escribe portapapeles.",
                input_schema=schema_objeto({
                    "contenido": campo("string", "Contenido a copiar; omitido lee el portapapeles."),
                }),
            ),
            MCPTool(
                name="sistema.notificacion",
                description="Envía una notificación.",
                input_schema=schema_objeto({
                    "titulo": campo("string", "Título de la notificación."),
                    "mensaje": campo("string", "Mensaje de la notificación."),
                    "subtitulo": campo("string", "Subtítulo opcional."),
                }, ["mensaje"]),
            ),
        ]

    async def ejecutar(self, tool_name: str, params: dict[str, Any]) -> Any:
        """Ejecuta una herramienta de sistema.

        Args:
            tool_name: Nombre canónico de herramienta.
            params: Parámetros de llamada.

        Returns:
            Resultado serializable de la acción.
        """
        match tool_name:
            case "sistema.abrir_app":
                return await self._control.abrir_app(str(params.get("nombre") or params["nombre_app"]))
            case "sistema.cerrar_app":
                ident = str(params.get("bundle_id") or params.get("nombre_app") or params["nombre"])
                return await self._control.cerrar_app(ident)
            case "sistema.volumen":
                if "nivel" in params:
                    return await self._control.establecer_volumen(int(params["nivel"]))
                return await self._control.obtener_volumen()
            case "sistema.brillo":
                if "nivel" in params:
                    return await self._control.establecer_brillo(int(params["nivel"]))
                return await self._control.obtener_brillo()
            case "sistema.clipboard":
                if "contenido" in params:
                    return await self._control.establecer_portapapeles(str(params["contenido"]))
                return serializar_dato(await self._control.obtener_portapapeles())
            case "sistema.notificacion":
                return await self._control.enviar_notificacion(
                    str(params.get("titulo", "JARVIS")),
                    str(params["mensaje"]),
                    subtitulo=str(params.get("subtitulo", "")),
                )
            case _:
                raise ValueError(f"Herramienta sistema desconocida: {tool_name}")
