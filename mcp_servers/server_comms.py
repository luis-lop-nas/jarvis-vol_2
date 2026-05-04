"""Servidor MCP que expone los canales de comunicación."""

from __future__ import annotations

from typing import Any

from actions.comms.imessage import IMessage, MensajeIMessage
from actions.comms.mail import Correo, Mail
from actions.comms.telegram import MensajeTelegram, Telegram


class ServidorComms:
    """Bridge MCP <-> mail, iMessage, Telegram."""

    nombre = "comms"

    def __init__(
        self,
        mail: Mail | None = None,
        imessage: IMessage | None = None,
        telegram: Telegram | None = None,
    ) -> None:
        self._mail = mail or Mail()
        self._imessage = imessage or IMessage()
        self._telegram = telegram

    def herramientas(self) -> list[dict[str, Any]]:
        herramientas: list[dict[str, Any]] = [
            {
                "name": "enviar_correo",
                "description": "Envía o guarda como borrador un correo electrónico.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "asunto": {"type": "string"},
                        "destinatarios": {"type": "array", "items": {"type": "string"}},
                        "cuerpo": {"type": "string"},
                        "enviar": {"type": "boolean", "default": False},
                    },
                    "required": ["asunto", "destinatarios", "cuerpo"],
                },
            },
            {
                "name": "enviar_imessage",
                "description": "Envía un iMessage a un contacto.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "destinatario": {"type": "string"},
                        "texto": {"type": "string"},
                    },
                    "required": ["destinatario", "texto"],
                },
            },
        ]
        if self._telegram is not None:
            herramientas.append(
                {
                    "name": "enviar_telegram",
                    "description": "Envía un mensaje vía Telegram bot.",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "chat_id": {"type": ["integer", "string"]},
                            "texto": {"type": "string"},
                        },
                        "required": ["chat_id", "texto"],
                    },
                }
            )
        return herramientas

    async def ejecutar(self, herramienta: str, argumentos: dict[str, Any]) -> Any:
        match herramienta:
            case "enviar_correo":
                correo = Correo(
                    asunto=argumentos["asunto"],
                    remitente="",
                    destinatarios=argumentos["destinatarios"],
                    cuerpo=argumentos["cuerpo"],
                )
                await self._mail.enviar(correo, enviar_inmediatamente=argumentos.get("enviar", False))
                return {"ok": True}
            case "enviar_imessage":
                await self._imessage.enviar(
                    MensajeIMessage(
                        destinatario=argumentos["destinatario"],
                        texto=argumentos["texto"],
                    )
                )
                return {"ok": True}
            case "enviar_telegram":
                if self._telegram is None:
                    raise RuntimeError("Telegram no configurado")
                msg_id = await self._telegram.enviar(
                    MensajeTelegram(
                        chat_id=argumentos["chat_id"], texto=argumentos["texto"]
                    )
                )
                return {"message_id": msg_id}
            case _:
                raise ValueError(f"Herramienta desconocida: {herramienta}")
