"""Integración con Telegram vía python-telegram-bot (Bot API).

JARVIS actúa como bot, no como usuario.
Enviar mensajes y archivos siempre requieren confirmación.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

CallbackConfirmacion = Callable[[str], "asyncio.Future[bool]"]


async def _denegar(_: str) -> bool:
    return False


# ---------------------------------------------------------------------------
# Tipos públicos
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class InfoChat:
    """Información de un chat de Telegram.

    Ejemplo::
        info = await tg.obtener_info_chat(-1001234567890)
        print(info.titulo)
    """

    id: int | str
    titulo: str
    tipo: str  # "private", "group", "supergroup", "channel"
    descripcion: str


@dataclass(slots=True)
class ActualizacionTG:
    """Una actualización (mensaje entrante) de Telegram.

    Ejemplo::
        updates = await tg.obtener_actualizaciones()
        for u in updates:
            print(u.texto, u.chat_id)
    """

    update_id: int
    chat_id: int | str
    texto: str
    remitente: str
    fecha: datetime


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------


class Telegram:
    """Cliente de Bot API de Telegram.

    Ejemplo::
        tg = Telegram(token="123456:ABC...")
        await tg.enviar_mensaje(-1001234567890, "Hola desde JARVIS")
    """

    def __init__(
        self,
        token: str,
        *,
        callback_confirmacion: CallbackConfirmacion | None = None,
        audit_log: "AuditLog | None" = None,
    ) -> None:
        from telegram import Bot
        self._bot = Bot(token=token)
        self._confirmar = callback_confirmacion or _denegar
        self._audit = audit_log
        self._ultimo_update_id: int = 0

    # ------------------------------------------------------------------
    # Lectura
    # ------------------------------------------------------------------

    async def obtener_actualizaciones(self, limite: int = 20) -> list[ActualizacionTG]:
        """Devuelve las actualizaciones pendientes del bot.

        Ejemplo::
            updates = await tg.obtener_actualizaciones()
            for u in updates:
                print(u.texto)
        """
        updates = await self._bot.get_updates(
            offset=self._ultimo_update_id + 1,
            limit=limite,
            timeout=0,
        )
        resultado: list[ActualizacionTG] = []
        for u in updates:
            if u.update_id > self._ultimo_update_id:
                self._ultimo_update_id = u.update_id
            if u.message and u.message.text:
                resultado.append(ActualizacionTG(
                    update_id=u.update_id,
                    chat_id=u.message.chat_id,
                    texto=u.message.text,
                    remitente=u.message.from_user.username or str(u.message.from_user.id) if u.message.from_user else "",
                    fecha=u.message.date or datetime.now(),
                ))
        return resultado

    async def obtener_info_chat(self, chat_id: int | str) -> InfoChat:
        """Obtiene información de un chat.

        Ejemplo::
            info = await tg.obtener_info_chat(-1001234567890)
        """
        chat = await self._bot.get_chat(chat_id)
        return InfoChat(
            id=chat.id,
            titulo=chat.title or chat.username or str(chat.id),
            tipo=chat.type,
            descripcion=chat.description or "",
        )

    # ------------------------------------------------------------------
    # Envío — siempre requiere confirmación
    # ------------------------------------------------------------------

    async def enviar_mensaje(
        self,
        chat_id: int | str,
        texto: str,
        *,
        parse_mode: str = "MarkdownV2",
    ) -> bool:
        """Envía un mensaje de texto. SIEMPRE requiere confirmación.

        Ejemplo::
            ok = await tg.enviar_mensaje(-1001234567890, "Hola desde JARVIS")
        """
        aprobado = await self._confirmar(f"Enviar Telegram a {chat_id}: «{texto[:80]}»")
        if not aprobado:
            return False

        from telegram.constants import ParseMode
        modo = ParseMode.MARKDOWN_V2 if parse_mode == "MarkdownV2" else ParseMode.HTML
        msg = await self._bot.send_message(chat_id=chat_id, text=texto, parse_mode=modo)
        await self._audit_log("enviar_mensaje", {"chat_id": chat_id, "message_id": msg.message_id})
        return True

    async def enviar_archivo(
        self,
        chat_id: int | str,
        ruta: Path,
        *,
        caption: str | None = None,
    ) -> bool:
        """Envía un archivo como documento. SIEMPRE requiere confirmación.

        Ejemplo::
            ok = await tg.enviar_archivo(-1001234567890, Path("~/informe.pdf"))
        """
        ruta_resuelta = ruta.expanduser().resolve()
        aprobado = await self._confirmar(
            f"Enviar archivo {ruta_resuelta.name} a chat {chat_id} por Telegram"
        )
        if not aprobado:
            return False

        with ruta_resuelta.open("rb") as f:
            msg = await self._bot.send_document(chat_id=chat_id, document=f, caption=caption)
        await self._audit_log("enviar_archivo", {"chat_id": chat_id, "archivo": ruta_resuelta.name, "message_id": msg.message_id})
        return True

    async def _audit_log(self, evento: str, datos: dict) -> None:
        if self._audit is not None:
            await self._audit.registrar(f"telegram.{evento}", datos)


# Importación diferida
try:
    from security.audit_log import AuditLog  # noqa: F401
except ImportError:
    AuditLog = None  # type: ignore[assignment,misc]
