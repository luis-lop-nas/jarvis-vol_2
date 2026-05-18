"""Verificación y gestión de permisos macOS necesarios para JARVIS."""

from __future__ import annotations

import asyncio
import enum
import logging
import subprocess
import sys

from pydantic import BaseModel

log = logging.getLogger(__name__)


class Permission(enum.Enum):
    """Permisos macOS que necesita JARVIS."""

    ACCESSIBILITY = "accessibility"
    SCREEN_RECORDING = "screen_recording"
    AUTOMATION = "automation"
    FULL_DISK_ACCESS = "full_disk_access"
    CONTACTS = "contacts"
    NOTIFICATIONS = "notifications"


class PermissionStatus(BaseModel):
    """Estado de un permiso macOS."""

    permission: Permission
    granted: bool
    required: bool
    how_to_grant: str


_SYSTEM_SETTINGS_URLS: dict[Permission, str] = {
    Permission.ACCESSIBILITY: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    Permission.SCREEN_RECORDING: "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
    Permission.AUTOMATION: "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation",
    Permission.FULL_DISK_ACCESS: "x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles",
    Permission.CONTACTS: "x-apple.systempreferences:com.apple.preference.security?Privacy_Contacts",
    Permission.NOTIFICATIONS: "x-apple.systempreferences:com.apple.preference.security?Privacy_Notifications",
}

_HOW_TO_GRANT: dict[Permission, str] = {
    Permission.ACCESSIBILITY: "Sistema → Privacidad → Accesibilidad → añadir JARVIS/Terminal",
    Permission.SCREEN_RECORDING: "Sistema → Privacidad → Grabación de Pantalla → añadir JARVIS/Terminal",
    Permission.AUTOMATION: "Sistema → Privacidad → Automatización → permitir JARVIS",
    Permission.FULL_DISK_ACCESS: "Sistema → Privacidad → Acceso Completo al Disco → añadir JARVIS",
    Permission.CONTACTS: "Sistema → Privacidad → Contactos → permitir JARVIS",
    Permission.NOTIFICATIONS: "Sistema → Privacidad → Notificaciones → permitir JARVIS",
}

_REQUIRED_PERMISSIONS = {Permission.ACCESSIBILITY, Permission.SCREEN_RECORDING}


class PermissionsManager:
    """Verifica y gestiona todos los permisos macOS necesarios al arrancar.

    Ejemplo::
        pm = PermissionsManager()
        pm.verify_critical()  # sys.exit(1) si falta ACCESSIBILITY o SCREEN_RECORDING
    """

    def check_all(self) -> dict[Permission, PermissionStatus]:
        """Verifica todos los permisos de una vez.

        Ejemplo::
            statuses = pm.check_all()
            for perm, status in statuses.items():
                print(perm.value, "OK" if status.granted else "FALTA")
        """
        return {p: self.check(p) for p in Permission}

    def check(self, permission: Permission) -> PermissionStatus:
        """Verifica un permiso específico.

        Ejemplo::
            status = pm.check(Permission.ACCESSIBILITY)
        """
        granted = self._check_granted(permission)
        return PermissionStatus(
            permission=permission,
            granted=granted,
            required=permission in _REQUIRED_PERMISSIONS,
            how_to_grant=_HOW_TO_GRANT[permission],
        )

    def request(self, permission: Permission) -> bool:
        """Abre System Settings en la sección correcta.

        Ejemplo::
            pm.request(Permission.ACCESSIBILITY)  # abre Ajustes del Sistema
        """
        url = _SYSTEM_SETTINGS_URLS.get(permission)
        if url is None:
            return False
        try:
            subprocess.Popen(["open", url])
            return True
        except Exception:
            return False

    def verify_critical(self) -> None:
        """Verifica ACCESSIBILITY y SCREEN_RECORDING; sys.exit(1) si falta alguno.

        Ejemplo::
            pm.verify_critical()  # aborta si falta algún permiso crítico
        """
        faltantes: list[PermissionStatus] = []
        for perm in _REQUIRED_PERMISSIONS:
            status = self.check(perm)
            if not status.granted:
                faltantes.append(status)

        if not faltantes:
            return

        print("\n[JARVIS] Permisos macOS requeridos no concedidos:\n", file=sys.stderr)
        for status in faltantes:
            print(f"  • {status.permission.value}: {status.how_to_grant}", file=sys.stderr)
            self.request(status.permission)
        print("\nReinicia JARVIS tras conceder los permisos.", file=sys.stderr)
        sys.exit(1)

    async def wait_for_permission(self, permission: Permission, timeout: float = 60.0) -> bool:
        """Polling cada 2s hasta que el permiso se conceda o expire el timeout.

        Usado en el onboarding inicial.

        Ejemplo::
            granted = await pm.wait_for_permission(Permission.ACCESSIBILITY, timeout=120)
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            if self._check_granted(permission):
                return True
            await asyncio.sleep(2.0)
        return False

    def get_missing_required(self) -> list[PermissionStatus]:
        """Devuelve los permisos requeridos que faltan.

        Ejemplo::
            missing = pm.get_missing_required()
        """
        return [s for p in _REQUIRED_PERMISSIONS if not (s := self.check(p)).granted]

    # ------------------------------------------------------------------
    # Helpers de verificación
    # ------------------------------------------------------------------

    def _check_granted(self, permission: Permission) -> bool:
        try:
            if permission == Permission.ACCESSIBILITY:
                return self._check_accessibility()
            if permission == Permission.SCREEN_RECORDING:
                return self._check_screen_recording()
            # Otros permisos: optimistic por defecto (no hay API directa en Python)
            return True
        except Exception:
            return False

    @staticmethod
    def _check_accessibility() -> bool:
        try:
            import ctypes
            ctypes.cdll.LoadLibrary("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
            lib = ctypes.CDLL(None)
            # AXIsProcessTrusted
            ax_func = lib.AXIsProcessTrusted
            ax_func.restype = ctypes.c_bool
            return bool(ax_func())
        except Exception:
            pass

        try:
            from perception.accessibility import (
                verificar_permiso_accesibilidad,  # type: ignore[import]
            )
            return verificar_permiso_accesibilidad()
        except Exception:
            return False

    @staticmethod
    def _check_screen_recording() -> bool:
        import os
        import tempfile
        tmp_path = ""
        granted = False
        try:
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
            result = subprocess.run(
                ["screencapture", "-x", "-t", "png", tmp_path],
                capture_output=True,
                timeout=3,
            )
            granted = result.returncode == 0 and os.path.getsize(tmp_path) > 1000
        except Exception:
            granted = False
        finally:
            if tmp_path:
                import contextlib
                with contextlib.suppress(Exception):
                    os.unlink(tmp_path)
        return granted
