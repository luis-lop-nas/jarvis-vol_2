"""Cards animadas del chat de JARVIS.

Cada evento del agente es un Widget independiente con su propio
ciclo de vida: fade-in de entrada, spinner braille en activo,
transición de estado a completado/fallido.

Inspirado en: Claude Code spinner/tool UX · aider diff display · btop compact stats
"""
from __future__ import annotations

import time
from datetime import datetime

from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.text import Text
from textual.widget import Widget

# Spinner braille — mismo que Claude Code
_SP = ["⣾", "⣽", "⣻", "⢿", "⡿", "⣟", "⣯", "⣷"]

# Paleta terminal-optimizada (más vibrante que la del overlay para dark bg)
_BLUE   = "#4d9fff"
_GREEN  = "#3ddc84"
_AMBER  = "#ffb340"
_RED    = "#ff4a6a"
_PURPLE = "#bf5af2"
_MUTED  = "#6a7a8a"
_DIM    = "#2a3a4a"
_TEXT   = "#dde8f0"


def _ts() -> str:
    return datetime.now().strftime("%H:%M")


# -- Helpers -------------------------------------------------------------------

_TOOL_ICONS: dict[str, str] = {
    "filesystem": "󰙅 ",
    "terminal":   " ",
    "browser":    "󰖟 ",
    "mail":       "󰇮 ",
    "email":      "󰇮 ",
    "calendar":   "󰃭 ",
    "imessage":   "󰍡 ",
    "whatsapp":   "󰖣 ",
    "telegram":   "󰖣 ",
    "keyboard":   "󰌌 ",
    "mouse":      "󰍽 ",
    "ocr":        "󰫙 ",
    "vision":     "󰷺 ",
    "memory":     "󱅀 ",
    "search":     "󰍉 ",
    "vault":      " ",
    "skill":      "󱁥 ",
}

_TOOL_ICONS_FALLBACK: dict[str, str] = {
    "filesystem": "▸ ",
    "terminal":   "$ ",
    "browser":    "◎ ",
    "mail":       "✉ ",
    "email":      "✉ ",
    "calendar":   "◷ ",
    "memory":     "◈ ",
    "search":     "⌕ ",
    "vault":      "⚿ ",
}


def _tool_icon(name: str) -> str:
    lower = name.lower().split(".")[0]
    return _TOOL_ICONS_FALLBACK.get(lower, "⚙ ")


def _shorten_path(text: str, max_len: int = 45) -> str:
    """Acorta rutas largas: /a/b/c/d/file.py → …/c/d/file.py"""
    if len(text) <= max_len or "/" not in text:
        return text
    parts = text.split("/")
    while len("/".join(parts)) > max_len and len(parts) > 2:
        parts = ["…"] + parts[2:]
    return "/".join(parts)


def _fmt_elapsed(ms: float) -> str:
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms/1000:.1f}s"


# -- Base card -----------------------------------------------------------------

class _BaseCard(Widget):
    DEFAULT_CSS = "_BaseCard { height: auto; margin: 0 1 0 1; }"

    def on_mount(self) -> None:
        self.animate("opacity", value=1.0, duration=0.22, easing="out_cubic")

    def on_compose(self) -> None:
        # Empieza invisible; on_mount lo revela
        self.styles.opacity = 0.0


# -- Mensaje del usuario -------------------------------------------------------

