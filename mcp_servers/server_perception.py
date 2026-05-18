"""Servidor MCP para percepción de pantalla y accesibilidad."""

from __future__ import annotations

from typing import Any

from mcp_servers.base import MCPTool, campo, schema_objeto, serializar_dato


class ServidorPercepcion:
    """Adaptador MCP sobre módulos de `perception/`."""

    nombre = "percepcion"

    def herramientas(self) -> list[MCPTool]:
        """Declara herramientas de percepción compatibles con el planner."""
        return [
            MCPTool(
                name="percepcion.screenshot",
                description="Captura pantalla o región.",
                input_schema=schema_objeto({
                    "x": campo("integer", "Coordenada X de la región."),
                    "y": campo("integer", "Coordenada Y de la región."),
                    "width": campo("integer", "Ancho de región en píxeles.", minimum=1),
                    "height": campo("integer", "Alto de región en píxeles.", minimum=1),
                }),
                annotations={"readOnlyHint": True, "openWorldHint": False},
            ),
            MCPTool(
                name="percepcion.accesibilidad",
                description="Lee contexto de accesibilidad.",
                input_schema=schema_objeto(),
                annotations={"readOnlyHint": True, "openWorldHint": False},
            ),
        ]

    async def ejecutar(self, tool_name: str, params: dict[str, Any]) -> Any:
        """Ejecuta una herramienta de percepción.

        Args:
            tool_name: Nombre canónico de herramienta.
            params: Parámetros de llamada.

        Returns:
            Resultado serializable de percepción.
        """
        match tool_name:
            case "percepcion.screenshot":
                from perception.screenshot import capture_region, capture_screen

                if {"x", "y", "width", "height"} <= set(params):
                    data = await capture_region(
                        int(params["x"]),
                        int(params["y"]),
                        int(params["width"]),
                        int(params["height"]),
                    )
                else:
                    data = await capture_screen()
                return {"bytes": len(data)}
            case "percepcion.accesibilidad":
                from perception.accessibility import (
                    get_active_window,
                    get_focused_element,
                    get_frontmost_app,
                )

                app, window, focused = await _gather_accessibility(
                    get_frontmost_app(),
                    get_active_window(),
                    get_focused_element(),
                )
                return serializar_dato(
                    {
                        "frontmost_app": app,
                        "active_window": window,
                        "focused_element": focused,
                    }
                )
            case _:
                raise ValueError(f"Herramienta percepción desconocida: {tool_name}")


async def _gather_accessibility(*aws: Any) -> tuple[Any, ...]:
    """Ejecuta llamadas de accesibilidad en paralelo.

    Args:
        *aws: Awaitables de percepción.

    Returns:
        Tupla con los resultados en el mismo orden.
    """
    import asyncio

    return tuple(await asyncio.gather(*aws))
