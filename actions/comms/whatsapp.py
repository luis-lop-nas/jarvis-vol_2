"""WhatsApp Web vía Playwright (no hay API oficial para uso personal)."""

from __future__ import annotations

from dataclasses import dataclass

from actions.browser import Navegador


@dataclass(slots=True)
class MensajeWhatsApp:
    """Mensaje a enviar por WhatsApp."""

    contacto: str
    texto: str


class WhatsApp:
    """Adaptador minimalista para enviar mensajes vía WhatsApp Web.

    Requiere haber escaneado previamente el QR con un perfil persistente.
    """

    URL_WEB = "https://web.whatsapp.com/"

    def __init__(self, navegador: Navegador) -> None:
        self._navegador = navegador

    async def enviar(self, mensaje: MensajeWhatsApp) -> None:
        """Localiza el chat y envía el mensaje."""
        pagina = await self._navegador.navegar(self.URL_WEB)
        await pagina.wait_for_selector('div[role="textbox"]', timeout=60_000)

        await pagina.click('div[role="textbox"]')
        await pagina.keyboard.type(mensaje.contacto)
        await pagina.keyboard.press("Enter")

        cuadro = pagina.locator('footer div[contenteditable="true"]').first
        await cuadro.click()
        await cuadro.type(mensaje.texto)
        await pagina.keyboard.press("Enter")
