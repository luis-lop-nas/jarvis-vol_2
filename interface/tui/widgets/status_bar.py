"""Barra inferior de estado: modelo, sesión, tokens, coste."""
from __future__ import annotations

from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget


class StatusBar(Widget):
    """Strip inferior con métricas de la sesión activa.

    Muestra: dot conexión · modelo · sesión · tokens · coste USD · tiempo activo.
    """

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        background: #08080b;
        border-top: solid #12121a;
        padding: 0 2;
        content-align: left middle;
    }
    """

    connected:  reactive[bool]  = reactive(False)
    model:      reactive[str]   = reactive("")
    session_id: reactive[str]   = reactive("")
    tokens:     reactive[int]   = reactive(0)
    cost_usd:   reactive[float] = reactive(0.0)

    def render(self) -> Text:
        t = Text(overflow="ellipsis", no_wrap=True)

        # Dot
        if self.connected:
            t.append("◉ ", style="#2a5a3a")
        else:
            t.append("○ ", style="#2a2a35")

        # Modelo
        if self.model:
            t.append(self.model, style="#2a4a5a")
            t.append("  ·  ", style="#161622")

        # Sesión
        if self.session_id:
            t.append(f"#{self.session_id[:8]}", style="#222235")
            t.append("  ·  ", style="#161622")

        # Tokens
        if self.tokens > 0:
            t.append(f"{self.tokens:,} tok", style="#222235")
            if self.cost_usd > 0:
                t.append("  ·  ", style="#161622")

        # Coste
        if self.cost_usd > 0:
            t.append(f"${self.cost_usd:.4f}", style="#2a2a35")

        return t
