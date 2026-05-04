"""Inspección del estado del sistema: apps abiertas, batería, red, etc."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass(slots=True)
class AppActiva:
    pid: int
    nombre: str
    bundle_id: str
    es_frontal: bool = False


@dataclass(slots=True)
class SnapshotSistema:
    """Foto puntual del estado del sistema."""

    apps: list[AppActiva] = field(default_factory=list)
    porcentaje_bateria: float | None = None
    cargando: bool = False
    red_conectada: bool = True
    nombre_red: str | None = None
    volumen: float | None = None
    pantalla_bloqueada: bool = False


class EstadoSistema:
    """Recoge en un único objeto el estado relevante para el agente."""

    async def snapshot(self) -> SnapshotSistema:
        """Obtiene una snapshot completa del sistema."""
        apps_task = asyncio.to_thread(self._listar_apps)
        bateria_task = asyncio.to_thread(self._info_bateria)
        red_task = asyncio.to_thread(self._info_red)
        apps, bateria, red = await asyncio.gather(apps_task, bateria_task, red_task)

        return SnapshotSistema(
            apps=apps,
            porcentaje_bateria=bateria[0],
            cargando=bateria[1],
            red_conectada=red[0],
            nombre_red=red[1],
        )

    def _listar_apps(self) -> list[AppActiva]:
        from AppKit import NSWorkspace  # type: ignore[import-not-found]

        ws = NSWorkspace.sharedWorkspace()
        frontal = ws.frontmostApplication()
        apps: list[AppActiva] = []
        for app in ws.runningApplications():
            apps.append(
                AppActiva(
                    pid=app.processIdentifier(),
                    nombre=str(app.localizedName() or ""),
                    bundle_id=str(app.bundleIdentifier() or ""),
                    es_frontal=app.processIdentifier() == frontal.processIdentifier(),
                )
            )
        return apps

    def _info_bateria(self) -> tuple[float | None, bool]:
        try:
            import subprocess

            salida = subprocess.check_output(["pmset", "-g", "batt"], text=True)
            porcentaje: float | None = None
            cargando = "AC Power" in salida
            for token in salida.split():
                if token.endswith("%;"):
                    porcentaje = float(token.rstrip("%;"))
                    break
            return porcentaje, cargando
        except Exception:  # noqa: BLE001
            return None, False

    def _info_red(self) -> tuple[bool, str | None]:
        try:
            import subprocess

            ssid = subprocess.check_output(
                [
                    "/System/Library/PrivateFrameworks/Apple80211.framework/"
                    "Versions/Current/Resources/airport",
                    "-I",
                ],
                text=True,
                stderr=subprocess.DEVNULL,
            )
            for linea in ssid.splitlines():
                if " SSID:" in linea:
                    nombre = linea.split(":", 1)[1].strip()
                    return True, nombre or None
            return True, None
        except Exception:  # noqa: BLE001
            return False, None
