"""Bus MCP interno: enruta herramientas del agente a servidores MCP."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from mcp_servers.base import (
    MCPRequest,
    MCPResult,
    MCPServer,
    MCPTool,
    serializar_dato,
    validar_parametros,
)
from security.audit_log import AuditLog
from security.permission_manager import PermissionManager

log = logging.getLogger(__name__)

_SECRET_KEYS: tuple[str, ...] = (
    "password",
    "contraseña",
    "token",
    "secret",
    "api_key",
    "apikey",
    "authorization",
)


class MCPBus:
    """Registro y despachador seguro de herramientas MCP internas.

    Ejemplo::
        bus = MCPBus([ServidorFilesystem()])
        resultado = await bus.execute("filesystem.leer", {"ruta": "README.md"})
    """

    def __init__(
        self,
        servers: list[MCPServer] | None = None,
        *,
        audit_log: AuditLog | None = None,
        timeout_seconds: float = 120.0,
        permission_manager: PermissionManager | None = None,
    ) -> None:
        self._servers: dict[str, MCPServer] = {}
        self._tools: dict[str, MCPTool] = {}
        self._tool_servers: dict[str, MCPServer] = {}
        self._session_restrictions: dict[str, set[str]] = {}
        self._audit = audit_log
        self._timeout = timeout_seconds
        self._permission_manager = permission_manager
        for server in servers or []:
            self.register(server)

    def register(self, server: MCPServer) -> None:
        """Registra un servidor MCP y sus herramientas.

        Args:
            server: Servidor que declara herramientas con nombres únicos.

        Returns:
            None.
        """
        self._servers[server.nombre] = server
        for tool in server.herramientas():
            if tool.name in self._tools:
                raise ValueError(f"Herramienta MCP duplicada: {tool.name}")
            self._tools[tool.name] = tool
            self._tool_servers[tool.name] = server
        log.info("Servidor MCP registrado: %s", server.nombre)

    def list_tools(self) -> list[MCPTool]:
        """Devuelve todas las herramientas disponibles.

        Returns:
            Lista ordenada por nombre de herramienta.
        """
        return [self._tools[name] for name in sorted(self._tools)]

    def has_tool(self, tool_name: str) -> bool:
        """Indica si existe una herramienta registrada.

        Args:
            tool_name: Nombre canónico de herramienta.

        Returns:
            `True` si el bus puede ejecutar la herramienta.
        """
        return tool_name in self._tools

    def allow_tool(self, tool_name: str, session_id: str) -> bool:
        """Indica si una sesión tiene permiso para usar una herramienta.

        Por defecto todas las herramientas están permitidas. Solo devuelve
        False si la sesión tiene restricciones explícitas sobre esa herramienta.

        Args:
            tool_name: Nombre canónico de la herramienta.
            session_id: Identificador de la sesión que origina la llamada.

        Returns:
            `True` si la herramienta está permitida para la sesión.
        """
        if not session_id:
            return True
        restricted = self._session_restrictions.get(session_id, set())
        return tool_name not in restricted

    def restrict_session(self, session_id: str, tools: list[str]) -> None:
        """Bloquea un conjunto de herramientas para una sesión concreta.

        Args:
            session_id: Identificador de sesión.
            tools: Herramientas que esa sesión no podrá ejecutar.

        Returns:
            None.
        """
        existing = self._session_restrictions.setdefault(session_id, set())
        existing.update(tools)

    async def health_check(self) -> dict[str, bool]:
        """Verifica disponibilidad de cada servidor registrado.

        Llama a herramientas() en cada servidor; si lanza excepción,
        el servidor se considera no disponible.

        Returns:
            Diccionario {nombre_servidor: disponible} para todos los servidores.
        """
        results: dict[str, bool] = {}
        for nombre, server in self._servers.items():
            try:
                herramientas = server.herramientas()
                results[nombre] = len(herramientas) > 0
            except Exception:
                results[nombre] = False
        return results

    async def execute(
        self,
        tool_name: str,
        params: dict[str, Any] | None = None,
        *,
        session_id: str = "",
        requires_confirmation: bool = False,
    ) -> MCPResult:
        """Ejecuta una herramienta MCP y normaliza el resultado.

        Args:
            tool_name: Nombre canónico, por ejemplo `filesystem.leer`.
            params: Parámetros de entrada.
            session_id: Sesión del agente que origina la llamada.
            requires_confirmation: Si el plan marcó confirmación humana.

        Returns:
            Resultado normalizado con éxito, datos o error explícito.
        """
        request = MCPRequest(
            tool_name=tool_name,
            params=params or {},
            session_id=session_id,
            requires_confirmation=requires_confirmation,
        )
        inicio = time.monotonic()
        tool = self._tools.get(request.tool_name)
        if tool is None:
            return MCPResult(
                success=False,
                error=f"Herramienta MCP no registrada: {request.tool_name}",
                tool_name=request.tool_name,
            )
        if not self.allow_tool(request.tool_name, request.session_id):
            return MCPResult(
                success=False,
                error=f"Herramienta no autorizada para esta sesión: {request.tool_name}",
                tool_name=request.tool_name,
            )

        # Verificación centralizada de políticas de permisos
        if self._permission_manager is not None:
            perm = await self._permission_manager.verificar(
                request.tool_name, request.params, request.session_id
            )
            if not perm.permitido:
                return MCPResult(
                    success=False,
                    error=f"PermissionError: {perm.motivo}",
                    side_effects=tool.side_effects,
                    tool_name=request.tool_name,
                )
            if perm.dry_run:
                duracion = int((time.monotonic() - inicio) * 1000)
                return MCPResult(
                    success=True,
                    data={"dry_run": True, "herramienta": request.tool_name, "params": _sanitize(request.params)},
                    duration_ms=duracion,
                    side_effects=tool.side_effects,
                    tool_name=request.tool_name,
                )

        if tool.requires_confirmation and not request.requires_confirmation:
            return MCPResult(
                success=False,
                error=(
                    "PermissionError: herramienta requiere confirmación explícita: "
                    f"{request.tool_name}"
                ),
                side_effects=tool.side_effects,
                tool_name=request.tool_name,
            )
        errores_schema = validar_parametros(request.params, tool.input_schema)
        if errores_schema:
            return MCPResult(
                success=False,
                error=f"ValidationError: {'; '.join(errores_schema)}",
                side_effects=tool.side_effects,
                tool_name=request.tool_name,
            )

        server = self._server_for_tool(request.tool_name)
        await self._audit_event(request, tool)
        try:
            data = await asyncio.wait_for(
                server.ejecutar(request.tool_name, request.params),
                timeout=self._timeout,
            )
            duracion = int((time.monotonic() - inicio) * 1000)
            result = MCPResult(
                success=True,
                data=serializar_dato(data),
                duration_ms=duracion,
                side_effects=tool.side_effects,
                tool_name=request.tool_name,
            )
            await self._audit_result(result)
            return result
        except TimeoutError:
            duracion = int((time.monotonic() - inicio) * 1000)
            result = MCPResult(
                success=False,
                error=f"TimeoutError: MCP superó {self._timeout:.0f}s",
                duration_ms=duracion,
                side_effects=tool.side_effects,
                tool_name=request.tool_name,
            )
            await self._audit_result(result)
            return result
        except Exception as exc:
            duracion = int((time.monotonic() - inicio) * 1000)
            result = MCPResult(
                success=False,
                error=f"{type(exc).__name__}: {exc}",
                duration_ms=duracion,
                side_effects=tool.side_effects,
                tool_name=request.tool_name,
            )
            await self._audit_result(result)
            return result

    def _server_for_tool(self, tool_name: str) -> MCPServer:
        """Localiza el servidor responsable de una herramienta.

        Args:
            tool_name: Nombre canónico de herramienta.

        Raises:
            RuntimeError: Si ningún servidor declara la herramienta.

        Returns:
            Servidor que debe ejecutar la llamada.
        """
        server = self._tool_servers.get(tool_name)
        if server is None:
            raise RuntimeError(f"Servidor no encontrado para herramienta: {tool_name}")
        return server

    async def _audit_event(self, request: MCPRequest, tool: MCPTool) -> None:
        """Registra una llamada MCP con parámetros sanitizados.

        Args:
            request: Solicitud MCP entrante.
            tool: Metadatos de la herramienta.

        Returns:
            None.
        """
        if self._audit is None:
            return
        await self._audit.registrar(
            "mcp_llamada",
            {
                "tool": request.tool_name,
                "params": _sanitize(request.params),
                "session_id": request.session_id,
                "requires_confirmation": request.requires_confirmation or tool.requires_confirmation,
            },
        )

    async def _audit_result(self, result: MCPResult) -> None:
        """Registra el resultado de una llamada MCP.

        Args:
            result: Resultado normalizado.

        Returns:
            None.
        """
        if self._audit is None:
            return
        await self._audit.registrar(
            "mcp_resultado",
            {
                "tool": result.tool_name,
                "success": result.success,
                "error": result.error,
                "duration_ms": result.duration_ms,
                "side_effects": result.side_effects,
            },
        )


def _sanitize(value: Any) -> Any:
    """Oculta secretos en parámetros antes de auditoría.

    Args:
        value: Valor arbitrario de parámetros.

    Returns:
        Valor equivalente con secretos reemplazados por `***`.
    """
    if isinstance(value, dict):
        limpio: dict[str, Any] = {}
        for key, item in value.items():
            key_str = str(key)
            if any(secret in key_str.lower() for secret in _SECRET_KEYS):
                limpio[key_str] = "***"
            else:
                limpio[key_str] = _sanitize(item)
        return limpio
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return value
