"""Tests del servidor MCP de memoria."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from mcp_servers.server_memory import ServidorMemoria


@pytest.mark.asyncio
async def test_mcp_memory_uses_public_facade() -> None:
    """ServidorMemoria delega en métodos públicos de MemorySystem."""
    memoria = AsyncMock()
    memoria.get_context = AsyncMock(return_value="ctx")
    memoria.health_check = AsyncMock(return_value={"chroma": True})
    servidor = ServidorMemoria(memory_system=memoria)

    contexto = await servidor.ejecutar("memory.contexto", {"task": "leer", "max_tokens": 50})
    health = await servidor.ejecutar("memory.health", {})

    assert contexto == "ctx"
    assert health["chroma"] is True
    memoria.get_context.assert_awaited_once_with("leer", 50)


@pytest.mark.asyncio
async def test_mcp_memory_unknown_tool() -> None:
    """Herramienta desconocida en memoria lanza ValueError explícito."""
    servidor = ServidorMemoria(memory_system=AsyncMock())

    with pytest.raises(ValueError, match="desconocida"):
        await servidor.ejecutar("memory.nope", {})
