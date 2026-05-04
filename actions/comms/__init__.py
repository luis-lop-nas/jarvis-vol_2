"""Adaptadores de canales de comunicación (mail, mensajería)."""

from actions.comms.imessage import IMessage
from actions.comms.mail import Mail
from actions.comms.telegram import Telegram
from actions.comms.whatsapp import WhatsApp

__all__ = ["IMessage", "Mail", "Telegram", "WhatsApp"]
