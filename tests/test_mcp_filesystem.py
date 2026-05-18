"""Tests del servidor MCP de filesystem."""

from __future__ import annotations

from pathlib import Path

import pytest

from core.mcp_bus import MCPBus
from mcp_servers.server_filesystem import ServidorFilesystem


async def _aprobar(_: str) -> bool:
    """Aprueba confirmaciones en tests controlados."""
    return True


@pytest.mark.asyncio
async def test_mcp_filesystem_read_write_list() -> None:
    """Filesystem MCP permite escribir, leer y listar dentro del sandbox."""
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as tmp:
        raiz = Path(tmp)
        bus = MCPBus([ServidorFilesystem(raiz=raiz, callback_confirmacion=_aprobar)])
        ruta = raiz / "nota.txt"

        escrito = await bus.execute(
            "filesystem.escribir",
            {"ruta": str(ruta), "contenido": "hola"},
            requires_confirmation=True,
        )
        leido = await bus.execute("filesystem.leer", {"ruta": str(ruta)})
        listado = await bus.execute("filesystem.listar", {"ruta": str(raiz)})

        assert escrito.success is True
        assert leido.data == "hola"
        assert listado.success is True
        assert listado.data[0]["nombre"] == "nota.txt"


@pytest.mark.asyncio
async def test_mcp_filesystem_sandbox_blocks_escape(tmp_path: Path) -> None:
    """El servidor respeta el sandbox de SistemaArchivos."""
    bus = MCPBus([ServidorFilesystem(raiz=tmp_path)])

    resultado = await bus.execute("filesystem.leer", {"ruta": "/etc/passwd"})

    assert resultado.success is False
    assert "PermissionError" in (resultado.error or "")
