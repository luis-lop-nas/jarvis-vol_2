"""Servidores MCP que exponen las capacidades de JARVIS como herramientas."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING

from mcp_servers.base import MCPRequest, MCPResult, MCPTool
from mcp_servers.server_code import ServidorCodigo
from mcp_servers.server_comms import ServidorComms
from mcp_servers.server_filesystem import ServidorFilesystem
from mcp_servers.server_input import ServidorInput
from mcp_servers.server_memory import ServidorMemoria
from mcp_servers.server_perception import ServidorPercepcion
from mcp_servers.server_system import ServidorSistema
from security.audit_log import AuditLog

if TYPE_CHECKING:
    from core.mcp_bus import MCPBus

__all__ = [
    "MCPRequest",
    "MCPResult",
    "MCPTool",
    "ServidorCodigo",
    "ServidorComms",
    "ServidorFilesystem",
    "ServidorInput",
    "ServidorMemoria",
    "ServidorPercepcion",
    "ServidorSistema",
    "crear_bus_mcp",
]


def crear_bus_mcp(
    *,
    raiz_filesystem: Path | None = None,
    callback_confirmacion: Callable[[str], Awaitable[bool]] | None = None,
    audit_log: AuditLog | None = None,
) -> MCPBus:
    """Crea el bus MCP interno con servidores seguros por defecto.

    Args:
        raiz_filesystem: Raíz permitida para operaciones de archivos.
        callback_confirmacion: Callback humano fail-closed para acciones sensibles.
        audit_log: Registro de auditoría compartido.

    Returns:
        Bus MCP con servidores filesystem, memory, terminal, system y comms.
    """
    from core.mcp_bus import MCPBus

    return MCPBus(
        [
            ServidorFilesystem(
                raiz=raiz_filesystem,
                callback_confirmacion=callback_confirmacion,
                audit_log=audit_log,
            ),
            ServidorMemoria(),
            ServidorCodigo(
                directorio_trabajo=raiz_filesystem,
                callback_confirmacion=callback_confirmacion,
                audit_log=audit_log,
            ),
            ServidorInput(
                callback_confirmacion=callback_confirmacion,
                audit_log=audit_log,
            ),
            ServidorPercepcion(),
            ServidorSistema(),
            ServidorComms(),
        ],
        audit_log=audit_log,
    )
