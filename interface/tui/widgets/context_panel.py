"""Panel de contexto de la app activa. Se adapta según la app en foco."""
from __future__ import annotations

from rich.text import Text
from textual.reactive import reactive
from textual.widget import Widget

from ..context_watcher import AppContext

# Sugerencias contextuales por tipo de app
_CONTEXT_HINTS: dict[str, str] = {
    "code":    "refactorizar · explicar · añadir tests",
    "xcode":   "revisar build · explicar error · añadir tests",
    "safari":  "resumir página · buscar · extraer datos",
    "chrome":  "resumir página · buscar · extraer datos",
    "finder":  "organizar · buscar · renombrar en lote",
    "terminal":"explicar error · sugerir comando · depurar",
    "notes":   "resumir · mejorar redacción · exportar",
    "slack":   "redactar respuesta · resumir hilo",
    "spotify": "info del artista · crear playlist",
}


def _hint_for(app_name: str) -> str:
    lower = app_name.lower()
    for key, hint in _CONTEXT_HINTS.items():
        if key in lower:
            return hint
    return "preguntar · ejecutar tarea · recordar"


class ContextPanel(Widget):
    """Muestra la app activa y sugerencias contextuales adaptadas."""

    DEFAULT_CSS = """
    ContextPanel {
        height: 2;
        background: #0f0f11;
        border-bottom: solid #1a1a22;
        padding: 0 2;
        content-align: left middle;
    }
    """

    context: reactive[AppContext] = reactive(AppContext())

    def render(self) -> Text:
        ctx = self.context
        t = Text(overflow="ellipsis", no_wrap=True)

        if ctx.is_empty:
            t.append("sin contexto  ", style="#333355 italic")
            t.append("abre una app para que JARVIS la detecte", style="#333355")
            return t

        t.append(ctx.icon, style="")
        t.append(ctx.app_name, style="bold #ccccee")

        if ctx.window_title:
            t.append(f"  ·  {ctx.short_title}", style="#445566")

        hint = _hint_for(ctx.app_name)
        t.append(f"  —  {hint}", style="#2a3a4a italic")

        return t
