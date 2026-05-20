"""Gestor de ventana del terminal. Redimensiona con osascript según el modo activo."""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
from enum import Enum

log = logging.getLogger(__name__)


class DisplayMode(str, Enum):
    CORNER = "corner"  # 200×35px esquina sup-derecha — compacto
    STRIP  = "strip"   # 240px ancho, alto completo — log lateral
    FULL   = "full"    # 540px ancho, alto completo — panel conversación


# Mapa WS state hint → DisplayMode
_STATE_MAP: dict[str, DisplayMode] = {
    "silent":  DisplayMode.CORNER,
    "notch":   DisplayMode.CORNER,
    "edge":    DisplayMode.STRIP,
    "modal":   DisplayMode.FULL,
    "inline":  DisplayMode.STRIP,
}


def mode_for_state(state: str, tipo: str, user_active: bool) -> DisplayMode:
    """Decide el modo de display a partir del hint del backend."""
    if tipo in {"waiting"}:
        return DisplayMode.FULL          # confirmación → siempre full
    if tipo in {"thinking", "acting"}:
        return _STATE_MAP.get(state, DisplayMode.STRIP)
    if tipo == "done" and user_active:
        return DisplayMode.FULL          # conversación activa → queda full
    if tipo in {"done", "error"}:
        return DisplayMode.CORNER        # tarea silenciosa → colapsa
    return _STATE_MAP.get(state, DisplayMode.FULL)


class TerminalWindowManager:
    """Redimensiona la ventana del terminal según DisplayMode.

    Detecta automáticamente iTerm2 o Terminal.app.
    El env var JARVIS_TERMINAL_APP sobreescribe la detección.

    Ejemplo::
        wm = TerminalWindowManager()
        await wm.resize(DisplayMode.STRIP)
    """

    def __init__(self) -> None:
        self._app  = os.environ.get("JARVIS_TERMINAL_APP") or self._detect()
        self._sw, self._sh = self._screen_size()
        log.debug("WindowManager: terminal=%s screen=%dx%d", self._app, self._sw, self._sh)

    @property
    def screen(self) -> tuple[int, int]:
        return self._sw, self._sh

    async def resize(self, mode: DisplayMode) -> None:
        x1, y1, x2, y2 = self._bounds(mode)
        script = self._script(x1, y1, x2, y2)
        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript", "-e", script,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.communicate(), timeout=2.0)
        except Exception as exc:
            log.debug("resize failed: %s", exc)

    # -- Privado ---------------------------------------------------------------

    def _bounds(self, mode: DisplayMode) -> tuple[int, int, int, int]:
        sw, sh = self._sw, self._sh
        top = 25   # barra de menú macOS
        usable_h = sh - top

        if mode == DisplayMode.CORNER:
            w, h = 200, 36
            return sw - w, top, sw, top + h

        if mode == DisplayMode.STRIP:
            w = 250
            return sw - w, top, sw, top + usable_h

        # FULL
        w = min(560, int(sw * 0.39))
        return sw - w, top, sw, top + usable_h

    def _script(self, x1: int, y1: int, x2: int, y2: int) -> str:
        bounds = f"{{{x1}, {y1}, {x2}, {y2}}}"
        if "iterm" in self._app.lower():
            return f'tell application "iTerm2" to tell current window to set bounds to {bounds}'
        return f'tell application "Terminal" to set bounds of front window to {bounds}'

    def _detect(self) -> str:
        try:
            import psutil
            p = psutil.Process(os.getpid())
            for parent in p.parents():
                name = parent.name().lower()
                if "iterm" in name:
                    return "iTerm2"
                if "terminal" in name:
                    return "Terminal"
        except Exception:
            pass
        return "iTerm2"

    @staticmethod
    def _screen_size() -> tuple[int, int]:
        try:
            out = subprocess.check_output(
                ["python3", "-c",
                 "import subprocess,re; r=subprocess.run(['system_profiler','SPDisplaysDataType'],"
                 "capture_output=True,text=True); m=re.search(r'Resolution: (\\d+) x (\\d+)',r.stdout);"
                 "print(int(m.group(1))//2, int(m.group(2))//2) if m else print(1440,900)"],
                text=True, timeout=3,
            ).strip().split()
            return int(out[0]), int(out[1])
        except Exception:
            return 1440, 900
