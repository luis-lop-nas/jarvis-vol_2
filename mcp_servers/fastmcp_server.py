"""Servidor MCP basado en FastMCP sobre el bus interno de JARVIS.

Reemplaza la capa stdio de JSON-RPC manual de stdio_server.py.
El MCPBus interno permanece intacto: FastMCP actúa solo como transporte.
"""

from __future__ import annotations

import importlib.metadata
import inspect
import logging
import sys
import time
from collections.abc import Callable
from typing import Any

try:
    from fastmcp import FastMCP as _FastMCP

    _FASTMCP_AVAILABLE = True
except ImportError:
    _FastMCP = None  # type: ignore[assignment,misc]
    _FASTMCP_AVAILABLE = False

from core.mcp_bus import MCPBus
from mcp_servers import crear_bus_mcp
from mcp_servers.base import MCPTool

log = logging.getLogger(__name__)

_JSON_TYPE_MAP: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "object": dict,
    "array": list,
}


def _fastmcp_version() -> tuple[int, ...]:
    """Devuelve la versión instalada de fastmcp como tupla de enteros.

    Returns:
        Tupla (major, minor, patch) o (0,) si no está instalado.
    """
    try:
        ver = importlib.metadata.version("fastmcp")
        return tuple(int(x) for x in ver.split(".")[:3] if x.isdigit())
    except Exception:
        return (0,)


def _json_type_to_python(json_type: str | list[str]) -> type:
    """Convierte tipo JSON Schema a tipo Python.

    Args:
        json_type: Tipo JSON Schema (string, integer, etc.) o lista de tipos.

    Returns:
        Tipo Python correspondiente; `object` como fallback.
    """
    if isinstance(json_type, list):
        json_type = json_type[0] if json_type else "string"
    return _JSON_TYPE_MAP.get(str(json_type), object)


def _make_handler(bus: MCPBus, tool: MCPTool) -> Callable:
    """Genera handler async con firma derivada del inputSchema de la herramienta.

    Parchea __signature__ con inspect.Parameter para que FastMCP/Pydantic
    derive el schema JSON correcto sin necesidad de exec().

    Args:
        bus: Bus MCP que ejecutará la herramienta.
        tool: Definición MCP con nombre, descripción e inputSchema.

    Returns:
        Función async con __signature__ ajustada y __name__ canónico.
    """
    tool_name = tool.name
    properties = tool.input_schema.get("properties", {})
    required_set = set(tool.input_schema.get("required", []))

    async def _handler(**_kwargs: Any) -> Any:
        """Delega la ejecución al MCPBus interno de JARVIS."""
        result = await bus.execute(tool_name, _kwargs)
        if not result.success:
            raise ValueError(result.error or f"Herramienta {tool_name} falló")
        return result.data

    params: list[inspect.Parameter] = []
    for name, prop in properties.items():
        raw_type = prop.get("type", "string")
        py_type = _json_type_to_python(raw_type)
        if name in required_set:
            annotation: Any = py_type
            param = inspect.Parameter(
                name,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                annotation=annotation,
            )
        else:
            annotation = py_type | None  # type: ignore[assignment]
            param = inspect.Parameter(
                name,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                default=None,
                annotation=annotation,
            )
        params.append(param)

    _handler.__signature__ = inspect.Signature(params, return_annotation=Any)
    _handler.__name__ = tool_name.replace(".", "_")
    _handler.__doc__ = tool.description
    return _handler


def _otel_wrap(handler: Callable, tool_name: str) -> Callable:
    """Envuelve handler con tracing OTel mínimo emitido a stderr en JSON Lines.

    Solo activo si fastmcp >= 3.0.0 y settings.mcp_otel_enabled = True.
    Se emite a stderr para no interferir con el protocolo MCP por stdout.
    Los parámetros nunca se incluyen en el span (pueden contener datos sensibles).

    Args:
        handler: Handler original de la herramienta.
        tool_name: Nombre canónico para el campo span.tool_name.

    Returns:
        Handler con tracing añadido que preserva __signature__.
    """
    import json as _json

    original_sig = getattr(handler, "__signature__", None)

    async def _traced(**kwargs: Any) -> Any:
        t0 = time.monotonic()
        success = True
        try:
            return await handler(**kwargs)
        except Exception:
            success = False
            raise
        finally:
            span = {
                "span": "mcp_tool_call",
                "tool_name": tool_name,
                "session_id": "",
                "duration_ms": round((time.monotonic() - t0) * 1000, 2),
                "success": success,
            }
            sys.stderr.write(_json.dumps(span) + "\n")
            sys.stderr.flush()

    if original_sig is not None:
        _traced.__signature__ = original_sig
    _traced.__name__ = handler.__name__
    _traced.__doc__ = handler.__doc__
    return _traced


def _build_server(bus: MCPBus) -> Any:
    """Construye el servidor FastMCP registrando todas las herramientas del bus.

    Itera sobre bus.list_tools() y registra cada herramienta con su nombre,
    descripción e inputSchema conservando la lógica de auditoría, confirmación
    y sanitización del bus interno intacta.

    Args:
        bus: Bus MCP con servidores ya registrados.

    Returns:
        Instancia FastMCP lista para run().
    """
    from config.settings import settings

    mcp = _FastMCP("jarvis_mcp")
    otel_active = settings.mcp_otel_enabled and _fastmcp_version() >= (3, 0, 0)

    for mcp_tool in bus.list_tools():
        handler = _make_handler(bus, mcp_tool)
        if otel_active:
            handler = _otel_wrap(handler, mcp_tool.name)
        mcp.add_tool(handler, name=mcp_tool.name, description=mcp_tool.description)
        log.debug("Herramienta FastMCP registrada: %s", mcp_tool.name)

    return mcp


def main() -> None:
    """Arranca el servidor FastMCP stdio de JARVIS.

    Si FastMCP no está instalado, recae en stdio_server.py como fallback.
    FastMCP gestiona su propio event loop interno (anyio).

    Returns:
        None.
    """
    if not _FASTMCP_AVAILABLE:
        import asyncio

        log.warning("fastmcp no disponible — usando stdio_server como fallback")
        from mcp_servers.stdio_server import main as _fallback

        asyncio.run(_fallback())
        return

    bus = crear_bus_mcp()
    server = _build_server(bus)
    server.run()


if __name__ == "__main__":
    main()
