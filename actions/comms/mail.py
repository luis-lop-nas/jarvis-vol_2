"""Integración con Apple Mail vía AppleScript."""

from __future__ import annotations

from dataclasses import dataclass

from actions.system import ControlSistema


@dataclass(slots=True)
class Correo:
    """Representación mínima de un correo electrónico."""

    asunto: str
    remitente: str
    destinatarios: list[str]
    cuerpo: str
    cuenta: str | None = None


class Mail:
    """Lectura y envío de correos a través de la app Mail.app."""

    def __init__(self, sistema: ControlSistema | None = None) -> None:
        self._sistema = sistema or ControlSistema()

    async def enviar(self, correo: Correo, *, enviar_inmediatamente: bool = False) -> None:
        """Crea un borrador (o lo envía directamente)."""
        destinatarios = ", ".join(f'"{d}"' for d in correo.destinatarios)
        accion_final = "send" if enviar_inmediatamente else "save"
        script = f"""
        tell application "Mail"
            set nuevoMensaje to make new outgoing message with properties {{
                subject: "{self._escapar(correo.asunto)}",
                content: "{self._escapar(correo.cuerpo)}",
                visible: true
            }}
            tell nuevoMensaje
                repeat with destinatario in {{{destinatarios}}}
                    make new to recipient at end of to recipients with properties {{address: destinatario}}
                end repeat
                {accion_final}
            end tell
        end tell
        """
        await self._sistema.ejecutar_applescript(script)

    async def listar_no_leidos(self, cuenta: str | None = None, limite: int = 20) -> list[Correo]:
        """Devuelve los últimos correos no leídos (lectura solo de cabeceras)."""
        # Implementación pendiente: requiere AppleScript más elaborado o
        # acceso directo a la base de datos de Mail. Por ahora devuelve [].
        _ = cuenta, limite
        return []

    @staticmethod
    def _escapar(texto: str) -> str:
        return texto.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
