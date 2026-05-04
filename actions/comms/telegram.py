"""Integración con Telegram vía Bot API."""

from __future__ import annotations

from dataclasses import dataclass

from telegram import Bot
from telegram.constants import ParseMode


@dataclass(slots=True)
class MensajeTelegram:
    """Mensaje a enviar por Telegram."""

    chat_id: int | str
    texto: str
    parse_mode: ParseMode = ParseMode.MARKDOWN_V2


class Telegram:
    """Cliente fino sobre python-telegram-bot."""

    def __init__(self, token: str) -> None:
        self._bot = Bot(token=token)

    async def enviar(self, mensaje: MensajeTelegram) -> int:
        """Envía un mensaje y devuelve su `message_id`."""
        resultado = await self._bot.send_message(
            chat_id=mensaje.chat_id,
            text=mensaje.texto,
            parse_mode=mensaje.parse_mode,
        )
        return resultado.message_id

    async def enviar_archivo(self, chat_id: int | str, ruta: str, caption: str | None = None) -> int:
        """Envía un archivo como documento."""
        with open(ruta, "rb") as fichero:
            resultado = await self._bot.send_document(
                chat_id=chat_id, document=fichero, caption=caption
            )
        return resultado.message_id
