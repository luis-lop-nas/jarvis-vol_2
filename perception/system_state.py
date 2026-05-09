"""Estado del sistema en tiempo real: app activa, RAM, CPU, batería, red, pantalla.

Diseño: SystemState es un dataclass inmutable (snapshot). Las funciones de módulo
get_system_state() y watch_state() son el punto de entrada. context_summary()
devuelve una línea de texto lista para incluir en el prompt del agente.
"""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field

import psutil

from perception.accessibility import AppInfo, Bounds, WindowInfo


# ── Snapshot ──────────────────────────────────────────────────────────────────
@dataclass(slots=True)
class SystemState:
    """Foto completa del estado del sistema en un instante."""

    active_app: AppInfo | None
    active_window: WindowInfo | None
    cpu_percent: float
    ram_used_gb: float
    ram_available_gb: float
    battery_percent: int | None
    is_charging: bool | None
    wifi_connected: bool
    wifi_ssid: str | None
    screen_locked: bool
    do_not_disturb: bool
    current_space: int
    running_apps: list[str] = field(default_factory=list)

    def is_busy(self) -> bool:
        """True si CPU > 80 % o RAM disponible < 1 GB."""
        return self.cpu_percent > 80.0 or self.ram_available_gb < 1.0

    def context_summary(self) -> str:
        """Resumen en una línea para incluir como contexto en los prompts del agente.

        Ejemplo:
            >>> state.context_summary()
            'VS Code activo · main.py · 4.2GB RAM libre · WiFi'
        """
        partes: list[str] = []
        if self.active_app:
            partes.append(f"{self.active_app.name} activo")
        if self.active_window and self.active_window.title:
            partes.append(self.active_window.title)
        partes.append(f"{self.ram_available_gb:.1f}GB RAM libre")
        if self.wifi_connected:
            ssid = f" ({self.wifi_ssid})" if self.wifi_ssid else ""
            partes.append(f"WiFi{ssid}")
        else:
            partes.append("sin red")
        if self.screen_locked:
            partes.append("pantalla bloqueada")
        return " · ".join(partes)


# ── Recolectores síncronos ────────────────────────────────────────────────────
def _app_activa_sync() -> AppInfo | None:
    try:
        from AppKit import NSWorkspace  # type: ignore[import-not-found]

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return AppInfo(
            bundle_id=str(app.bundleIdentifier() or ""),
            name=str(app.localizedName() or ""),
            pid=int(app.processIdentifier()),
        )
    except Exception:
        return None


def _ventana_activa_sync(pid: int) -> WindowInfo | None:
    try:
        from ApplicationServices import (  # type: ignore[import-not-found]
            AXUIElementCopyAttributeValue,
            AXUIElementCreateApplication,
        )

        ax_app = AXUIElementCreateApplication(pid)
        _, window = AXUIElementCopyAttributeValue(ax_app, "AXFocusedWindow", None)
        if window is None:
            return None
        _, titulo = AXUIElementCopyAttributeValue(window, "AXTitle", None)
        _, fullscreen = AXUIElementCopyAttributeValue(window, "AXFullScreen", None)
        return WindowInfo(
            title=str(titulo) if titulo else None,
            bounds=None,  # bounds no es crítico para el resumen
            is_fullscreen=bool(fullscreen or False),
        )
    except Exception:
        return None


def _ram_sync() -> tuple[float, float]:
    """(ram_used_gb, ram_available_gb)."""
    mem = psutil.virtual_memory()
    return mem.used / 1e9, mem.available / 1e9


def _bateria_sync() -> tuple[int | None, bool | None]:
    """(porcentaje, cargando). None si no hay batería."""
    bat = psutil.sensors_battery()
    if bat is None:
        return None, None
    return int(bat.percent), bool(bat.power_plugged)


