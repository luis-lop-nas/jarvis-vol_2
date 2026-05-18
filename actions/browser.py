"""Control del navegador: AppleScript para Safari básico, Playwright para interacción web.

Dos capas:
- `ControlSafari` — control básico de pestañas via AppleScript (sin abrir proceso externo)
- `Navegador` — interacción web completa via Playwright (Chromium headless o Safari)
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import Any, AsyncGenerator, Callable, Self

from actions.system import ControlSistema

CallbackConfirmacion = Callable[[str], "asyncio.Future[bool]"]


async def _denegar(_: str) -> bool:
    return False


# ---------------------------------------------------------------------------
# Tipos públicos
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class InfoPestana:
    """Información de una pestaña del navegador.

    Ejemplo::
        pestanas = await safari.obtener_pestanas()
        print(pestanas[0].titulo)
    """

    indice: int
    url: str
    titulo: str
    activa: bool
    cargando: bool


@dataclass(slots=True)
class ResultadoExtraccion:
    """Datos extraídos de una página web.

    Ejemplo::
        res = await nav.obtener_contenido("https://example.com")
        print(res.texto[:200])
    """

    url: str
    titulo: str
    texto: str
    html: str | None = None


# ---------------------------------------------------------------------------
# ControlSafari — capa AppleScript
# ---------------------------------------------------------------------------


class ControlSafari:
    """Control básico de Safari.app vía AppleScript.

    Ejemplo::
        safari = ControlSafari()
        await safari.abrir_url("https://example.com")
    """

    def __init__(self, sistema: ControlSistema | None = None) -> None:
        self._s = sistema or ControlSistema()

    async def obtener_url_actual(self) -> str | None:
        """Devuelve la URL de la pestaña activa de Safari.

        Ejemplo::
            url = await safari.obtener_url_actual()
        """
        return await self._s.ejecutar_applescript(
            'tell application "Safari" to return URL of current tab of front window'
        )

    async def obtener_titulo(self) -> str | None:
        """Devuelve el título de la pestaña activa.

        Ejemplo::
            titulo = await safari.obtener_titulo()
        """
        return await self._s.ejecutar_applescript(
            'tell application "Safari" to return name of current tab of front window'
        )

    async def abrir_url(self, url: str) -> bool:
        """Abre una URL en la pestaña activa de Safari.

        Ejemplo::
            await safari.abrir_url("https://github.com")
        """
        script = f'tell application "Safari" to set URL of current tab of front window to "{_escapar(url)}"'
        return await self._s.ejecutar_applescript(script) is not None

    async def nueva_pestana(self, url: str = "") -> bool:
        """Abre una nueva pestaña (opcionalmente con URL).

        Ejemplo::
            await safari.nueva_pestana("https://example.com")
        """
        url_part = f' with properties {{URL: "{_escapar(url)}"}}' if url else ""
        script = (
            f'tell application "Safari"\n'
            f'  tell front window\n'
            f'    set current tab to (make new tab{url_part})\n'
            f'  end tell\n'
            f'end tell'
        )
        return await self._s.ejecutar_applescript(script) is not None

    async def cerrar_pestana(self) -> bool:
        """Cierra la pestaña activa.

        Ejemplo::
            await safari.cerrar_pestana()
        """
        script = 'tell application "Safari" to close current tab of front window'
        return await self._s.ejecutar_applescript(script) is not None

    async def ir_atras(self) -> bool:
        """Navega hacia atrás.

        Ejemplo::
            await safari.ir_atras()
        """
        return await self._s.ejecutar_applescript(
            'tell application "Safari" to do JavaScript "history.back()" in current tab of front window'
        ) is not None

    async def ir_adelante(self) -> bool:
        """Navega hacia adelante.

        Ejemplo::
            await safari.ir_adelante()
        """
        return await self._s.ejecutar_applescript(
            'tell application "Safari" to do JavaScript "history.forward()" in current tab of front window'
        ) is not None

    async def recargar(self) -> bool:
        """Recarga la pestaña activa.

        Ejemplo::
            await safari.recargar()
        """
        return await self._s.ejecutar_applescript(
            'tell application "Safari" to do JavaScript "location.reload()" in current tab of front window'
        ) is not None

    async def obtener_pestanas(self) -> list[InfoPestana]:
        """Lista todas las pestañas de la ventana activa.

        Ejemplo::
            pestanas = await safari.obtener_pestanas()
        """
        script = (
            'tell application "Safari"\n'
            '  tell front window\n'
            '    set resultado to {}\n'
            '    set n to count of tabs\n'
            '    repeat with i from 1 to n\n'
            '      set t to tab i\n'
            '      set isActive to (current tab is t)\n'
            '      set end of resultado to (URL of t) & "|||" & (name of t) & "|||" & (isActive as string)\n'
            '    end repeat\n'
            '    return resultado\n'
            '  end tell\n'
            'end tell'
        )
        salida = await self._s.ejecutar_applescript(script)
        pestanas: list[InfoPestana] = []
        if not salida:
            return pestanas
        for i, entrada in enumerate(salida.split(", ")):
            partes = entrada.split("|||")
            if len(partes) >= 3:
                pestanas.append(InfoPestana(
                    indice=i,
                    url=partes[0].strip(),
                    titulo=partes[1].strip(),
                    activa=partes[2].strip() == "true",
                    cargando=False,
                ))
        return pestanas

    async def enfocar_pestana(self, indice: int) -> bool:
        """Activa la pestaña con el índice dado (base 1 en AppleScript).

        Ejemplo::
            await safari.enfocar_pestana(2)
        """
        script = (
            f'tell application "Safari"\n'
            f'  tell front window\n'
            f'    set current tab to tab {indice + 1}\n'
            f'  end tell\n'
            f'end tell'
        )
        return await self._s.ejecutar_applescript(script) is not None


# ---------------------------------------------------------------------------
# Navegador — capa Playwright
# ---------------------------------------------------------------------------


class Navegador:
    """Interacción web completa via Playwright (Chromium headless).

    Ejemplo::
        async with Navegador() as nav:
            texto = await nav.obtener_texto_pagina("https://example.com")
    """

    def __init__(
        self,
        *,
        headless: bool = True,
        callback_confirmacion: CallbackConfirmacion | None = None,
        audit_log: "AuditLog | None" = None,
    ) -> None:
        self._headless = headless
        self._confirmar = callback_confirmacion or _denegar
        self._audit = audit_log
        self._playwright = None
        self._browser = None
        self._context = None

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
        """Arranca Playwright y el contexto del navegador.

        Ejemplo::
            await nav.iniciar()
        """
        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self._headless)
        self._context = await self._browser.new_context()

    async def cerrar(self) -> None:
        """Cierra el navegador y libera recursos.

        Ejemplo::
            await nav.cerrar()
        """
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def obtener_contenido_pagina(self, url: str, *, incluir_html: bool = False) -> ResultadoExtraccion:
        """Visita una URL y extrae texto plano (y opcionalmente HTML).

        Ejemplo::
            res = await nav.obtener_contenido_pagina("https://python.org")
            print(res.texto[:200])
        """
        await self._audit_log("navegar", {"url": url})
        pagina = await self._nueva_pagina()
        try:
            await pagina.goto(url, wait_until="domcontentloaded", timeout=30000)
            titulo = await pagina.title()
            texto = await pagina.inner_text("body")
            html = await pagina.content() if incluir_html else None
            return ResultadoExtraccion(url=pagina.url, titulo=titulo, texto=texto, html=html)
        finally:
            await pagina.close()

    async def obtener_texto_pagina(self, url: str) -> str:
        """Devuelve solo el texto visible de una página.

        Ejemplo::
            texto = await nav.obtener_texto_pagina("https://example.com")
        """
        res = await self.obtener_contenido_pagina(url)
        return res.texto

    async def click_elemento(self, selector: str, *, pagina: Any = None) -> bool:
        """Hace click en un elemento por selector CSS.

        Ejemplo::
            await nav.click_elemento("#submit-btn")
        """
        if pagina is None:
            return False
        try:
            await pagina.click(selector, timeout=5000)
            return True
        except Exception:
            return False

    async def rellenar_campo(self, selector: str, valor: str, *, pagina: Any) -> bool:
        """Rellena un campo de formulario.

        Ejemplo::
            await nav.rellenar_campo("#email", "user@example.com", pagina=p)
        """
        try:
            await pagina.fill(selector, valor)
            return True
        except Exception:
            return False

    async def enviar_formulario(self, selector: str, *, pagina: Any) -> bool:
        """Envía un formulario haciendo click en su botón.

        Ejemplo::
            await nav.enviar_formulario("button[type=submit]", pagina=p)
        """
        return await self.click_elemento(selector, pagina=pagina)

    async def scroll_hasta(self, selector: str, *, pagina: Any) -> bool:
        """Hace scroll hasta que un elemento sea visible.

        Ejemplo::
            await nav.scroll_hasta("#footer", pagina=p)
        """
        try:
            await pagina.locator(selector).scroll_into_view_if_needed(timeout=5000)
            return True
        except Exception:
            return False

    async def esperar_elemento(self, selector: str, *, pagina: Any, timeout: int = 10000) -> bool:
        """Espera hasta que un elemento sea visible.

        Ejemplo::
            await nav.esperar_elemento(".resultado", pagina=p, timeout=5000)
        """
        try:
            await pagina.wait_for_selector(selector, timeout=timeout)
            return True
        except Exception:
            return False

    async def ejecutar_js(self, codigo: str, *, pagina: Any) -> Any:
        """Ejecuta JavaScript en el contexto de la página.

        SEGURIDAD: nunca pasar código no validado sin confirmación.

        Ejemplo::
            resultado = await nav.ejecutar_js("document.title", pagina=p)
        """
        aprobado = await self._confirmar(f"Ejecutar JS: {codigo[:100]}")
        if not aprobado:
            raise PermissionError("Ejecución de JavaScript no confirmada")
        return await pagina.evaluate(codigo)

    async def descargar_archivo(self, url: str, destino: Path) -> Path | None:
        """Descarga un archivo de una URL.

        Ejemplo::
            ruta = await nav.descargar_archivo("https://example.com/doc.pdf", Path("~/Downloads/doc.pdf"))
        """
        await self._audit_log("descargar", {"url": url, "destino": str(destino)})
        pagina = await self._nueva_pagina()
        try:
            async with pagina.expect_download() as dl_info:
                await pagina.goto(url)
            descarga = await dl_info.value
            destino.parent.mkdir(parents=True, exist_ok=True)
            await descarga.save_as(destino)
            return destino
        except Exception:
            return None
        finally:
            await pagina.close()

    async def obtener_texto_seleccionado(self, *, pagina: Any) -> str | None:
        """Devuelve el texto seleccionado en la página.

        Ejemplo::
            texto = await nav.obtener_texto_seleccionado(pagina=p)
        """
        try:
            return await pagina.evaluate("window.getSelection().toString()")
        except Exception:
            return None

    async def captura_pagina(self, *, pagina: Any) -> bytes:
        """Toma una captura de pantalla de la página completa.

        Ejemplo::
            png = await nav.captura_pagina(pagina=p)
        """
        return await pagina.screenshot(full_page=True)

    async def _nueva_pagina(self) -> Any:
        if not self._context:
            raise RuntimeError("Navegador no iniciado. Usa 'async with Navegador():'")
        return await self._context.new_page()

    async def _audit_log(self, evento: str, datos: dict) -> None:
        if self._audit is not None:
            await self._audit.registrar(f"browser.{evento}", datos)


def _escapar(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace('"', '\\"')


# Importación diferida
try:
    from security.audit_log import AuditLog  # noqa: F401
except ImportError:
    AuditLog = None  # type: ignore[assignment,misc]
