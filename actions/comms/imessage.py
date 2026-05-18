"""Integración con iMessage vía AppleScript / Messages.app.

Enviar mensajes y leer conversaciones siempre requieren confirmación.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from actions.system import ControlSistema

CallbackConfirmacion = Callable[[str], "asyncio.Future[bool]"]


async def _denegar(_: str) -> bool:
    return False


# ---------------------------------------------------------------------------
# Tipos públicos
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Conversacion:
    """Metadatos de una conversación de iMessage.

    Ejemplo::
        convs = await im.obtener_conversaciones()
        print(convs[0].participantes)
    """

    id: str
    participantes: list[str]
    ultimo_mensaje: str
    fecha: datetime


@dataclass(slots=True)
class MensajeIM:
    """Un mensaje de iMessage.

    Ejemplo::
        msgs = await im.obtener_mensajes("+34612345678", limite=10)
    """

    id: str
    texto: str
    enviado: bool  # True = enviado por JARVIS, False = recibido
    fecha: datetime
    contacto: str


# ---------------------------------------------------------------------------
# IMessage
# ---------------------------------------------------------------------------


class IMessage:
    """Adaptador para Messages.app via AppleScript.

    Regla estricta: enviar SIEMPRE requiere confirmación explícita.
    Leer conversaciones de contactos desconocidos también.

    Ejemplo::
        im = IMessage()
        ok = await im.enviar_mensaje("+34612345678", "Hola")
    """

    def __init__(
        self,
        sistema: ControlSistema | None = None,
        *,
        callback_confirmacion: CallbackConfirmacion | None = None,
        audit_log: "AuditLog | None" = None,
        contactos_conocidos: set[str] | None = None,
    ) -> None:
        self._s = sistema or ControlSistema()
        self._confirmar = callback_confirmacion or _denegar
        self._audit = audit_log
        self._conocidos = contactos_conocidos or set()

    # ------------------------------------------------------------------
    # Lectura
    # ------------------------------------------------------------------

    async def obtener_conversaciones(self) -> list[Conversacion]:
        """Lista todas las conversaciones activas.

        Ejemplo::
            convs = await im.obtener_conversaciones()
        """
        script = """
        tell application "Messages"
            set resultado to {}
            repeat with c in chats
                set participantes to {}
                repeat with p in participants of c
                    set end of participantes to handle of p
                end repeat
                set end of resultado to (id of c as string) & "|||" & (participantes as string)
            end repeat
            return resultado
        end tell
        """
        salida = await self._s.ejecutar_applescript(script)
        conversaciones: list[Conversacion] = []
        if not salida:
            return conversaciones

        for entrada in salida.split(", "):
            partes = entrada.split("|||", 1)
            if len(partes) >= 2:
                conversaciones.append(Conversacion(
                    id=partes[0].strip(),
                    participantes=[p.strip() for p in partes[1].split(",") if p.strip()],
                    ultimo_mensaje="",
                    fecha=datetime.now(),
                ))
        return conversaciones

    async def obtener_mensajes(self, contacto: str, limite: int = 20) -> list[MensajeIM]:
        """Obtiene los últimos mensajes de un contacto.

        Solo contactos conocidos sin confirmación; desconocidos requieren aprobación.

        Ejemplo::
            msgs = await im.obtener_mensajes("+34612345678", limite=10)
        """
        if contacto not in self._conocidos:
            aprobado = await self._confirmar(f"Leer mensajes de contacto no conocido: {contacto}")
            if not aprobado:
                return []

        script = f"""
        tell application "Messages"
            set resultado to {{}}
            set conversacion to chat "{_escapar(contacto)}"
            set msgs to last {limite} messages of conversacion
            repeat with m in msgs
                set end of resultado to (id of m as string) & "|||" & \\
                    (text of m) & "|||" & \\
                    (outgoing of m as string)
            end repeat
            return resultado
        end tell
        """
        salida = await self._s.ejecutar_applescript(script)
        mensajes: list[MensajeIM] = []
        if not salida:
            return mensajes

        for entrada in salida.split(", "):
            partes = entrada.split("|||", 2)
            if len(partes) >= 3:
                mensajes.append(MensajeIM(
                    id=partes[0].strip(),
                    texto=partes[1].strip(),
                    enviado=partes[2].strip() == "true",
                    fecha=datetime.now(),
                    contacto=contacto,
                ))
        return mensajes

    # ------------------------------------------------------------------
    # Envío — siempre requiere confirmación
    # ------------------------------------------------------------------

    async def enviar_mensaje(self, contacto: str, texto: str) -> bool:
        """Envía un iMessage. SIEMPRE requiere confirmación.

        Ejemplo::
            ok = await im.enviar_mensaje("+34612345678", "Hola, ¿cómo estás?")
        """
        aprobado = await self._confirmar(f"Enviar iMessage a {contacto}: «{texto[:80]}»")
        if not aprobado:
            return False

        script = f"""
        tell application "Messages"
            set servicio to 1st service whose service type = iMessage
            set buddy to buddy "{_escapar(contacto)}" of servicio
            send "{_escapar(texto)}" to buddy
        end tell
        """
        resultado = await self._s.ejecutar_applescript(script)
        await self._audit_log("enviar_mensaje", {"contacto": contacto, "longitud": len(texto)})
        return resultado is not None

    async def enviar_archivo(self, contacto: str, ruta: Path) -> bool:
        """Envía un archivo por iMessage. SIEMPRE requiere confirmación.

        Ejemplo::
            ok = await im.enviar_archivo("+34612345678", Path("~/foto.jpg"))
        """
        ruta_resuelta = ruta.expanduser().resolve()
        aprobado = await self._confirmar(f"Enviar archivo {ruta_resuelta.name} a {contacto} por iMessage")
        if not aprobado:
            return False

        script = f"""
        tell application "Messages"
            set servicio to 1st service whose service type = iMessage
            set buddy to buddy "{_escapar(contacto)}" of servicio
            send (POSIX file "{_escapar(str(ruta_resuelta))}") to buddy
        end tell
        """
        resultado = await self._s.ejecutar_applescript(script)
        await self._audit_log("enviar_archivo", {"contacto": contacto, "archivo": str(ruta_resuelta)})
        return resultado is not None

    async def _audit_log(self, evento: str, datos: dict) -> None:
        if self._audit is not None:
            await self._audit.registrar(f"imessage.{evento}", datos)


def _escapar(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


# Importación diferida
try:
    from security.audit_log import AuditLog  # noqa: F401
except ImportError:
    AuditLog = None  # type: ignore[assignment,misc]