class UserMessage(_BaseCard):
    """Línea de entrada del usuario con timestamp y separador visual."""

    DEFAULT_CSS = "UserMessage { height: 2; margin: 1 2 0 2; }"

    def __init__(self, text: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._text = text
        self._ts   = _ts()

    def render(self) -> Text:
        t = Text(overflow="fold")
        t.append(f" {self._ts} ", style=f"dim {_DIM}")
        t.append(" ▶ ", style=f"bold {_BLUE}")
        t.append(self._text, style=_TEXT)
        return t


# -- Línea de thinking ---------------------------------------------------------

class ThinkingLine(_BaseCard):
    """Una fase 'pensando' con spinner braille animado. .freeze() la congela."""

    DEFAULT_CSS = "ThinkingLine { height: 1; margin: 0 3 0 3; }"

    def __init__(self, text: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._text   = text
        self._frame  = 0
        self._frozen = False
        self._timer  = None

    def on_mount(self) -> None:
        super().on_mount()
        self._timer = self.set_interval(0.08, self._tick)

    def _tick(self) -> None:
        self._frame = (self._frame + 1) % 8
        self.refresh()

    def freeze(self) -> None:
        if self._timer:
            self._timer.stop()
            self._timer = None
        self._frozen = True
        self.refresh()

    def render(self) -> Text:
        t = Text(overflow="ellipsis", no_wrap=True)
        if self._frozen:
            t.append("  · ", style=f"dim {_DIM}")
            t.append(self._text, style=f"dim {_MUTED}")
        else:
            t.append(f"  {_SP[self._frame]} ", style=f"bold {_BLUE}")
            t.append(self._text, style=f"italic {_MUTED}")
        return t


# -- Card de herramienta -------------------------------------------------------

class ToolCard(_BaseCard):
    """Panel animado con estado de la herramienta: activa → completada/fallida.

    Muestra: icono, nombre, detalle, tiempo transcurrido al completar.

    Ejemplo::
        card = ToolCard("filesystem.read", "main.py")
        # ... tras completar:
        card.complete("342 líneas")
    """

    DEFAULT_CSS = "ToolCard { height: auto; margin: 0 2 1 2; }"

    def __init__(self, tool_name: str, detail: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self.tool_name  = tool_name
        self._detail    = _shorten_path(detail)
        self._status    = "active"
        self._frame     = 0
        self._timer     = None
        self._started   = time.monotonic()

    def on_mount(self) -> None:
        super().on_mount()
        self._timer = self.set_interval(0.08, self._tick)

    def _tick(self) -> None:
        if self._status == "active":
            self._frame = (self._frame + 1) % 8
            self.refresh()

    def complete(self, detail: str = "") -> None:
        if self._timer:
            self._timer.stop()
            self._timer = None
        elapsed = (time.monotonic() - self._started) * 1000
        raw = _shorten_path(detail) if detail else self._detail
        self._detail = f"{raw}  ·  {_fmt_elapsed(elapsed)}" if raw else _fmt_elapsed(elapsed)
        self._status = "completed"
        self.refresh()

    def fail(self, detail: str = "") -> None:
        if self._timer:
            self._timer.stop()
            self._timer = None
        self._detail = _shorten_path(detail) if detail else self._detail
        self._status = "failed"
        self.refresh()

    def render(self) -> Panel:
        icon = _tool_icon(self.tool_name)
        body = Text()

        if self._status == "active":
            body.append(f" {_SP[self._frame]} ", style=f"bold {_BLUE}")
            body.append(icon, style=f"dim {_BLUE}")
            body.append(self._detail or "ejecutando…", style=f"dim {_MUTED}")
            border, title_style = "#0f1e30", f"dim {_BLUE}"

        elif self._status == "completed":
            body.append(" ✓ ", style=f"bold {_GREEN}")
            body.append(icon, style=f"dim {_GREEN}")
            body.append(self._detail or "completado", style=_GREEN)
            border, title_style = "#0a1f12", f"dim {_GREEN}"

        else:
            body.append(" ✗ ", style=f"bold {_RED}")
            body.append(icon, style=f"dim {_RED}")
            body.append(self._detail or "error", style=_RED)
            border, title_style = "#1f0a0a", f"dim {_RED}"

        title = Text()
        title.append(self.tool_name, style=title_style)

        return Panel(
            body, title=title, title_align="left",
            border_style=border, padding=(0, 0), expand=True,
        )


# -- Card de subagente/skill ---------------------------------------------------

class SubagentCard(_BaseCard):
    """Panel con pasos del subagente o skill invocado, animado mientras activo.

    Ejemplo::
        card = SubagentCard("debugger")
        card.add_step("analizando stack trace…")
        card.add_step("filesystem.read  ✓", "completed")
        card.complete("bug encontrado en línea 45")
    """

    DEFAULT_CSS = "SubagentCard { height: auto; margin: 0 2 1 2; }"

    def __init__(self, agent_name: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.agent_name = agent_name
        self._steps: list[tuple[str, str]] = []
        self._done  = False
        self._frame = 0
        self._timer = None

    def on_mount(self) -> None:
        super().on_mount()
        self._timer = self.set_interval(0.08, self._tick)

    def _tick(self) -> None:
        if not self._done:
            self._frame = (self._frame + 1) % 8
            self.refresh()

    def add_step(self, text: str, status: str = "active") -> None:
        self._steps.append((text, status))
        self.refresh()

    def complete(self, summary: str = "") -> None:
        if self._timer:
            self._timer.stop()
            self._timer = None
        self._done = True
        if summary:
            self._steps.append((summary, "completed"))
        self.refresh()

    def render(self) -> Panel:
        content = Text()
        _icons  = {"active": _SP[self._frame], "completed": "✓", "failed": "✗", "pending": "·"}
        _colors = {"active": _PURPLE, "completed": _GREEN, "failed": _RED, "pending": _DIM}

        for step_text, step_status in self._steps:
            icon  = _icons.get(step_status, "·")
            color = _colors.get(step_status, _DIM)
            content.append(f"  {icon} ", style=f"bold {color}")
            content.append(step_text + "\n", style="#aab0cc")

        if not content._spans and not content._text:
            content.append("  iniciando…", style=f"italic {_MUTED}")

        done_icon  = "✓ " if self._done else f"{_SP[self._frame]} "
        done_style = f"{_GREEN}" if self._done else f"{_PURPLE}"

        title = Text()
        title.append(done_icon, style=done_style)
        title.append("AGENTE ", style=f"dim {_PURPLE}")
        title.append(self.agent_name, style=f"bold {_PURPLE}")

        return Panel(
            content, title=title, title_align="left",
            border_style="#2a1040" if not self._done else "#141028",
            padding=(0, 1), expand=True,
        )


# -- Respuesta de JARVIS -------------------------------------------------------

class JARVISCard(_BaseCard):
    """Respuesta completa de JARVIS renderizada en Markdown dentro de un Panel.

    Ejemplo::
        card = JARVISCard("He encontrado el problema en la línea 45…")
    """

    DEFAULT_CSS = "JARVISCard { height: auto; margin: 0 1 2 1; }"

    def __init__(self, text: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self._text = text
        self._ts   = _ts()

    def on_mount(self) -> None:
        self.styles.opacity = 0.0
        self.animate("opacity", value=1.0, duration=0.38, easing="out_cubic")

    def render(self) -> Panel:
        try:
            content = Markdown(self._text, code_theme="one-dark")
        except Exception:
            content = Text(self._text, style=_TEXT)

        title = Text()
        title.append("◈ JARVIS", style=f"bold {_BLUE}")
        title.append(f"  {self._ts}", style=f"dim {_DIM}")

        return Panel(
            content, title=title, title_align="left",
            border_style="#142030",
            padding=(1, 2), expand=True,
        )


# -- Card de confirmación ------------------------------------------------------

class ConfirmCard(_BaseCard):
    """Panel de confirmación con borde ámbar (destructivo) o azul (normal).

    Ejemplo::
        card = ConfirmCard("Eliminar 45 archivos", "rm -rf /tmp/*", is_destructive=True)
    """

    DEFAULT_CSS = "ConfirmCard { height: auto; margin: 1 2 1 2; }"

    def __init__(
        self,
        description: str,
        command: str | None,
        is_destructive: bool,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._desc        = description
        self._cmd         = command
        self._destructive = is_destructive

    def render(self) -> Panel:
        color = _AMBER if self._destructive else _BLUE
        icon  = "⚠  " if self._destructive else "?  "

        content = Text()
        content.append(icon, style=f"bold {color}")
        content.append(self._desc + "\n", style=_TEXT)

        if self._cmd:
            content.append(f"\n  $ {self._cmd}\n", style=f"bold {color}")

        content.append("\n  Enter confirmar  ·  Esc cancelar",
                       style=f"dim {_MUTED} italic")

        title = Text()
        title.append("CONFIRMAR", style=f"bold {color}")
        if self._destructive:
            title.append(" ACCIÓN DESTRUCTIVA", style=f"bold {color}")

        return Panel(
            content, title=title, title_align="left",
            border_style=color, padding=(1, 2),
        )


# -- Línea de sistema ----------------------------------------------------------

class SystemLine(_BaseCard):
    """Separador semántico con Rule y nivel de alerta."""

    DEFAULT_CSS = "SystemLine { height: 1; margin: 0 2 0 2; }"

    _TEXT_COLORS = {
        "info":    "#2a3d50",
        "success": _GREEN,
        "warning": _AMBER,
        "error":   _RED,
    }

    def __init__(self, text: str, level: str = "info", **kwargs) -> None:
        super().__init__(**kwargs)
        self._text  = text
        self._level = level

    def on_compose(self) -> None:
        pass  # No fade para líneas de sistema (demasiado frecuentes)

    def on_mount(self) -> None:
        pass  # Override: sin animación

    def render(self) -> Rule:
        style = self._TEXT_COLORS.get(self._level, "#2a3d50")
        return Rule(self._text, style=style, characters="─")
