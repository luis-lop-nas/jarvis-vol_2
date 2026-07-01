"""Control del navegador: AppleScript para Safari básico, Playwright para interacción web.

Dos capas:
- `ControlSafari` — control básico de pestañas via AppleScript (sin abrir proceso externo)
- `Navegador` — interacción web completa via Playwright (Chromium headless o Safari)
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import TracebackType
from typing import Any, Self

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
        # Robustez: si Safari no está abierto o no tiene ventana frontal, el
        # `current tab of front window` falla. Activamos y creamos un documento
        # cuando no hay ninguna ventana antes de fijar la URL.
        script = (
            'tell application "Safari"\n'
            '  activate\n'
            '  if (count of windows) = 0 then make new document\n'
            f'  set URL of current tab of front window to "{_escapar(url)}"\n'
            'end tell'
        )
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
        audit_log: AuditLog | None = None,
    ) -> None:
        self._headless = headless
        self._confirmar = callback_confirmacion or _denegar
        self._audit = audit_log
        self._playwright = None
        self._browser = None
        self._context = None
        # Página persistente entre llamadas: `obtener_contenido_pagina` la deja
        # viva para que las herramientas interactivas (js/click/fill) operen
        # sobre la misma pestaña sin recibir el objeto página por parámetro.
        self._pagina_actual: Any = None

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

    async def asegurar_iniciado(self) -> None:
        """Arranca el navegador si aún no lo está (idempotente).

        Pensado para instancias de larga vida (servidor MCP) que no usan el
        gestor de contexto ``async with``: la primera herramienta de navegador
        arranca Playwright y las siguientes reutilizan el mismo contexto.

        Ejemplo::
            await nav.asegurar_iniciado()
        """
        if self._context is None:
            await self.iniciar()

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
        # Usa la página persistente (no la cierra) para que js/click/fill puedan
        # operar después sobre la misma pestaña.
        pagina = await self._pagina_persistente()
        await pagina.goto(url, wait_until="domcontentloaded", timeout=30000)
        titulo = await pagina.title()
        texto = await pagina.inner_text("body")
        html = await pagina.content() if incluir_html else None
        return ResultadoExtraccion(url=pagina.url, titulo=titulo, texto=texto, html=html)

    async def _pagina_persistente(self) -> Any:
        """Devuelve una página reutilizable, creándola si no existe o se cerró.

        A diferencia de ``_nueva_pagina`` (que exige iniciar y crea una pestaña
        de usar y tirar), esta arranca el navegador perezosamente y mantiene una
        única pestaña viva en ``_pagina_actual`` para las herramientas interactivas.

        Ejemplo::
            pagina = await nav._pagina_persistente()
        """
        await self.asegurar_iniciado()
        if self._pagina_actual is None or self._pagina_actual.is_closed():
            self._pagina_actual = await self._context.new_page()
        return self._pagina_actual

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
        pagina = pagina or self._pagina_actual
        if pagina is None:
            return False
        try:
            await pagina.click(selector, timeout=5000)
            return True
        except Exception:
            return False

    async def rellenar_campo(self, selector: str, valor: str, *, pagina: Any = None) -> bool:
        """Rellena un campo de formulario.

        Ejemplo::
            await nav.rellenar_campo("#email", "user@example.com", pagina=p)
        """
        pagina = pagina or self._pagina_actual
        if pagina is None:
            return False
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

    async def ejecutar_js(self, codigo: str, *, pagina: Any = None) -> Any:
        """Ejecuta JavaScript en el contexto de la página.

        SEGURIDAD: nunca pasar código no validado sin confirmación.

        Ejemplo::
            resultado = await nav.ejecutar_js("document.title", pagina=p)
        """
        aprobado = await self._confirmar(f"Ejecutar JS: {codigo[:100]}")
        if not aprobado:
            raise PermissionError("Ejecución de JavaScript no confirmada")
        pagina = pagina or self._pagina_actual
        if pagina is None:
            raise RuntimeError("No hay página activa; abre una URL antes de ejecutar JS.")
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

    async def captura_pagina(self, *, pagina: Any = None) -> bytes:
        """Toma una captura de pantalla de la página completa.

        Ejemplo::
            png = await nav.captura_pagina(pagina=p)
        """
        pagina = pagina or self._pagina_actual
        if pagina is None:
            raise RuntimeError("No hay página activa; abre una URL antes de capturar.")
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


# ---------------------------------------------------------------------------
# Tipos de la capa de agente
# ---------------------------------------------------------------------------


class PermisosBrowser(str, Enum):
    """Capacidades del navegador que requieren autorización explícita."""

    NAVEGACION_EXTERNA = "browser.navegacion_externa"
    DESCARGA = "browser.descarga"
    JS = "browser.javascript"


@dataclass(slots=True)
class ResultadoNavegacion:
    """Resultado de una operación de navegación del agente.

    Ejemplo::
        res = await sesion.open_url("https://example.com")
        assert res.ok and res.url_cambio
    """

    ok: bool
    url_actual: str
    url_cambio: bool
    mensaje: str = ""


@dataclass(slots=True)
class InfoEnlace:
    """Enlace extraído de una página.

    Ejemplo::
        enlaces = await sesion.extract_links()
        hrefs = [e.href for e in enlaces]
    """

    texto: str
    href: str


@dataclass(slots=True)
class CampoFormulario:
    """Campo de un formulario HTML."""

    nombre: str
    tipo: str
    valor: str | None
    etiqueta: str | None


@dataclass(slots=True)
class InfoFormulario:
    """Formulario extraído de una página.

    Ejemplo::
        forms = await sesion.extract_forms()
        print(forms[0].campos)
    """

    accion: str
    metodo: str
    campos: list[CampoFormulario]


# ---------------------------------------------------------------------------
# SesionNavegador — herramientas web de alto nivel
# ---------------------------------------------------------------------------


class SesionNavegador:
    """Sesión de navegación de alto nivel. No expone objetos internos de Playwright.

    El agente interactúa solo con esta clase — nunca con Page, BrowserContext, etc.

    Ejemplo::
        async with GestorSesiones() as gestor:
            sesion = await gestor.obtener_sesion("tarea-1")
            res = await sesion.open_url("https://python.org")
            print(await sesion.get_text())
    """

    def __init__(
        self,
        session_id: str,
        page: Any,
        context: Any,
        confirmar: CallbackConfirmacion,
        permisos: set[PermisosBrowser],
        audit_log: Any | None = None,
    ) -> None:
        self._session_id = session_id
        self._page = page
        self._context = context
        self._confirmar = confirmar
        self._permisos = permisos
        self._audit = audit_log

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def url_actual(self) -> str:
        return self._page.url

    async def open_url(self, url: str) -> ResultadoNavegacion:
        """Navega a una URL y espera a que cargue el DOM.

        Verifica: cambio de URL respecto a la anterior.

        Ejemplo::
            res = await sesion.open_url("https://example.com")
        """
        if not _es_local(url) and PermisosBrowser.NAVEGACION_EXTERNA not in self._permisos:
            aprobado = await self._confirmar(f"Navegar a URL externa: {url}")
            if not aprobado:
                return ResultadoNavegacion(
                    ok=False, url_actual=self._page.url,
                    url_cambio=False, mensaje="navegación externa no autorizada",
                )
            self._permisos.add(PermisosBrowser.NAVEGACION_EXTERNA)

        url_antes = self._page.url
        await self._audit_log("open_url", {"url": url})
        try:
            await self._page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            url_despues = self._page.url
            return ResultadoNavegacion(
                ok=True, url_actual=url_despues,
                url_cambio=url_despues != url_antes, mensaje="",
            )
        except Exception as e:
            return ResultadoNavegacion(
                ok=False, url_actual=self._page.url,
                url_cambio=False, mensaje=str(e),
            )

    async def get_text(self) -> str:
        """Devuelve el texto visible de la página actual.

        Ejemplo::
            texto = await sesion.get_text()
        """
        try:
            return await self._page.inner_text("body")
        except Exception:
            return ""

    async def click(self, selector_or_text: str) -> ResultadoNavegacion:
        """Hace click en un elemento por selector CSS o por texto visible.

        Verifica: elemento visible y sin error. Detecta cambio de URL.

        Ejemplo::
            await sesion.click("Iniciar sesión")   # texto visible
            await sesion.click("#submit-btn")       # selector CSS
        """
        url_antes = self._page.url
        try:
            if _es_selector(selector_or_text):
                await self._page.click(selector_or_text, timeout=5_000)
            else:
                await self._page.get_by_text(selector_or_text, exact=False).first.click(timeout=5_000)
            try:
                await self._page.wait_for_load_state("domcontentloaded", timeout=5_000)
            except Exception:
                pass
            url_despues = self._page.url
            return ResultadoNavegacion(
                ok=True, url_actual=url_despues,
                url_cambio=url_despues != url_antes, mensaje="",
            )
        except Exception as e:
            return ResultadoNavegacion(
                ok=False, url_actual=self._page.url,
                url_cambio=False, mensaje=str(e),
            )

    async def fill(self, selector_or_label: str, value: str) -> ResultadoNavegacion:
        """Rellena un campo de formulario por selector CSS, etiqueta o placeholder.

        Verifica: campo encontrado y rellenado sin error.

        Ejemplo::
            await sesion.fill("Nombre", "Luis")
            await sesion.fill("#email", "luis@example.com")
        """
        try:
            if _es_selector(selector_or_label):
                await self._page.fill(selector_or_label, value, timeout=5_000)
            else:
                locator = self._page.get_by_label(selector_or_label, exact=False)
                if await locator.count() > 0:
                    await locator.first.fill(value, timeout=5_000)
                else:
                    await self._page.get_by_placeholder(
                        selector_or_label, exact=False
                    ).first.fill(value, timeout=5_000)
            return ResultadoNavegacion(
                ok=True, url_actual=self._page.url,
                url_cambio=False, mensaje="",
            )
        except Exception as e:
            return ResultadoNavegacion(
                ok=False, url_actual=self._page.url,
                url_cambio=False, mensaje=str(e),
            )

    async def submit(self) -> ResultadoNavegacion:
        """Envía el formulario activo (button[type=submit] → input[type=submit] → button).

        Verifica: botón encontrado, envío ejecutado. Detecta cambio de URL.

        Ejemplo::
            await sesion.fill("nombre", "Luis")
            res = await sesion.submit()
            assert res.ok
        """
        url_antes = self._page.url
        enviado = False
        for selector in ("button[type=submit]", "input[type=submit]", "button:not([type])"):
            try:
                await self._page.click(selector, timeout=2_000)
                enviado = True
                break
            except Exception:
                continue
        if not enviado:
            return ResultadoNavegacion(
                ok=False, url_actual=self._page.url,
                url_cambio=False, mensaje="no se encontró botón de envío",
            )
        try:
            await self._page.wait_for_load_state("domcontentloaded", timeout=10_000)
        except Exception:
            pass
        url_despues = self._page.url
        return ResultadoNavegacion(
            ok=True, url_actual=url_despues,
            url_cambio=url_despues != url_antes, mensaje="formulario enviado",
        )

    async def wait_for(self, text_or_selector: str, *, timeout: int = 10_000) -> bool:
        """Espera hasta que aparezca un texto o selector en la página.

        Verifica: texto nuevo visible o elemento presente.

        Ejemplo::
            ok = await sesion.wait_for("Bienvenido", timeout=5000)
        """
        try:
            if _es_selector(text_or_selector):
                await self._page.wait_for_selector(text_or_selector, timeout=timeout)
            else:
                await self._page.wait_for_function(
                    f"document.body.innerText.includes({json.dumps(text_or_selector)})",
                    timeout=timeout,
                )
            return True
        except Exception:
            return False

    async def screenshot(self) -> bytes:
        """Captura la página completa como PNG.

        Ejemplo::
            png = await sesion.screenshot()
            Path("captura.png").write_bytes(png)
        """
        return await self._page.screenshot(full_page=True)

    async def download(self, url: str, destination: Path) -> Path | None:
        """Descarga un archivo a `destination`. Requiere permiso DESCARGA.

        Verifica: archivo presente en `destination` al completarse.

        Ejemplo::
            ruta = await sesion.download("https://example.com/doc.pdf", Path("/tmp/doc.pdf"))
        """
        if PermisosBrowser.DESCARGA not in self._permisos:
            aprobado = await self._confirmar(f"Descargar archivo desde: {url}")
            if not aprobado:
                return None
            self._permisos.add(PermisosBrowser.DESCARGA)

        await self._audit_log("download", {"url": url, "destino": str(destination)})
        try:
            async with self._page.expect_download(timeout=30_000) as dl_info:
                await self._page.goto(url)
            descarga = await dl_info.value
            destination.parent.mkdir(parents=True, exist_ok=True)
            await descarga.save_as(destination)
            return destination if destination.exists() else None
        except Exception:
            return None

    async def extract_links(self) -> list[InfoEnlace]:
        """Extrae todos los enlaces con href de la página actual.

        Ejemplo::
            enlaces = await sesion.extract_links()
        """
        try:
            datos: list[dict] = await self._page.evaluate(
                "Array.from(document.querySelectorAll('a[href]'))"
                ".map(a => ({texto: a.innerText.trim(), href: a.href}))"
            )
            return [InfoEnlace(texto=d["texto"], href=d["href"]) for d in datos]
        except Exception:
            return []

    async def extract_forms(self) -> list[InfoFormulario]:
        """Extrae formularios y sus campos de la página actual.

        Ejemplo::
            forms = await sesion.extract_forms()
            print(forms[0].campos)
        """
        try:
            datos: list[dict] = await self._page.evaluate("""
                Array.from(document.querySelectorAll('form')).map(f => ({
                    accion: f.action || '',
                    metodo: f.method || 'get',
                    campos: Array.from(f.querySelectorAll('input, textarea, select')).map(el => {
                        const lbl = el.id
                            ? document.querySelector('label[for="' + el.id + '"]')
                            : null;
                        return {
                            nombre: el.name || '',
                            tipo: el.type || el.tagName.toLowerCase(),
                            valor: el.value || null,
                            etiqueta: lbl ? lbl.innerText.trim() : null
                        };
                    })
                }))
            """)
            return [
                InfoFormulario(
                    accion=f["accion"],
                    metodo=f["metodo"],
                    campos=[CampoFormulario(**c) for c in f["campos"]],
                )
                for f in datos
            ]
        except Exception:
            return []

    async def _audit_log(self, evento: str, datos: dict) -> None:
        if self._audit is not None:
            await self._audit.registrar(f"browser.sesion.{evento}", datos)


# ---------------------------------------------------------------------------
# GestorSesiones — sesiones por session_id
# ---------------------------------------------------------------------------


class GestorSesiones:
    """Gestiona sesiones de navegación independientes identificadas por session_id.

    Cada sesión tiene su propio BrowserContext y Page — sin fugas de objetos Playwright.

    Ejemplo::
        async with GestorSesiones(headless=True) as gestor:
            sesion = await gestor.obtener_sesion("tarea-1")
            await sesion.open_url("https://python.org")
    """

    def __init__(
        self,
        *,
        headless: bool = True,
        confirmar: CallbackConfirmacion | None = None,
        permisos: set[PermisosBrowser] | None = None,
        audit_log: Any | None = None,
    ) -> None:
        self._headless = headless
        self._confirmar = confirmar or _denegar
        self._permisos: set[PermisosBrowser] = permisos or set()
        self._audit = audit_log
        self._playwright: Any = None
        self._browser: Any = None
        self._sesiones: dict[str, SesionNavegador] = {}

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
        """Arranca Playwright y el navegador compartido.

        Ejemplo::
            gestor = GestorSesiones()
            await gestor.iniciar()
        """
        from playwright.async_api import async_playwright
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=self._headless)

    async def cerrar(self) -> None:
        """Cierra todas las sesiones y libera recursos.

        Ejemplo::
            await gestor.cerrar()
        """
        for sid in list(self._sesiones):
            await self.cerrar_sesion(sid)
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def obtener_sesion(self, session_id: str) -> SesionNavegador:
        """Devuelve la sesión existente o crea una nueva con su propio contexto.

        Ejemplo::
            sesion = await gestor.obtener_sesion("main")
        """
        if session_id not in self._sesiones:
            context = await self._browser.new_context()
            page = await context.new_page()
            self._sesiones[session_id] = SesionNavegador(
                session_id=session_id,
                page=page,
                context=context,
                confirmar=self._confirmar,
                permisos=set(self._permisos),
                audit_log=self._audit,
            )
        return self._sesiones[session_id]

    async def cerrar_sesion(self, session_id: str) -> None:
        """Cierra y elimina una sesión específica.

        Ejemplo::
            await gestor.cerrar_sesion("main")
        """
        if session_id in self._sesiones:
            sesion = self._sesiones.pop(session_id)
            await sesion._context.close()

    def sesiones_activas(self) -> list[str]:
        """Lista los session_ids activos.

        Ejemplo::
            ids = gestor.sesiones_activas()
        """
        return list(self._sesiones)


# ---------------------------------------------------------------------------
# Helpers de la capa de agente
# ---------------------------------------------------------------------------

_SELECTOR_PREFIJOS = ("#", ".", "[", "//", "xpath=", "css=")
_SELECTOR_TAG_ATTR = ("button[", "input[", "select[", "textarea[", "a[", "form[")


def _es_selector(s: str) -> bool:
    """Heurística: ¿es esto un selector CSS/XPath en lugar de texto visible?"""
    if any(s.startswith(p) for p in _SELECTOR_PREFIJOS + _SELECTOR_TAG_ATTR):
        return True
    return "::" in s or ">>" in s


def _es_local(url: str) -> bool:
    """¿La URL apunta a recursos locales (file://, localhost, 127.0.0.1)?"""
    return url.startswith("file://") or "localhost" in url or "127.0.0.1" in url


# Importación diferida
try:
    from security.audit_log import AuditLog  # noqa: F401
except ImportError:
    AuditLog = None  # type: ignore[assignment,misc]
