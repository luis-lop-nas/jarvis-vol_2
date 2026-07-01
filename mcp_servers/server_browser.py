"""Servidor MCP para navegación web."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from actions.browser import ControlSafari, Navegador
from mcp_servers.base import MCPTool, campo, schema_objeto, serializar_dato


class ServidorNavegador:
    """Adaptador MCP sobre `actions.browser.Navegador`."""

    nombre = "browser"

    def __init__(
        self,
        navegador: Navegador | None = None,
        safari: ControlSafari | None = None,
        *,
        callback_confirmacion: Any | None = None,
        audit_log: Any | None = None,
    ) -> None:
        self._navegador = navegador or Navegador(
            callback_confirmacion=callback_confirmacion,
            audit_log=audit_log,
        )
        self._safari = safari or ControlSafari()

    def herramientas(self) -> list[MCPTool]:
        """Declara herramientas de navegador compatibles con el planner."""
        return [
            MCPTool(
                name="browser.abrir",
                description="Abre y extrae una URL.",
                input_schema=schema_objeto({
                    "url": campo("string", "URL absoluta a abrir."),
                    "incluir_html": campo("boolean", "Incluye HTML además de texto visible."),
                }, ["url"]),
                side_effects=["browser.navigate"],
            ),
            MCPTool(
                name="browser.leer",
                description="Lee texto visible de una URL o pestaña activa.",
                input_schema=schema_objeto({
                    "url": campo("string", "URL opcional; si se omite usa pestaña activa."),
                    "incluir_html": campo("boolean", "Incluye HTML además de texto visible."),
                }),
            ),
            MCPTool(
                name="browser.click",
                description="Hace click en selector CSS.",
                input_schema=schema_objeto({
                    "selector": campo("string", "Selector CSS del elemento."),
                    "pagina": campo("object", "Objeto página Playwright opcional inyectado por runtime."),
                }, ["selector"]),
                side_effects=["browser.click"],
            ),
            MCPTool(
                name="browser.fill",
                description="Rellena un campo CSS.",
                input_schema=schema_objeto({
                    "selector": campo("string", "Selector CSS del campo."),
                    "valor": campo("string", "Valor a escribir."),
                    "pagina": campo("object", "Objeto página Playwright opcional inyectado por runtime."),
                }, ["selector", "valor"]),
                side_effects=["browser.fill"],
            ),
            MCPTool(
                name="browser.ejecutar_js",
                description="Ejecuta JavaScript tras confirmación.",
                input_schema=schema_objeto({
                    "codigo": campo("string", "Código JavaScript a ejecutar."),
                    "pagina": campo("object", "Objeto página Playwright opcional inyectado por runtime."),
                }, ["codigo"]),
                requires_confirmation=True,
                side_effects=["browser.javascript"],
            ),
            MCPTool(
                name="browser.screenshot",
                description="Captura página actual o descarga una URL si se proporciona destino.",
                input_schema=schema_objeto({
                    "url": campo("string", "URL a descargar cuando hay destino."),
                    "destino": campo("string", "Ruta destino de descarga opcional."),
                    "pagina": campo("object", "Objeto página Playwright opcional inyectado por runtime."),
                }),
            ),
        ]

    async def ejecutar(self, tool_name: str, params: dict[str, Any]) -> Any:
        """Ejecuta una herramienta de navegador.

        Args:
            tool_name: Nombre canónico de herramienta.
            params: Parámetros de llamada.

        Returns:
            Resultado serializable de navegador.
        """
        # El Navegador (Playwright) es de larga vida y no usa `async with`:
        # arráncalo perezosamente en la primera herramienta que lo necesite.
        await self._navegador.asegurar_iniciado()

        match tool_name:
            case "browser.abrir" | "browser.leer":
                if tool_name == "browser.abrir":
                    await self._safari.abrir_url(str(params["url"]))
                url = str(params.get("url") or await self._safari.obtener_url_actual() or "")
                if not url:
                    raise ValueError("browser.leer requiere una URL o una pestaña activa")
                return serializar_dato(
                    await self._navegador.obtener_contenido_pagina(
                        url,
                        incluir_html=bool(params.get("incluir_html", False)),
                    )
                )
            case "browser.click":
                return await self._navegador.click_elemento(str(params["selector"]), pagina=params.get("pagina"))
            case "browser.fill":
                return await self._navegador.rellenar_campo(
                    str(params["selector"]),
                    str(params["valor"]),
                    pagina=params.get("pagina"),
                )
            case "browser.ejecutar_js":
                return serializar_dato(
                    await self._navegador.ejecutar_js(
                        str(params["codigo"]),
                        pagina=params.get("pagina"),
                    )
                )
            case "browser.screenshot":
                if "destino" in params:
                    ruta = await self._navegador.descargar_archivo(
                        str(params["url"]),
                        Path(params["destino"]),
                    )
                    return {"ruta": str(ruta) if ruta else None}
                return serializar_dato(await self._navegador.captura_pagina(pagina=params.get("pagina")))
            case _:
                raise ValueError(f"Herramienta browser desconocida: {tool_name}")
