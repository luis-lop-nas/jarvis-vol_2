"""Servidor MCP para comandos de terminal y ejecución de código."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from actions.terminal import Terminal
from mcp_servers.base import MCPTool, campo, schema_objeto, serializar_dato
from security.audit_log import AuditLog


class ServidorCodigo:
    """Adaptador MCP sobre `actions.terminal.Terminal`."""

    nombre = "terminal"

    def __init__(
        self,
        terminal: Terminal | None = None,
        *,
        directorio_trabajo: Path | None = None,
        callback_confirmacion: Callable[[str], Awaitable[bool]] | None = None,
        audit_log: AuditLog | None = None,
    ) -> None:
        self._terminal = terminal or Terminal(
            directorio_trabajo=directorio_trabajo,
            callback_confirmacion=callback_confirmacion,
            audit_log=audit_log,
        )

    def herramientas(self) -> list[MCPTool]:
        """Declara herramientas terminal compatibles con el planner."""
        return [
            MCPTool(
                name="terminal.ejecutar",
                description="Ejecuta un comando permitido.",
                input_schema=schema_objeto({
                    "comando": campo("string", "Comando a ejecutar."),
                    "timeout": campo("number", "Timeout en segundos.", minimum=1),
                    "directorio": campo("string", "Directorio de trabajo opcional."),
                }, ["comando"]),
            ),
            MCPTool(
                name="terminal.python",
                description="Ejecuta código Python tras confirmación.",
                input_schema=schema_objeto({
                    "codigo": campo("string", "Código Python a ejecutar."),
                    "timeout": campo("number", "Timeout en segundos.", minimum=1),
                }, ["codigo"]),
                requires_confirmation=True,
                side_effects=["terminal.python"],
            ),
            MCPTool(
                name="terminal.transmitir",
                description="Ejecuta y captura salida por líneas.",
                input_schema=schema_objeto({
                    "comando": campo("string", "Comando a ejecutar."),
                    "timeout": campo("number", "Timeout en segundos.", minimum=1),
                }, ["comando"]),
            ),
        ]

    async def ejecutar(self, tool_name: str, params: dict[str, Any]) -> Any:
        """Ejecuta una herramienta de terminal.

        Args:
            tool_name: Nombre canónico de herramienta.
            params: Parámetros de llamada.

        Returns:
            Resultado serializable del comando.
        """
        match tool_name:
            case "terminal.ejecutar":
                resultado = await self._terminal.ejecutar_comando(
                    str(params["comando"]),
                    timeout=float(params.get("timeout", 60.0)),
                    directorio=Path(params["directorio"]) if params.get("directorio") else None,
                )
                return serializar_dato(resultado)
            case "terminal.python":
                resultado = await self._terminal.ejecutar_python(
                    str(params["codigo"]),
                    timeout=float(params.get("timeout", 30.0)),
                )
                return serializar_dato(resultado)
            case "terminal.transmitir":
                lineas: list[str] = []
                async for linea in self._terminal.transmitir_comando(
                    str(params["comando"]),
                    timeout=float(params.get("timeout", 60.0)),
                ):
                    lineas.append(linea)
                return {"lineas": lineas}
            case _:
                raise ValueError(f"Herramienta terminal desconocida: {tool_name}")
