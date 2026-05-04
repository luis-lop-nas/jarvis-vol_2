"""Servidor MCP que expone ejecución de código y comandos."""

from __future__ import annotations

from typing import Any

from actions.terminal import Terminal


class ServidorCodigo:
    """Bridge MCP <-> shell."""

    nombre = "code"

    def __init__(self) -> None:
        self._terminal = Terminal()

    def herramientas(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "shell",
                "description": "Ejecuta un comando en una subshell con timeout.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "comando": {"type": "string"},
                        "timeout": {"type": "number", "default": 60},
                    },
                    "required": ["comando"],
                },
            },
        ]

    async def ejecutar(self, herramienta: str, argumentos: dict[str, Any]) -> Any:
        match herramienta:
            case "shell":
                resultado = await self._terminal.ejecutar(
                    argumentos["comando"], timeout=argumentos.get("timeout", 60)
                )
                return {
                    "codigo": resultado.codigo,
                    "stdout": resultado.stdout,
                    "stderr": resultado.stderr,
                }
            case _:
                raise ValueError(f"Herramienta desconocida: {herramienta}")
