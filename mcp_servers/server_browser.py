"""Servidor MCP que expone el navegador como herramientas."""

from __future__ import annotations

from typing import Any

from actions.browser import Navegador


class ServidorNavegador:
    """Bridge MCP <-> Playwright."""

    nombre = "browser"

    def __init__(self, navegador: Navegador) -> None:
        self._navegador = navegador

    def herramientas(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "browser_extraer",
                "description": "Visita una URL y devuelve título y texto plano.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "incluir_html": {"type": "boolean", "default": False},
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "browser_rellenar_form",
                "description": "Rellena un formulario y opcionalmente lo envía.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "campos": {"type": "object"},
                        "selector_envio": {"type": "string"},
                    },
                    "required": ["url", "campos"],
                },
            },
        ]

    async def ejecutar(self, herramienta: str, argumentos: dict[str, Any]) -> Any:
        match herramienta:
            case "browser_extraer":
                resultado = await self._navegador.extraer(
                    argumentos["url"],
                    incluir_html=argumentos.get("incluir_html", False),
                )
                return resultado.__dict__
            case "browser_rellenar_form":
                pagina = await self._navegador.rellenar_formulario(
                    argumentos["url"],
                    argumentos["campos"],
                    argumentos.get("selector_envio"),
                )
                return {"url": pagina.url}
            case _:
                raise ValueError(f"Herramienta desconocida: {herramienta}")
