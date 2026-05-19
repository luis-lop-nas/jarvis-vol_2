"""Integración con Apple Mail vía AppleScript.

Lectura de mensajes y envío con confirmación obligatoria.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from actions.filesystem import DryRunResult
from actions.system import ControlSistema

CallbackConfirmacion = Callable[[str], "asyncio.Future[bool]"]


async def _denegar(_: str) -> bool:
    return False


# ---------------------------------------------------------------------------
# Tipos públicos
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class MensajeCorreo:
    """Representación de un correo electrónico.

    Ejemplo::
        msg = await mail.obtener_mensaje("12345")
        print(msg.asunto)
    """

    id: str
    remitente: str
    destinatarios: list[str]
    asunto: str
    cuerpo: str
    fecha: datetime
    leido: bool
    tiene_adjuntos: bool
    carpeta: str = "INBOX"


# ---------------------------------------------------------------------------
# Mail
# ---------------------------------------------------------------------------


class Mail:
    """Lectura y envío de correos a través de Mail.app vía AppleScript.

    Ejemplo::
        mail = Mail()
        count = await mail.contar_no_leidos()
    """

    def __init__(
        self,
        sistema: ControlSistema | None = None,
        *,
        callback_confirmacion: CallbackConfirmacion | None = None,
        audit_log: AuditLog | None = None,
        auth_manager: AuthManager | None = None,
    ) -> None:
        self._s = sistema or ControlSistema()
        self._confirmar = callback_confirmacion or _denegar
        self._audit = audit_log
        self._auth = auth_manager

    # ------------------------------------------------------------------
    # Lectura
    # ------------------------------------------------------------------

    async def contar_no_leidos(self) -> int:
        """Devuelve el número de mensajes no leídos.

        Ejemplo::
            n = await mail.contar_no_leidos()
        """
        res = await self._s.ejecutar_applescript(
            'tell application "Mail" to return unread count of inbox'
        )
        try:
            return int(res or "0")
        except ValueError:
            return 0

    async def obtener_no_leidos(self, limite: int = 20) -> list[MensajeCorreo]:
        """Devuelve los mensajes no leídos más recientes.

        Ejemplo::
            mensajes = await mail.obtener_no_leidos(limite=5)
            for m in mensajes:
                print(m.asunto, m.remitente)
        """
        script = f"""
        tell application "Mail"
            set msgs to (messages of inbox whose read status is false)
            set resultado to {{}}
            set contador to 0
            repeat with m in msgs
                if contador >= {limite} then exit repeat
                set info to (message id of m as string) & "|||" & \\
                    (sender of m) & "|||" & \\
                    (subject of m) & "|||" & \\
                    (read status of m as string) & "|||" & \\
                    ((count of mail attachments of m) > 0) as string
                set end of resultado to info
                set contador to contador + 1
            end repeat
            return resultado
        end tell
        """
        salida = await self._s.ejecutar_applescript(script)
        mensajes: list[MensajeCorreo] = []
        if not salida:
            return mensajes

        for linea in salida.split(", "):
            partes = linea.split("|||")
            if len(partes) >= 5:
                mensajes.append(MensajeCorreo(
                    id=partes[0].strip(),
                    remitente=partes[1].strip(),
                    destinatarios=[],
                    asunto=partes[2].strip(),
                    cuerpo="",
                    fecha=datetime.now(),
                    leido=partes[3].strip() == "true",
                    tiene_adjuntos=partes[4].strip() == "true",
                ))
        return mensajes

    async def obtener_mensaje(self, message_id: str) -> MensajeCorreo | None:
        """Obtiene un mensaje completo por su ID.

        Ejemplo::
            msg = await mail.obtener_mensaje("12345")
        """
        script = f"""
        tell application "Mail"
            set m to message id "{_escapar(message_id)}" of inbox
            set info to (message id of m as string) & "|||" & \\
                (sender of m) & "|||" & \\
                (subject of m) & "|||" & \\
                (content of m)
            return info
        end tell
        """
        salida = await self._s.ejecutar_applescript(script)
        if not salida:
            return None
        partes = salida.split("|||", 3)
        if len(partes) < 4:
            return None
        return MensajeCorreo(
            id=partes[0].strip(),
            remitente="",
            destinatarios=[],
            asunto=partes[2].strip() if len(partes) > 2 else "",
            cuerpo=partes[3].strip() if len(partes) > 3 else "",
            fecha=datetime.now(),
            leido=False,
            tiene_adjuntos=False,
        )

    async def buscar_mensajes(self, consulta: str) -> list[MensajeCorreo]:
        """Busca mensajes en el buzón de entrada.

        Ejemplo::
            msgs = await mail.buscar_mensajes("factura diciembre")
        """
        script = f"""
        tell application "Mail"
            set msgs to (messages of inbox whose subject contains "{_escapar(consulta)}")
            set resultado to {{}}
            repeat with m in msgs
                set end of resultado to (message id of m as string) & "|||" & (sender of m) & "|||" & (subject of m)
            end repeat
            return resultado
        end tell
        """
        salida = await self._s.ejecutar_applescript(script)
        mensajes: list[MensajeCorreo] = []
        if not salida:
            return mensajes
        for linea in salida.split(", "):
            partes = linea.split("|||")
            if len(partes) >= 3:
                mensajes.append(MensajeCorreo(
                    id=partes[0].strip(),
                    remitente=partes[1].strip(),
                    destinatarios=[],
                    asunto=partes[2].strip(),
                    cuerpo="",
                    fecha=datetime.now(),
                    leido=False,
                    tiene_adjuntos=False,
                ))
        return mensajes

    # ------------------------------------------------------------------
    # Escritura — siempre requieren confirmación
    # ------------------------------------------------------------------

    async def enviar_mensaje(
        self,
        destinatarios: list[str],
        asunto: str,
        cuerpo: str,
        cc: list[str] | None = None,
        adjuntos: list[str] | None = None,
        *,
        dry_run: bool = False,
    ) -> bool | DryRunResult:
        """Envía un correo. Requiere confirmación obligatoria.

        Con dry_run=True describe el correo que se enviaría sin enviarlo.

        Ejemplo::
            ok = await mail.enviar_mensaje(
                ["usuario@example.com"], "Hola", "Cuerpo del mensaje"
            )
        """
        desc = f"Enviar correo a {', '.join(destinatarios)}: {asunto}"

        if dry_run:
            return DryRunResult(
                accion="mail.enviar_mensaje",
                descripcion=desc,
                efecto_esperado=f"Se enviaría un correo a {', '.join(destinatarios)} con asunto '{asunto}'",
            )

        if self._auth is not None:
            await self._auth.require_auth(desc)
        aprobado = await self._confirmar(desc)
        if not aprobado:
            return False

        dests_as = ", ".join(f'"{_escapar(d)}"' for d in destinatarios)
        cc_block = ""
        if cc:
            cc_as = ", ".join(f'"{_escapar(c)}"' for c in cc)
            cc_block = f"\n                repeat with d in {{{cc_as}}}\n                    make new cc recipient at end of cc recipients with properties {{address: d}}\n                end repeat"

        script = f"""
        tell application "Mail"
            set m to make new outgoing message with properties {{
                subject: "{_escapar(asunto)}",
                content: "{_escapar(cuerpo)}",
                visible: true
            }}
            tell m
                repeat with d in {{{dests_as}}}
                    make new to recipient at end of to recipients with properties {{address: d}}
                end repeat{cc_block}
                send
            end tell
        end tell
        """
        resultado = await self._s.ejecutar_applescript(script)
        await self._audit_log("enviar_mensaje", {"destinatarios": destinatarios, "asunto": asunto})
        return resultado is not None

    async def responder_mensaje(self, message_id: str, cuerpo: str) -> bool:
        """Responde a un mensaje. Requiere confirmación.

        Ejemplo::
            ok = await mail.responder_mensaje("12345", "Gracias por tu mensaje.")
        """
        desc_reply = f"Responder al mensaje {message_id}"
        if self._auth is not None:
            await self._auth.require_auth(desc_reply)
        aprobado = await self._confirmar(desc_reply)
        if not aprobado:
            return False

        script = f"""
        tell application "Mail"
            set m to message id "{_escapar(message_id)}" of inbox
            set r to reply m with opening window
            set content of r to "{_escapar(cuerpo)}"
            send r
        end tell
        """
        resultado = await self._s.ejecutar_applescript(script)
        await self._audit_log("responder_mensaje", {"message_id": message_id})
        return resultado is not None

    async def mover_a_carpeta(self, message_id: str, carpeta: str) -> bool:
        """Mueve un mensaje a una carpeta.

        Ejemplo::
            await mail.mover_a_carpeta("12345", "Archivados")
        """
        script = f"""
        tell application "Mail"
            set m to message id "{_escapar(message_id)}" of inbox
            move m to mailbox "{_escapar(carpeta)}"
        end tell
        """
        return await self._s.ejecutar_applescript(script) is not None

    async def marcar_como_leido(self, message_id: str) -> bool:
        """Marca un mensaje como leído.

        Ejemplo::
            await mail.marcar_como_leido("12345")
        """
        script = f"""
        tell application "Mail"
            set read status of (message id "{_escapar(message_id)}" of inbox) to true
        end tell
        """
        return await self._s.ejecutar_applescript(script) is not None

    async def eliminar_mensaje(self, message_id: str) -> bool:
        """Elimina un mensaje. Requiere confirmación.

        Ejemplo::
            ok = await mail.eliminar_mensaje("12345")
        """
        aprobado = await self._confirmar(f"Eliminar mensaje {message_id}")
        if not aprobado:
            return False

        script = f"""
        tell application "Mail"
            delete (message id "{_escapar(message_id)}" of inbox)
        end tell
        """
        resultado = await self._s.ejecutar_applescript(script)
        await self._audit_log("eliminar_mensaje", {"message_id": message_id})
        return resultado is not None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _audit_log(self, evento: str, datos: dict) -> None:
        if self._audit is not None:
            await self._audit.registrar(f"mail.{evento}", datos)


def _escapar(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


# Importaciones diferidas
try:
    from security.audit_log import AuditLog  # noqa: F401
except ImportError:
    AuditLog = None  # type: ignore[assignment,misc]

try:
    from security.auth import AuthManager  # noqa: F401
except ImportError:
    AuthManager = None  # type: ignore[assignment,misc]
