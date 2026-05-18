"""Tests del bus MCP interno de JARVIS."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.mcp_bus import MCPBus
from mcp_servers.base import MCPTool, campo, schema_objeto


class FakeServer:
    """Servidor MCP mínimo para verificar el bus."""

    nombre = "fake"

    def herramientas(self) -> list[MCPTool]:
        """Declara una herramienta de prueba."""
        return [MCPTool(name="fake.echo", description="Eco")]

    async def ejecutar(self, tool_name: str, params: dict[str, Any]) -> Any:
        """Devuelve los parámetros recibidos."""
        return {"tool": tool_name, "params": params}


class SensitiveServer:
    """Servidor con herramienta que exige confirmación."""

    nombre = "sensitive"

    def herramientas(self) -> list[MCPTool]:
        """Declara una herramienta sensible."""
        return [
            MCPTool(
                name="sensitive.write",
                description="Escritura sensible",
                requires_confirmation=True,
                side_effects=["write"],
            )
        ]

    async def ejecutar(self, tool_name: str, params: dict[str, Any]) -> Any:
        """Devuelve éxito si se ejecuta."""
        return {"ok": True}


class SchemaServer:
    """Servidor con schema de entrada obligatorio."""

    nombre = "schema"

    def herramientas(self) -> list[MCPTool]:
        """Declara herramienta con parámetro requerido."""
        return [
            MCPTool(
                name="schema.echo",
                description="Eco validado",
                input_schema=schema_objeto({"texto": campo("string", "Texto")}, ["texto"]),
            )
        ]

    async def ejecutar(self, tool_name: str, params: dict[str, Any]) -> Any:
        """Devuelve los parámetros recibidos si superan validación."""
        return {"texto": params["texto"]}


@pytest.mark.asyncio
async def test_mcp_bus_execute_success() -> None:
    """El bus despacha una herramienta registrada y normaliza el resultado."""
    bus = MCPBus([FakeServer()])

    resultado = await bus.execute("fake.echo", {"texto": "hola"})

    assert resultado.success is True
    assert resultado.data["params"]["texto"] == "hola"


@pytest.mark.asyncio
async def test_mcp_bus_unknown_tool() -> None:
    """Herramientas no registradas devuelven error explícito."""
    bus = MCPBus([FakeServer()])

    resultado = await bus.execute("fake.nope", {})

    assert resultado.success is False
    assert "no registrada" in (resultado.error or "")


@pytest.mark.asyncio
async def test_mcp_bus_audit_sanitizes_secrets() -> None:
    """El audit log no recibe valores secretos en parámetros."""
    audit = MagicMock()
    audit.registrar = AsyncMock()
    bus = MCPBus([FakeServer()], audit_log=audit)

    await bus.execute("fake.echo", {"api_key": "secret", "normal": "ok"})

    llamada = audit.registrar.await_args_list[0].args[1]
    assert llamada["params"]["api_key"] == "***"
    assert llamada["params"]["normal"] == "ok"


@pytest.mark.asyncio
async def test_mcp_bus_blocks_sensitive_without_confirmation() -> None:
    """El bus rechaza herramientas sensibles si el plan no marca confirmación."""
    bus = MCPBus([SensitiveServer()])

    resultado = await bus.execute("sensitive.write", {})

    assert resultado.success is False
    assert "confirmación" in (resultado.error or "")


@pytest.mark.asyncio
async def test_mcp_bus_allows_sensitive_with_confirmation() -> None:
    """El bus permite herramientas sensibles si llegan con confirmación explícita."""
    bus = MCPBus([SensitiveServer()])

    resultado = await bus.execute("sensitive.write", {}, requires_confirmation=True)

    assert resultado.success is True


@pytest.mark.asyncio
async def test_mcp_bus_validates_input_schema() -> None:
    """El bus rechaza parámetros incompletos antes de llamar al servidor."""
    bus = MCPBus([SchemaServer()])

    resultado = await bus.execute("schema.echo", {})

    assert resultado.success is False
    assert "ValidationError" in (resultado.error or "")
