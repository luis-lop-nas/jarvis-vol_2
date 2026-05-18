"""Servidor MCP stdio mínimo sobre el bus interno de JARVIS."""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, TextIO

from pydantic import BaseModel, Field

from core.mcp_bus import MCPBus
from mcp_servers import crear_bus_mcp

_PROTOCOLO_MCP = "2024-11-05"
_SERVER_INFO = {"name": "jarvis_mcp", "version": "0.7.0"}


class JsonRpcRequest(BaseModel):
    """Solicitud JSON-RPC recibida por stdio.

    Ejemplo::
        JsonRpcRequest(jsonrpc="2.0", id=1, method="tools/list")
    """

    jsonrpc: str = "2.0"
    id: int | str | None = None
    method: str
    params: dict[str, Any] = Field(default_factory=dict)


class JsonRpcResponse(BaseModel):
    """Respuesta JSON-RPC emitida por stdio.

    Ejemplo::
        JsonRpcResponse(id=1, result={"ok": True})
    """

    jsonrpc: str = "2.0"
    id: int | str | None = None
    result: Any | None = None
    error: dict[str, Any] | None = None


class MCPStdioServer:
    """Expone `MCPBus` mediante el subconjunto stdio del protocolo MCP.

    Ejemplo::
        servidor = MCPStdioServer(bus)
        respuesta = await servidor.handle_json({...})
    """

    def __init__(self, bus: MCPBus | None = None) -> None:
        self._bus = bus or crear_bus_mcp()

    async def handle_json(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Procesa un mensaje JSON-RPC ya parseado.

        Args:
            payload: Mensaje entrante como diccionario.

        Returns:
            Respuesta JSON-RPC o `None` para notificaciones sin respuesta.
        """
        try:
            request = JsonRpcRequest(**payload)
        except Exception as exc:
            return JsonRpcResponse(
                id=payload.get("id"),
                error={"code": -32600, "message": f"Solicitud inválida: {exc}"},
            ).model_dump(exclude_none=True)

        if request.id is None and request.method.startswith("notifications/"):
            return None

        try:
            result = await self._dispatch(request)
            return JsonRpcResponse(id=request.id, result=result).model_dump(exclude_none=True)
        except ValueError as exc:
            return JsonRpcResponse(
                id=request.id,
                error={"code": -32602, "message": str(exc)},
            ).model_dump(exclude_none=True)
        except Exception as exc:
            return JsonRpcResponse(
                id=request.id,
                error={"code": -32603, "message": f"{type(exc).__name__}: {exc}"},
            ).model_dump(exclude_none=True)

    async def serve(self, stdin: TextIO | None = None, stdout: TextIO | None = None) -> None:
        """Atiende mensajes JSON-RPC línea a línea por stdio.

        Args:
            stdin: Flujo de entrada; por defecto `sys.stdin`.
            stdout: Flujo de salida; por defecto `sys.stdout`.

        Returns:
            None.
        """
        entrada = stdin or sys.stdin
        salida = stdout or sys.stdout
        while True:
            linea = await asyncio.to_thread(entrada.readline)
            if not linea:
                break
            try:
                payload = json.loads(linea)
            except json.JSONDecodeError as exc:
                response = JsonRpcResponse(
                    error={"code": -32700, "message": f"JSON inválido: {exc.msg}"},
                ).model_dump(exclude_none=True)
            else:
                response = await self.handle_json(payload)
            if response is not None:
                await asyncio.to_thread(salida.write, json.dumps(response, ensure_ascii=False) + "\n")
                await asyncio.to_thread(salida.flush)

    async def _dispatch(self, request: JsonRpcRequest) -> dict[str, Any]:
        """Despacha métodos MCP soportados.

        Args:
            request: Solicitud JSON-RPC validada.

        Raises:
            ValueError: Si el método o los parámetros no son válidos.

        Returns:
            Resultado serializable para JSON-RPC.
        """
        match request.method:
            case "initialize":
                return {
                    "protocolVersion": _PROTOCOLO_MCP,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": _SERVER_INFO,
                }
            case "tools/list":
                return {"tools": [tool.to_protocol_dict() for tool in self._bus.list_tools()]}
            case "tools/call":
                return await self._call_tool(request.params)
            case _:
                raise ValueError(f"Método MCP no soportado: {request.method}")

    async def _call_tool(self, params: dict[str, Any]) -> dict[str, Any]:
        """Ejecuta una herramienta solicitada por `tools/call`.

        Args:
            params: Parámetros MCP con `name`, `arguments` y confirmación opcional.

        Returns:
            Respuesta MCP con `content` textual e indicador `isError`.
        """
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise ValueError("tools/call requiere params.name")
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            raise ValueError("tools/call requiere params.arguments como objeto")
        requires_confirmation = bool(params.get("requires_confirmation", False))
        resultado = await self._bus.execute(
            name,
            arguments,
            session_id=str(params.get("session_id", "")),
            requires_confirmation=requires_confirmation,
        )
        cuerpo = {
            "success": resultado.success,
            "data": resultado.data,
            "error": resultado.error,
            "duration_ms": resultado.duration_ms,
            "side_effects": resultado.side_effects,
            "tool_name": resultado.tool_name,
        }
        return {
            "content": [{"type": "text", "text": json.dumps(cuerpo, ensure_ascii=False)}],
            "isError": not resultado.success,
        }


async def main() -> None:
    """Arranca el servidor MCP stdio de JARVIS.

    Returns:
        None.
    """
    await MCPStdioServer().serve()


if __name__ == "__main__":
    asyncio.run(main())
