"""Capa de seguridad de JARVIS — autenticación, sandbox, confirmaciones y auditoría.

Otros módulos solo importan desde aquí.
Las instancias globales se inicializan en main.py.
"""

from security.audit_log import AuditEntry, AuditLog
from security.auth import AuthError, AuthManager, AuthResult
from security.confirmation import (
    ConfirmationError,
    ConfirmationManager,
    ConfirmationRequest,
    ConfirmationResult,
)
from security.permissions import Permission, PermissionsManager, PermissionStatus
from security.sandbox import CommandRisk, Sandbox, SandboxError, SandboxResult

# Compatibilidad con código anterior que importaba los nombres viejos
AutenticadorLocal = AuthManager
GestorConfirmacion = ConfirmationManager

__all__ = [
    # auth
    "AuthManager",
    "AuthError",
    "AuthResult",
    # sandbox
    "Sandbox",
    "SandboxError",
    "SandboxResult",
    "CommandRisk",
    # confirmation
    "ConfirmationManager",
    "ConfirmationRequest",
    "ConfirmationResult",
    "ConfirmationError",
    # audit_log
    "AuditLog",
    "AuditEntry",
    # permissions
    "PermissionsManager",
    "Permission",
    "PermissionStatus",
    # compat
    "AutenticadorLocal",
    "GestorConfirmacion",
]

# ---------------------------------------------------------------------------
# Instancias globales — inicializadas una vez en main.py
# ---------------------------------------------------------------------------

auth_manager: AuthManager | None = None
sandbox: Sandbox | None = None
confirmation_manager: ConfirmationManager | None = None
audit_log: AuditLog | None = None
permissions_manager: PermissionsManager | None = None
