"""WhatsApp Web vía Playwright.

Soporta dos modos de uso:
- Inyección de página: para integraciones donde Playwright ya está corriendo.
- initialize_session(): lanza Chromium propio con sesión persistente en ~/.jarvis/whatsapp_session/.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

CallbackConfirmacion = Callable[[str], "asyncio.Future[bool]"]

_URL_WEB = "https://web.whatsapp.com"
_SELECTOR_BUSQUEDA = 'div[contenteditable="true"][data-tab="3"]'
_SELECTOR_INPUT_MENSAJE = 'div[contenteditable="true"][data-tab="10"]'
_SELECTOR_QR = 'canvas[aria-label="Scan me!"], div[data-testid="qrcode"]'
_SESSION_DIR_DEFAULT = Path.home() / ".jarvis" / "whatsapp_session"


async def _denegar(_: str) -> bool:
    return False


# ---------------------------------------------------------------------------
# Tipos públicos
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ChatWA:
    """Información de un chat de WhatsApp.

    Ejemplo::
        chats = await wa.obtener_chats_no_leidos()
        print(chats[0].nombre)
    """

    id: str
    nombre: str
    ultimo_mensaje: str
    no_leidos: int
    fecha: datetime


@dataclass(slots=True)
class MensajeWA:
    """Un mensaje de WhatsApp.

    Ejemplo::
        msgs = await wa.obtener_mensajes("Juan García", limite=10)
    """

    texto: str
    enviado: bool
    fecha: datetime
    contacto: str


# ---------------------------------------------------------------------------
# WhatsApp
# ---------------------------------------------------------------------------


class WhatsApp:
    """Adaptador de WhatsApp Web via Playwright.

    Uso recomendado: initialize_session() gestiona Playwright y la sesión automáticamente.
    Uso legacy: inyectar `pagina` ya abierta con sesión activa.

    Ejemplo::
        wa = await WhatsApp.initialize_session()
        ok = await wa.enviar_mensaje("Juan García", "Hola")
        await wa.cerrar_sesion()
    """

    def __init__(
        self,
        pagina: Any | None = None,
        *,
        callback_confirmacion: CallbackConfirmacion | None = None,
        audit_log: AuditLog | None = None,
    ) -> None:
        self._p = pagina
        self._confirmar = callback_confirmacion or _denegar
        self._audit = audit_log
        self._inicializado = False
        self._playwright_propio: Any = None
        self._context_propio: Any = None

    @classmethod
    async def initialize_session(
        cls,
        *,
        session_dir: Path | None = None,
        timeout_qr_s: int = 60,
        callback_confirmacion: CallbackConfirmacion | None = None,
        audit_log: AuditLog | None = None,
    ) -> WhatsApp:
        """Lanza Chromium no-headless con sesión persistente y espera el QR si es necesario.

        Si ya existe una sesión válida en session_dir, la reutiliza sin mostrar el QR.
        Si no hay sesión, espera hasta timeout_qr_s segundos a que el usuario escanee.

        Ejemplo::
            wa = await WhatsApp.initialize_session(timeout_qr_s=60)
            # Escanea el QR si es la primera vez
            print("Conectado:", wa._inicializado)
        """
        from playwright.async_api import async_playwright

        ruta_sesion = (session_dir or _SESSION_DIR_DEFAULT).expanduser().resolve()
        ruta_sesion.mkdir(parents=True, exist_ok=True)

        playwright = await async_playwright().start()
        context = await playwright.chromium.launch_persistent_context(
            str(ruta_sesion),
            headless=False,
            args=["--no-sandbox"],
        )
        pagina = context.pages[0] if context.pages else await context.new_page()

        wa = cls(pagina=pagina, callback_confirmacion=callback_confirmacion, audit_log=audit_log)
        wa._playwright_propio = playwright
        wa._context_propio = context

        await pagina.goto(_URL_WEB)

        # Verificar si ya hay sesión activa (barra de búsqueda visible en 5s)
        try:
            await pagina.wait_for_selector(_SELECTOR_BUSQUEDA, timeout=5_000)
            wa._inicializado = True
            return wa
        except Exception:
            pass

        # Sin sesión: esperar a que el usuario escanee el QR
        try:
            await pagina.wait_for_selector(_SELECTOR_BUSQUEDA, timeout=timeout_qr_s * 1_000)
            wa._inicializado = True
        except Exception:
            wa._inicializado = False

        return wa

    async def cerrar_sesion(self) -> None:
        """Cierra el contexto Playwright creado por initialize_session().

        Ejemplo::
            await wa.cerrar_sesion()
        """
        if self._context_propio is not None:
            await self._context_propio.close()
            self._context_propio = None
        if self._playwright_propio is not None:
            await self._playwright_propio.stop()
            self._playwright_propio = None

    async def inicializar(self, timeout_ms: int = 60_000) -> bool:
        """Navega a WhatsApp Web y espera a que cargue la sesión (modo inyección de página).

        Ejemplo::
            ok = await wa.inicializar()
        """
        try:
            await self._p.goto(_URL_WEB)
            await self._p.wait_for_selector(_SELECTOR_BUSQUEDA, timeout=timeout_ms)
            self._inicializado = True
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Lectura
    # ------------------------------------------------------------------

    async def obtener_chats_no_leidos(self) -> list[ChatWA]:
        """Lista los chats con mensajes no leídos.

        Ejemplo::
            chats = await wa.obtener_chats_no_leidos()
        """
        self._verificar_init()
        try:
            elementos = await self._p.query_selector_all('span[aria-label*="mensajes sin leer"], span[aria-label*="unread"]')
            chats: list[ChatWA] = []
            for el in elementos[:20]:
                titulo_el = await el.evaluate('e => e.closest("[data-testid=\'cell-frame-container\']")?.querySelector("[data-testid=\'cell-frame-title\']")?.innerText')
                chats.append(ChatWA(
                    id="",
                    nombre=titulo_el or "Desconocido",
                    ultimo_mensaje="",
                    no_leidos=1,
                    fecha=datetime.now(),
                ))
            return chats
        except Exception:
            return []

    async def obtener_mensajes(self, nombre_chat: str, limite: int = 20) -> list[MensajeWA]:
        """Obtiene los últimos mensajes de un chat.

        Ejemplo::
            msgs = await wa.obtener_mensajes("Juan García", limite=10)
        """
        self._verificar_init()
        try:
            await self._abrir_chat(nombre_chat)
            await asyncio.sleep(1)

            burbujas = await self._p.query_selector_all('div.message-in, div.message-out')
            mensajes: list[MensajeWA] = []
            for burbuja in burbujas[-limite:]:
                texto_el = await burbuja.query_selector('span.selectable-text')
                texto = await texto_el.inner_text() if texto_el else ""
                es_enviado = "message-out" in (await burbuja.get_attribute("class") or "")
                mensajes.append(MensajeWA(
                    texto=texto,
                    enviado=es_enviado,
                    fecha=datetime.now(),
                    contacto=nombre_chat,
                ))
            return mensajes
        except Exception:
            return []

    async def buscar_chat(self, consulta: str) -> list[ChatWA]:
        """Busca chats por nombre.

        Ejemplo::
            chats = await wa.buscar_chat("Juan")
        """
        self._verificar_init()
        try:
            campo = await self._p.wait_for_selector(_SELECTOR_BUSQUEDA, timeout=5000)
            await campo.click()
            await campo.type(consulta)
            await asyncio.sleep(1.5)

            resultados = await self._p.query_selector_all('[data-testid="cell-frame-title"]')
            chats: list[ChatWA] = []
            for r in resultados[:10]:
                nombre = await r.inner_text()
                chats.append(ChatWA(
                    id="",
                    nombre=nombre,
                    ultimo_mensaje="",
                    no_leidos=0,
                    fecha=datetime.now(),
                ))
            return chats
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Envío — siempre requiere confirmación
    # ------------------------------------------------------------------

    async def enviar_mensaje(self, nombre_chat: str, texto: str) -> bool:
        """Envía un mensaje. SIEMPRE requiere confirmación.

        Ejemplo::
            ok = await wa.enviar_mensaje("Juan García", "Hola, ¿todo bien?")
        """
        self._verificar_init()
        aprobado = await self._confirmar(f"Enviar WhatsApp a {nombre_chat}: «{texto[:80]}»")
        if not aprobado:
            return False

        try:
            await self._abrir_chat(nombre_chat)
            campo_msg = await self._p.wait_for_selector(_SELECTOR_INPUT_MENSAJE, timeout=10000)
            await campo_msg.click()
            await campo_msg.type(texto)
            await self._p.keyboard.press("Enter")
            await self._audit_log("enviar_mensaje", {"chat": nombre_chat, "longitud": len(texto)})
            return True
        except Exception:
            return False

    async def enviar_archivo(self, nombre_chat: str, ruta: Path) -> bool:
        """Envía un archivo. SIEMPRE requiere confirmación.

        Ejemplo::
            ok = await wa.enviar_archivo("Juan García", Path("~/foto.jpg"))
        """
        self._verificar_init()
        ruta_resuelta = ruta.expanduser().resolve()
        aprobado = await self._confirmar(f"Enviar archivo {ruta_resuelta.name} a {nombre_chat} por WhatsApp")
        if not aprobado:
            return False

        try:
            await self._abrir_chat(nombre_chat)
            # Clic en el botón de adjuntar
            boton_adjuntar = await self._p.wait_for_selector('[data-testid="attach-btn"]', timeout=5000)
            await boton_adjuntar.click()
            # Subir el archivo via input type=file
            input_file = await self._p.wait_for_selector('input[type="file"]', timeout=5000)
            await input_file.set_input_files(str(ruta_resuelta))
            # Confirmar envío
            boton_enviar = await self._p.wait_for_selector('[data-testid="send-btn"]', timeout=5000)
            await boton_enviar.click()
            await self._audit_log("enviar_archivo", {"chat": nombre_chat, "archivo": ruta_resuelta.name})
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _abrir_chat(self, nombre: str) -> None:
        """Busca y abre un chat por nombre."""
        campo = await self._p.wait_for_selector(_SELECTOR_BUSQUEDA, timeout=10000)
        await campo.click()
        # Limpiar campo y escribir nombre
        await campo.fill("")
        await campo.type(nombre)
        await asyncio.sleep(1.0)
        # Primer resultado
        primer_resultado = await self._p.wait_for_selector('[data-testid="cell-frame-container"]', timeout=5000)
        await primer_resultado.click()
        await asyncio.sleep(0.5)

    def _verificar_init(self) -> None:
        if not self._inicializado:
            raise RuntimeError("WhatsApp no inicializado. Llama a inicializar() primero.")

    async def _audit_log(self, evento: str, datos: dict) -> None:
        if self._audit is not None:
            await self._audit.registrar(f"whatsapp.{evento}", datos)


# Importación diferida
try:
    from security.audit_log import AuditLog  # noqa: F401
except ImportError:
    AuditLog = None  # type: ignore[assignment,misc]
