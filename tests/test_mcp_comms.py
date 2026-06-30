"""Tests de servidores MCP de comunicación."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from core.mcp_bus import MCPBus
from mcp_servers.server_comms import ServidorComms


@dataclass(slots=True)
class FakeMensajeWhatsApp:
    """Mensaje mínimo compatible con serialización MCP."""

    texto: str
    enviado: bool
    fecha: datetime
    contacto: str


class FakeWhatsApp:
    """Doble de WhatsApp Web para evitar Playwright en tests."""

    def __init__(self) -> None:
        self.enviados: list[tuple[str, str]] = []

    async def obtener_chats_no_leidos(self) -> list[dict[str, object]]:
        """Devuelve chats no leídos simulados."""
        return [{"nombre": "Luichi", "no_leidos": 2}]

    async def obtener_mensajes(self, nombre_chat: str, limite: int = 20) -> list[FakeMensajeWhatsApp]:
        """Devuelve mensajes simulados de un chat."""
        return [
            FakeMensajeWhatsApp(
                texto=f"hola {nombre_chat}",
                enviado=False,
                fecha=datetime(2026, 5, 18, tzinfo=UTC),
                contacto=nombre_chat,
            )
        ][:limite]

    async def enviar_mensaje(self, nombre_chat: str, texto: str) -> bool:
        """Registra el envío simulado."""
        self.enviados.append((nombre_chat, texto))
        return True


@pytest.mark.asyncio
async def test_comms_whatsapp_not_configured() -> None:
    """WhatsApp falla de forma explícita si no hay sesión inyectada."""
    servidor = ServidorComms(mail=object(), imessage=object())

    with pytest.raises(RuntimeError, match="WhatsApp no configurado"):
        await servidor.ejecutar("whatsapp.leer", {})


@pytest.mark.asyncio
async def test_comms_whatsapp_auto_init_session(monkeypatch) -> None:
    """Con auto_init_whatsapp=True el servidor crea la sesión vía initialize_session()."""
    fake = FakeWhatsApp()
    creado = {"n": 0}

    async def fake_initialize_session(**kwargs):
        creado["n"] += 1
        return fake

    monkeypatch.setattr(
        "mcp_servers.server_comms.WhatsApp.initialize_session",
        fake_initialize_session,
    )
    servidor = ServidorComms(mail=object(), imessage=object(), auto_init_whatsapp=True)

    resultado = await servidor.ejecutar("whatsapp.leer", {"contacto": "Pep"})
    # Segunda llamada reutiliza la sesión: initialize_session solo una vez.
    await servidor.ejecutar("whatsapp.leer", {"contacto": "Pep"})

    assert resultado[0]["texto"] == "hola Pep"
    assert creado["n"] == 1


@pytest.mark.asyncio
async def test_comms_whatsapp_read_injected_session() -> None:
    """WhatsApp lee mensajes cuando se inyecta una sesión configurada."""
    servidor = ServidorComms(mail=object(), imessage=object(), whatsapp=FakeWhatsApp())

    resultado = await servidor.ejecutar("whatsapp.leer", {"contacto": "Pep"})

    assert resultado[0]["texto"] == "hola Pep"
    assert resultado[0]["contacto"] == "Pep"


@pytest.mark.asyncio
async def test_comms_whatsapp_send_requires_bus_confirmation() -> None:
    """El envío de WhatsApp solo pasa por el bus con confirmación explícita."""
    whatsapp = FakeWhatsApp()
    bus = MCPBus([ServidorComms(mail=object(), imessage=object(), whatsapp=whatsapp)])

    bloqueado = await bus.execute("whatsapp.enviar", {"contacto": "Pep", "mensaje": "hola"})
    permitido = await bus.execute(
        "whatsapp.enviar",
        {"contacto": "Pep", "mensaje": "hola"},
        requires_confirmation=True,
    )

    assert bloqueado.success is False
    assert permitido.success is True
    assert whatsapp.enviados == [("Pep", "hola")]
