"""Detección de app activa en macOS mediante polling con osascript.

Omite terminales y Python para siempre mostrar el último contexto útil.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)

_SKIP_APPS = frozenset({
    "terminal", "iterm2", "iterm", "python3", "python",
    "alacritty", "kitty", "hyper", "warp", "ghostty",
})

_APPLESCRIPT = """\
tell application "System Events"
    set p to first process where frontmost is true
    set appName to name of p
    set bundleId to ""
    try
        set bundleId to bundle identifier of p
    end try
    set winTitle to ""
    try
        set winTitle to name of first window of p
    end try
    return appName & "|" & bundleId & "|" & winTitle
end tell
"""

_APP_ICONS: dict[str, str] = {
    "code":    "󰨞 ",
    "xcode":   "🔨 ",
    "safari":  "🌐 ",
    "chrome":  "🌐 ",
    "firefox": "🦊 ",
    "finder":  "📁 ",
    "notes":   "📝 ",
    "notion":  "📓 ",
    "slack":   "💬 ",
    "zoom":    "📹 ",
    "spotify": "🎵 ",
    "discord": "🎮 ",
}


def app_icon(name: str) -> str:
    lower = name.lower()
    for key, icon in _APP_ICONS.items():
        if key in lower:
            return icon
    return "◆ "


@dataclass
class AppContext:
    """Contexto de la app activa del sistema."""

    app_name: str = ""
    bundle_id: str = ""
    window_title: str = ""

    @property
    def is_empty(self) -> bool:
        return not self.app_name

    @property
    def icon(self) -> str:
        return app_icon(self.app_name)

    @property
    def short_title(self) -> str:
        if len(self.window_title) > 50:
            return self.window_title[:47] + "…"
        return self.window_title


class ContextWatcher:
    """Observa la app activa. Omite terminales para mantener el último contexto útil.

    Ejemplo::
        watcher = ContextWatcher()
        await watcher.watch(on_change=lambda ctx: print(ctx.app_name))
    """

    def __init__(self, interval: float = 2.0) -> None:
        self.interval = interval
        self._last = AppContext()
        self._running = False

    @property
    def current(self) -> AppContext:
        return self._last

    async def watch(self, on_change: Callable[[AppContext], None]) -> None:
        self._running = True
        while self._running:
            ctx = await self._poll()
            if ctx.app_name and (
                ctx.app_name != self._last.app_name
                or ctx.window_title != self._last.window_title
            ):
                self._last = ctx
                try:
                    on_change(ctx)
                except Exception as exc:
                    log.debug("ContextWatcher on_change error: %s", exc)
            await asyncio.sleep(self.interval)

    def stop(self) -> None:
        self._running = False

    async def _poll(self) -> AppContext:
        try:
            proc = await asyncio.create_subprocess_exec(
                "osascript", "-e", _APPLESCRIPT,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=2.0)
            line = stdout.decode().strip()
        except Exception:
            return self._last

        parts = line.split("|", 2)
        app    = parts[0].strip() if len(parts) > 0 else ""
        bundle = parts[1].strip() if len(parts) > 1 else ""
        title  = parts[2].strip() if len(parts) > 2 else ""

        if any(t in app.lower() for t in _SKIP_APPS):
            return self._last

        return AppContext(app_name=app, bundle_id=bundle, window_title=title)
