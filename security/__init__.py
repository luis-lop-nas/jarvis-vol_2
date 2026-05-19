"""Capa de seguridad de JARVIS — autenticación, sandbox, confirmaciones y auditoría.

Otros módulos solo importan desde aquí.
Las instancias globales se inicializan en main.py.
"""

from security.audit_log import AuditEntry, AuditLog, AuditStats
from security.auth import AuthError, AuthManager, AuthResult
from security.confirmation import (
    ConfirmationError,
    ConfirmationManager,
    ConfirmationRequest,
    ConfirmationResult,
    SecurityError,
)
from security.permission_manager import (
    InjectionResult,
    PermissionManager,
    PermissionResult,
    RiskLevel,
    ToolPolicy,
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
    "SecurityError",
    # audit_log
    "AuditLog",
    "AuditEntry",
    "AuditStats",
    # permissions (macOS)
    "PermissionsManager",
    "Permission",
    "PermissionStatus",
    # permission_manager (por herramienta)
    "PermissionManager",
    "PermissionResult",
    "ToolPolicy",
    "RiskLevel",
    "InjectionResult",
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
permission_manager: PermissionManager | None = None
