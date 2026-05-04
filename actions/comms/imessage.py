"""Envío de iMessages vía AppleScript / app Messages."""

from __future__ import annotations

from dataclasses import dataclass

from actions.system import ControlSistema


@dataclass(slots=True)
class MensajeIMessage:
    """Mensaje de iMessage a enviar."""

    destinatario: str
    texto: str
    servicio: str = "iMessage"


class IMessage:
    """Adaptador AppleScript para Messages.app."""

    def __init__(self, sistema: ControlSistema | None = None) -> None:
        self._sistema = sistema or ControlSistema()

    async def enviar(self, mensaje: MensajeIMessage) -> None:
        """Envía un iMessage al destinatario indicado."""
        script = f"""
        tell application "Messages"
            set servicioObjetivo to 1st service whose service type = {mensaje.servicio}
            set buddyObjetivo to buddy "{mensaje.destinatario}" of servicioObjetivo
            send "{self._escapar(mensaje.texto)}" to buddyObjetivo
        end tell
        """
        await self._sistema.ejecutar_applescript(script)

    @staticmethod
    def _escapar(texto: str) -> str:
        return texto.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
