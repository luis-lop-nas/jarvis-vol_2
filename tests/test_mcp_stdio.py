"""Tests del servidor MCP stdio."""

from __future__ import annotations

import json
from typing import Any

import pytest

from core.mcp_bus import MCPBus
from mcp_servers.base import MCPTool, campo, schema_objeto
from mcp_servers.server_browser import ServidorNavegador
from mcp_servers.server_code import ServidorCodigo
from mcp_servers.server_comms import ServidorComms
from mcp_servers.server_filesystem import ServidorFilesystem
from mcp_servers.server_input import ServidorInput
from mcp_servers.server_memory import ServidorMemoria
from mcp_servers.server_perception import ServidorPercepcion
from mcp_servers.server_system import ServidorSistema
from mcp_servers.stdio_server import MCPStdioServer


class EchoServer:
    """Servidor mínimo para probar el protocolo stdio."""

    nombre = "echo"

    def herramientas(self) -> list[MCPTool]:
        """Declara una herramienta de eco."""
        return [
            MCPTool(
                name="echo.hola",
                description="Devuelve el texto recibido.",
                input_schema=schema_objeto({"texto": campo("string", "Texto")}, ["texto"]),
            )
        ]

    async def ejecutar(self, tool_name: str, params: dict[str, Any]) -> Any:
        """Devuelve los parámetros recibidos."""
        return {"texto": params["texto"], "tool": tool_name}


@pytest.mark.asyncio
async def test_stdio_initialize() -> None:
    """El servidor responde al handshake initialize de MCP."""
    servidor = MCPStdioServer(MCPBus([EchoServer()]))

    respuesta = await servidor.handle_json({"jsonrpc": "2.0", "id": 1, "method": "initialize"})

    assert respuesta is not None
    assert respuesta["result"]["serverInfo"]["name"] == "jarvis_mcp"
    assert "tools" in respuesta["result"]["capabilities"]


@pytest.mark.asyncio
async def test_stdio_tools_list_contains_schema() -> None:
    """`tools/list` expone schemas y anotaciones MCP."""
    servidor = MCPStdioServer(MCPBus([EchoServer()]))

    respuesta = await servidor.handle_json({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})

    assert respuesta is not None
    herramienta = respuesta["result"]["tools"][0]
    assert herramienta["name"] == "echo.hola"
    assert herramienta["inputSchema"]["required"] == ["texto"]
    assert herramienta["annotations"]["readOnlyHint"] is True


@pytest.mark.asyncio
async def test_stdio_tools_call_returns_text_content() -> None:
    """`tools/call` ejecuta el bus y devuelve contenido textual JSON."""
    servidor = MCPStdioServer(MCPBus([EchoServer()]))

    respuesta = await servidor.handle_json({
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {"name": "echo.hola", "arguments": {"texto": "hola"}},
    })

    assert respuesta is not None
    contenido = respuesta["result"]["content"][0]
    payload = json.loads(contenido["text"])
    assert respuesta["result"]["isError"] is False
    assert payload["data"]["texto"] == "hola"


@pytest.mark.asyncio
async def test_stdio_notifications_do_not_reply() -> None:
    """Las notificaciones MCP sin id no generan respuesta."""
    servidor = MCPStdioServer(MCPBus([EchoServer()]))

    respuesta = await servidor.handle_json({"jsonrpc": "2.0", "method": "notifications/initialized"})

    assert respuesta is None


def test_all_mcp_tools_expose_protocol_schema() -> None:
    """Todas las herramientas reales exponen `inputSchema` MCP de objeto."""
    servidores = [
        ServidorFilesystem(filesystem=object()),
        ServidorMemoria(memory_system=object()),
        ServidorCodigo(terminal=object()),
        ServidorSistema(control=object()),
        ServidorComms(mail=object(), imessage=object()),
        ServidorNavegador(navegador=object(), safari=object()),
        ServidorInput(input_control=object()),
        ServidorPercepcion(),
    ]

    herramientas = [tool for servidor in servidores for tool in servidor.herramientas()]

    assert herramientas
    assert all(tool.input_schema.get("type") == "object" for tool in herramientas)
    assert all("additionalProperties" in tool.input_schema for tool in herramientas)


# ---------------------------------------------------------------------------
# Tests FastMCP
# ---------------------------------------------------------------------------


def test_fastmcp_server_can_be_built() -> None:
    """El servidor FastMCP se construye correctamente desde el bus."""
    from mcp_servers.fastmcp_server import _FASTMCP_AVAILABLE, _build_server

    if not _FASTMCP_AVAILABLE:
        import pytest

        pytest.skip("fastmcp no instalado")

    bus = MCPBus([EchoServer()])
    server = _build_server(bus)

    assert server is not None


@pytest.mark.asyncio
async def test_fastmcp_handler_executes_via_bus() -> None:
    """El handler FastMCP delega la ejecución al bus MCP."""
    from mcp_servers.fastmcp_server import _make_handler

    bus = MCPBus([EchoServer()])
    tool = MCPTool(
        name="echo.hola",
        description="Devuelve el texto recibido.",
        input_schema=schema_objeto({"texto": campo("string", "Texto")}, ["texto"]),
    )

    handler = _make_handler(bus, tool)
    result = await handler(texto="mundo")

    assert result["texto"] == "mundo"


def test_fastmcp_handler_signature_matches_schema() -> None:
    """El handler FastMCP tiene __signature__ con los parámetros del inputSchema."""
    import inspect as _inspect

    from mcp_servers.fastmcp_server import _make_handler

    bus = MCPBus([EchoServer()])
    tool = MCPTool(
        name="echo.hola",
        description="Devuelve el texto recibido.",
        input_schema=schema_objeto({"texto": campo("string", "Texto")}, ["texto"]),
    )

    handler = _make_handler(bus, tool)
    sig = _inspect.signature(handler)

    assert "texto" in sig.parameters
    assert sig.parameters["texto"].annotation is str