def _wifi_sync() -> tuple[bool, str | None]:
    """(conectado, ssid)."""
    try:
        resultado = subprocess.run(
            ["networksetup", "-getairportnetwork", "en0"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        salida = resultado.stdout.strip()
        if "You are not associated" in salida or resultado.returncode != 0:
            return False, None
        if ": " in salida:
            return True, salida.split(": ", 1)[1].strip() or None
        return True, None
    except Exception:
        return False, None


def _pantalla_bloqueada_sync() -> bool:
    try:
        import Quartz  # type: ignore[import-not-found]

        sesion = Quartz.CGSessionCopyCurrentDictionary()
        return bool(sesion.get("CGSSessionScreenIsLocked", 0))
    except Exception:
        return False


def _no_molestar_sync() -> bool:
    try:
        resultado = subprocess.run(
            ["defaults", "read", "com.apple.notificationcenterui", "doNotDisturb"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        return resultado.stdout.strip() == "1"
    except Exception:
        return False


def _espacio_actual_sync() -> int:
    """Escritorio virtual activo (1-based). Devuelve 1 si no se puede determinar."""
    try:
        import Quartz  # type: ignore[import-not-found]

        # CGSCopyManagedDisplaySpaces es API privada; si falla, devolvemos 1
        conn = Quartz.CGSMainConnectionID()
        spaces = Quartz.CGSCopyManagedDisplaySpaces(conn)
        if not spaces:
            return 1
        for display in spaces:
            actual = display.get("Current Space", {})
            if actual:
                return int(actual.get("id64", 1))
        return 1
    except Exception:
        return 1


def _apps_activas_sync() -> list[str]:
    try:
        from AppKit import NSWorkspace  # type: ignore[import-not-found]

        return [
            str(app.bundleIdentifier() or "")
            for app in NSWorkspace.sharedWorkspace().runningApplications()
            if app.bundleIdentifier()
        ]
    except Exception:
        return []


# ── API pública ───────────────────────────────────────────────────────────────
async def get_system_state() -> SystemState:
    """Obtiene un snapshot completo del sistema de forma concurrente.

    Ejemplo:
        >>> estado = await get_system_state()
        >>> print(estado.context_summary())
        'VS Code activo · main.py · 4.2GB RAM libre · WiFi'
    """
    (
        app,
        (ram_used, ram_avail),
        (bat_pct, cargando),
        (wifi_ok, wifi_ssid),
        bloqueada,
        dnd,
        espacio,
        apps,
        cpu,
    ) = await asyncio.gather(
        asyncio.to_thread(_app_activa_sync),
        asyncio.to_thread(_ram_sync),
        asyncio.to_thread(_bateria_sync),
        asyncio.to_thread(_wifi_sync),
        asyncio.to_thread(_pantalla_bloqueada_sync),
        asyncio.to_thread(_no_molestar_sync),
        asyncio.to_thread(_espacio_actual_sync),
        asyncio.to_thread(_apps_activas_sync),
        asyncio.to_thread(psutil.cpu_percent, 0.1),
    )

    ventana: WindowInfo | None = None
    if app is not None:
        ventana = await asyncio.to_thread(_ventana_activa_sync, app.pid)

    return SystemState(
        active_app=app,
        active_window=ventana,
        cpu_percent=float(cpu),
        ram_used_gb=ram_used,
        ram_available_gb=ram_avail,
        battery_percent=bat_pct,
        is_charging=cargando,
        wifi_connected=wifi_ok,
        wifi_ssid=wifi_ssid,
        screen_locked=bloqueada,
        do_not_disturb=dnd,
        current_space=espacio,
        running_apps=apps,
    )


def _estado_cambio_relevante(anterior: SystemState, actual: SystemState) -> bool:
    """True si hubo un cambio que merezca notificar al agente."""
    if anterior.active_app != actual.active_app:
        return True
    if anterior.screen_locked != actual.screen_locked:
        return True
    if not anterior.is_busy() and actual.is_busy():
        return True
    if anterior.wifi_connected != actual.wifi_connected:
        return True
    return False


async def watch_state(
    callback: Callable[[SystemState], None],
    interval: float = 1.0,
) -> asyncio.Task[None]:
    """Lanza una tarea asyncio que llama a `callback` cuando el estado cambia.

    Detecta cambios relevantes: nueva app activa, pantalla bloqueada,
    RAM/CPU críticos, pérdida de red.

    Ejemplo:
        >>> task = await watch_state(lambda s: print(s.context_summary()))
        >>> # ...
        >>> task.cancel()
    """
    ultimo_estado = await get_system_state()

    async def _loop() -> None:
        nonlocal ultimo_estado
        while True:
            await asyncio.sleep(interval)
            actual = await get_system_state()
            if _estado_cambio_relevante(ultimo_estado, actual):
                callback(actual)
            ultimo_estado = actual

    return asyncio.create_task(_loop())


async def is_busy() -> bool:
    """True si el sistema está bajo carga alta (CPU > 80 % o RAM libre < 1 GB).

    Ejemplo:
        >>> if await is_busy(): print("sistema ocupado")
    """
    estado = await get_system_state()
    return estado.is_busy()


async def context_summary() -> str:
    """Resumen del estado en una línea, listo para insertar en un prompt.

    Ejemplo:
        >>> await context_summary()
        'VS Code activo · main.py · 4.2GB RAM libre · WiFi'
    """
    estado = await get_system_state()
    return estado.context_summary()
