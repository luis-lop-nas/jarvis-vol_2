"""Servidor MCP para teclado y ratón."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from actions.keyboard_mouse import RatonTeclado
from mcp_servers.base import MCPTool, campo, schema_objeto
from security.audit_log import AuditLog


class ServidorInput:
    """Adaptador MCP sobre `actions.keyboard_mouse.RatonTeclado`."""

    nombre = "teclado"

    def __init__(
        self,
        input_control: RatonTeclado | None = None,
        *,
        callback_confirmacion: Callable[[str], Awaitable[bool]] | None = None,
        audit_log: AuditLog | None = None,
    ) -> None:
        self._input = input_control or RatonTeclado(
            callback_confirmacion=callback_confirmacion,
            audit_log=audit_log,
        )

    def herramientas(self) -> list[MCPTool]:
        """Declara herramientas de teclado y ratón compatibles con el planner."""
        return [
            MCPTool(
                name="teclado.escribir",
                description="Escribe texto en la app activa.",
                input_schema=schema_objeto({
                    "texto": campo("string", "Texto a escribir."),
                    "intervalo": campo("number", "Pausa entre teclas en segundos.", minimum=0),
                }, ["texto"]),
                side_effects=["input.keyboard"],
            ),
            MCPTool(
                name="teclado.atajo",
                description="Ejecuta un atajo de teclado.",
                input_schema=schema_objeto({
                    "teclas": campo("array", "Teclas del atajo en orden.", items={"type": "string"}),
                }, ["teclas"]),
                side_effects=["input.keyboard"],
            ),
            MCPTool(
                name="teclado.click",
                description="Hace click en coordenadas.",
                input_schema=schema_objeto({
                    "x": campo("integer", "Coordenada X."),
                    "y": campo("integer", "Coordenada Y."),
                    "boton": campo("string", "Botón del ratón: left, right o middle."),
                }, ["x", "y"]),
                side_effects=["input.mouse"],
            ),
            MCPTool(
                name="teclado.doble_click",
                description="Hace doble click en coordenadas.",
                input_schema=schema_objeto({
                    "x": campo("integer", "Coordenada X."),
                    "y": campo("integer", "Coordenada Y."),
                }, ["x", "y"]),
                side_effects=["input.mouse"],
            ),
            MCPTool(
                name="teclado.scroll",
                description="Hace scroll en coordenadas.",
                input_schema=schema_objeto({
                    "x": campo("integer", "Coordenada X."),
                    "y": campo("integer", "Coordenada Y."),
                    "dx": campo("integer", "Desplazamiento horizontal opcional."),
                    "dy": campo("integer", "Desplazamiento vertical."),
                    "cantidad": campo("integer", "Alias para cantidad vertical."),
                }, ["x", "y"]),
                side_effects=["input.mouse"],
            ),
        ]

    async def ejecutar(self, tool_name: str, params: dict[str, Any]) -> Any:
        """Ejecuta una herramienta de input.

        Args:
            tool_name: Nombre canónico de herramienta.
            params: Parámetros de llamada.

        Returns:
            `True` si la acción se ejecutó correctamente.
        """
        match tool_name:
            case "teclado.escribir":
                return await self._input.escribir_texto(
                    str(params["texto"]),
                    intervalo=float(params.get("intervalo", 0.02)),
                )
            case "teclado.atajo":
                return await self._input.atajo(*[str(t) for t in params["teclas"]])
            case "teclado.click":
                return await self._input.click(
                    int(params["x"]),
                    int(params["y"]),
                    boton=str(params.get("boton", "left")),
                )
            case "teclado.doble_click":
                return await self._input.doble_click(int(params["x"]), int(params["y"]))
            case "teclado.scroll":
                dy = int(params.get("dy", params.get("cantidad", -3)))
                direccion = "down" if dy < 0 else "up"
                return await self._input.scroll(
                    int(params["x"]),
                    int(params["y"]),
                    abs(dy),
                    direccion=direccion,
                )
            case _:
                raise ValueError(f"Herramienta teclado desconocida: {tool_name}")
