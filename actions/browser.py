"""Control del navegador vía Playwright (asíncrono)."""

from __future__ import annotations

from dataclasses import dataclass
from types import TracebackType
from typing import Self

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
)


@dataclass(slots=True)
class ResultadoExtraccion:
    """Datos extraídos de una página."""

    url: str
    titulo: str
    texto: str
    html: str | None = None


class Navegador:
    """Wrapper sobre Playwright orientado a tareas del agente."""

    def __init__(self, headless: bool = False, perfil: str = "default") -> None:
        self._headless = headless
        self._perfil = perfil
        self._playwright: Playwright | None = None
        self._navegador: Browser | None = None
        self._contexto: BrowserContext | None = None

    async def __aenter__(self) -> Self:
        await self.iniciar()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.cerrar()

    async def iniciar(self) -> None:
        """Arranca Playwright y abre un contexto persistente."""
        self._playwright = await async_playwright().start()
        self._navegador = await self._playwright.chromium.launch(headless=self._headless)
        self._contexto = await self._navegador.new_context()

    async def cerrar(self) -> None:
        if self._contexto:
            await self._contexto.close()
        if self._navegador:
            await self._navegador.close()
        if self._playwright:
            await self._playwright.stop()

    # ------------------------------------------------------------------
    # Operaciones de alto nivel
    # ------------------------------------------------------------------

    async def navegar(self, url: str) -> Page:
        """Abre una nueva pestaña apuntando a `url` y devuelve la página."""
        if not self._contexto:
            raise RuntimeError("Navegador no iniciado")
        pagina = await self._contexto.new_page()
        await pagina.goto(url, wait_until="domcontentloaded")
        return pagina

    async def extraer(self, url: str, *, incluir_html: bool = False) -> ResultadoExtraccion:
        """Visita `url` y devuelve título + texto plano (y opcionalmente HTML)."""
        pagina = await self.navegar(url)
        try:
            titulo = await pagina.title()
            texto = await pagina.inner_text("body")
            html = await pagina.content() if incluir_html else None
            return ResultadoExtraccion(
                url=pagina.url, titulo=titulo, texto=texto, html=html
            )
        finally:
            await pagina.close()

    async def rellenar_formulario(
        self, url: str, campos: dict[str, str], selector_envio: str | None = None
    ) -> Page:
        """Rellena cada `selector -> valor` y opcionalmente clica el botón."""
        pagina = await self.navegar(url)
        for selector, valor in campos.items():
            await pagina.fill(selector, valor)
        if selector_envio:
            await pagina.click(selector_envio)
        return pagina
