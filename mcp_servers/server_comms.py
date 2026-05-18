"""Servidor MCP para canales de comunicación."""

from __future__ import annotations

from typing import Any

from actions.comms.imessage import IMessage
from actions.comms.mail import Mail
from actions.comms.telegram import Telegram
from actions.comms.whatsapp import WhatsApp
from mcp_servers.base import MCPTool, campo, schema_objeto, serializar_dato


class ServidorComms:
    """Adaptador MCP sobre Mail, iMessage, Telegram y WhatsApp."""

    nombre = "comms"

    def __init__(
        self,
        mail: Mail | None = None,
        imessage: IMessage | None = None,
        telegram: Telegram | None = None,
        whatsapp: WhatsApp | None = None,
    ) -> None:
        self._mail = mail or Mail()
        self._imessage = imessage or IMessage()
        self._telegram = telegram
        self._whatsapp = whatsapp

    def herramientas(self) -> list[MCPTool]:
        """Declara herramientas de comunicación compatibles con el planner."""
        herramientas = [
            MCPTool(
                name="mail.leer",
                description="Lee correos no leídos o un mensaje concreto.",
                input_schema=schema_objeto({
                    "message_id": campo("string", "Identificador de correo específico."),
                    "limite": campo("integer", "Máximo de correos no leídos.", minimum=1),
                    "maximo": campo("integer", "Alias del prompt para límite.", minimum=1),
                }),
            ),
            MCPTool(
                name="mail.enviar",
                description="Envía un correo tras confirmación.",
                input_schema=schema_objeto({
                    "destinatario": campo("string", "Destinatario único."),
                    "destinatarios": campo("array", "Lista de destinatarios.", items={"type": "string"}),
                    "asunto": campo("string", "Asunto del correo."),
                    "cuerpo": campo("string", "Cuerpo del correo."),
                    "cc": campo("array", "Destinatarios en copia.", items={"type": "string"}),
                    "adjuntos": campo("array", "Rutas de adjuntos.", items={"type": "string"}),
                }, ["asunto", "cuerpo"]),
                requires_confirmation=True,
                side_effects=["mail.send"],
            ),
            MCPTool(
                name="mail.eliminar",
                description="Elimina un correo tras confirmación.",
                input_schema=schema_objeto({
                    "message_id": campo("string", "Identificador del mensaje a eliminar."),
                }, ["message_id"]),
                requires_confirmation=True,
                side_effects=["mail.delete"],
            ),
            MCPTool(
                name="imessage.leer",
                description="Lee conversaciones o mensajes.",
                input_schema=schema_objeto({
                    "contacto": campo("string", "Contacto del que leer mensajes."),
                    "limite": campo("integer", "Máximo de mensajes.", minimum=1),
                }),
            ),
            MCPTool(
                name="imessage.enviar",
                description="Envía iMessage tras confirmación.",
                input_schema=schema_objeto({
                    "contacto": campo("string", "Contacto destino."),
                    "mensaje": campo("string", "Texto a enviar."),
                    "texto": campo("string", "Alias para texto a enviar."),
                }, ["contacto"]),
                requires_confirmation=True,
                side_effects=["imessage.send"],
            ),
            MCPTool(
                name="telegram.leer",
                description="Lee actualizaciones de Telegram.",
                input_schema=schema_objeto({
                    "limite": campo("integer", "Máximo de actualizaciones.", minimum=1),
                }),
            ),
            MCPTool(
                name="telegram.enviar",
                description="Envía Telegram tras confirmación.",
                input_schema=schema_objeto({
                    "chat_id": campo("string", "Identificador del chat destino."),
                    "mensaje": campo("string", "Texto a enviar."),
                    "texto": campo("string", "Alias para texto a enviar."),
                    "parse_mode": campo("string", "Modo de parseo de Telegram."),
                }, ["chat_id"]),
                requires_confirmation=True,
                side_effects=["telegram.send"],
            ),
            MCPTool(
                name="whatsapp.leer",
                description="Lee chats o mensajes de WhatsApp Web configurado.",
                input_schema=schema_objeto({
                    "contacto": campo("string", "Contacto o chat a leer."),
                    "nombre_chat": campo("string", "Alias de chat a leer."),
                    "limite": campo("integer", "Máximo de mensajes.", minimum=1),
                }),
            ),
            MCPTool(
                name="whatsapp.enviar",
                description="Envía WhatsApp Web tras confirmación.",
                input_schema=schema_objeto({
                    "contacto": campo("string", "Contacto destino."),
                    "nombre_chat": campo("string", "Alias de contacto destino."),
                    "mensaje": campo("string", "Texto a enviar."),
                    "texto": campo("string", "Alias para texto a enviar."),
                }),
                requires_confirmation=True,
                side_effects=["whatsapp.send"],
            ),
        ]
        return herramientas

    async def ejecutar(self, tool_name: str, params: dict[str, Any]) -> Any:
        """Ejecuta una herramienta de comunicación.

        Args:
            tool_name: Nombre canónico de herramienta.
            params: Parámetros de llamada.

        Returns:
            Resultado serializable de la acción.
        """
        match tool_name:
            case "mail.leer":
                if "message_id" in params:
                    return serializar_dato(await self._mail.obtener_mensaje(str(params["message_id"])))
                return serializar_dato(
                    await self._mail.obtener_no_leidos(
                        int(params.get("limite", params.get("maximo", 20)))
                    )
                )
            case "mail.enviar":
                destinatarios = params.get("destinatarios")
                if destinatarios is None:
                    destinatarios = [params["destinatario"]]
                return await self._mail.enviar_mensaje(
                    list(destinatarios),
                    str(params["asunto"]),
                    str(params["cuerpo"]),
                    cc=list(params.get("cc", [])) or None,
                    adjuntos=list(params.get("adjuntos", [])) or None,
                )
            case "mail.eliminar":
                return await self._mail.eliminar_mensaje(str(params["message_id"]))
            case "imessage.leer":
                if "contacto" in params:
                    return serializar_dato(
                        await self._imessage.obtener_mensajes(
                            str(params["contacto"]),
                            limite=int(params.get("limite", 20)),
                        )
                    )
                return serializar_dato(await self._imessage.obtener_conversaciones())
            case "imessage.enviar":
                return await self._imessage.enviar_mensaje(
                    str(params["contacto"]),
                    str(params.get("texto") or params["mensaje"]),
                )
            case "telegram.leer":
                if self._telegram is None:
                    raise RuntimeError("Telegram no configurado")
                return serializar_dato(await self._telegram.obtener_actualizaciones(int(params.get("limite", 20))))
            case "telegram.enviar":
                if self._telegram is None:
                    raise RuntimeError("Telegram no configurado")
                return await self._telegram.enviar_mensaje(
                    params["chat_id"],
                    str(params.get("texto") or params["mensaje"]),
                    parse_mode=str(params.get("parse_mode", "MarkdownV2")),
                )
            case "whatsapp.leer":
                if self._whatsapp is None:
                    raise RuntimeError("WhatsApp no configurado")
                contacto = params.get("contacto") or params.get("nombre_chat")
                if contacto is not None:
                    return serializar_dato(
                        await self._whatsapp.obtener_mensajes(
                            str(contacto),
                            limite=int(params.get("limite", 20)),
                        )
                    )
                return serializar_dato(await self._whatsapp.obtener_chats_no_leidos())
            case "whatsapp.enviar":
                if self._whatsapp is None:
                    raise RuntimeError("WhatsApp no configurado")
                contacto = params.get("contacto") or params["nombre_chat"]
                texto = params.get("texto") or params["mensaje"]
                return await self._whatsapp.enviar_mensaje(str(contacto), str(texto))
            case _:
                raise ValueError(f"Herramienta comms desconocida: {tool_name}")
