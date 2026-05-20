"""Barra de estado: dot animado por fase, modelo activo, hora."""
from __future__ import annotations

from datetime import datetime

from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget

_FASE_LABEL: dict[str, tuple[str, str]] = {
    "init":              ("·",        "#333355"),
    "silent":            ("·",        "#333355"),
    "thinking":          ("pensando", "#387ddd"),
    "perceive":          ("viendo",   "#387ddd"),
    "plan":              ("plan",     "#387ddd"),
    "acting":            ("exec",     "#387ddd"),
    "execute_tool":      ("exec",     "#387ddd"),
    "verify":            ("verif.",   "#556688"),
    "reflect":           ("reflej.",  "#556688"),
    "replan":            ("replan",   "#f0a030"),
    "wait_confirmation": ("espera",   "#f0a030"),
    "waiting":           ("espera",   "#f0a030"),
    "done":              ("listo",    "#4caf50"),
    "error":             ("error",    "#ef5350"),
    "cancelled":         ("—",        "#555555"),
}

_ACTIVE_FASES = frozenset({
    "thinking", "perceive", "plan", "acting", "execute_tool",
    "verify", "reflect", "replan",
})

_DOT_FRAMES = ("◉", "◎")   # frames de animación del dot


class HeaderBar(Widget):
    """Header fijo con dot animado, fase y hora. Adapta su verbosidad al ancho."""

    DEFAULT_CSS = """
    HeaderBar {
        height: 1;
        background: #141416;
        padding: 0 1;
        content-align: left middle;
    }
    """

    connected: reactive[bool] = reactive(False)
    model:     reactive[str]  = reactive("")
    fase:      reactive[str]  = reactive("init")
    _frame:    reactive[int]  = reactive(0)

    def on_mount(self) -> None:
        self.set_interval(0.9, self._tick)
        self.set_interval(30.0, self.refresh)    # actualiza reloj

    def _tick(self) -> None:
        if self.fase in _ACTIVE_FASES:
            self._frame = 1 - self._frame        # alterna dot
        else:
            self._frame = 0

    def render(self) -> Text:
        wide = self.size.width >= 38

        # Dot
        dot   = _DOT_FRAMES[self._frame]
        if not self.connected:
            dot_style = "#333344"
        elif self.fase in _ACTIVE_FASES:
            dot_style = "bold #387ddd"
        elif self.fase == "done":
            dot_style = "#4caf50"
        elif self.fase == "error":
            dot_style = "#ef5350"
        elif self.fase in {"waiting", "wait_confirmation", "replan"}:
            dot_style = "#f0a030"
        else:
            dot_style = "#333355"

        t = Text(overflow="fold", no_wrap=True)
        t.append(f"{dot} ", style=dot_style)
        t.append("JARVIS", style="bold #387ddd")

        if wide:
            label, color = _FASE_LABEL.get(self.fase, (self.fase, "#888888"))
            if label not in {"·", "—"}:
                t.append(f"  {label}", style=color)
            if self.model:
                t.append(f"  {self.model}", style="#223344")
            now = datetime.now().strftime("%H:%M")
            t.append(f"  {now}", style="#222233")

        return t
