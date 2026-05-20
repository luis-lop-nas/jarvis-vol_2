"""TUI de JARVIS — panel adaptativo tipo overlay.

Estados:
  CORNER → esquina 200×35px  (idle / notificación silenciosa)
  STRIP  → franja 250px      (herramientas en ejecución)
  FULL   → panel 560px       (conversación activa / confirmación)

El modo cambia automáticamente según los mensajes del backend.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import uuid4

from rich.panel import Panel
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widget import Widget
from textual.binding import Binding
from textual.message import Message
from textual.reactive import reactive

from .context_watcher import AppContext, ContextWatcher
from .widgets import (
    ChatView,
    ConfirmationResponse,
    ContextPanel,
    HeaderBar,
    InputBar,
    MessageSubmitted,
    StatusBar,
)
from .window_manager import DisplayMode, TerminalWindowManager, mode_for_state
from .ws_client import TUIWebSocketClient

log = logging.getLogger(__name__)

# -- Mensajes internos --------------------------------------------------------

class _WSUpdate(Message):
    def __init__(self, data: dict[str, Any]) -> None:
        super().__init__(); self.data = data

class _WSStatus(Message):
    def __init__(self, connected: bool) -> None:
        super().__init__(); self.connected = connected

class _CtxChanged(Message):
    def __init__(self, ctx: AppContext) -> None:
        super().__init__(); self.ctx = ctx

# -----------------------------------------------------------------------------


class JARVISTui(App):
    """TUI adaptativo de JARVIS. Cambia tamaño y layout según el estado del agente."""

    CSS = """
    Screen {
        layout: vertical;
        background: #0d0d10;
    }
    Screen.corner #context { display: none; }
    Screen.corner #chat    { display: none; }
    Screen.corner #input   { display: none; }
    Screen.corner #status  { display: none; }
    Screen.strip  #context { display: none; }
    Screen.strip  #input   { display: none; }
    """

    BINDINGS = [
        Binding("ctrl+c",     "quit",           "Salir",      show=False),
        Binding("ctrl+k",     "action_clear",   "Limpiar",    show=False),
        Binding("grave_accent","action_toggle",  "Alternar",   show=False),  # ` key
        Binding("ctrl+space", "action_toggle",  "Alternar",   show=False),
    ]

    TITLE = "JARVIS"

    _mode: reactive[DisplayMode] = reactive(DisplayMode.FULL)

    def __init__(
        self,
        api_url: str = "ws://127.0.0.1:8765/ws",
        context_interval: float = 2.0,
    ) -> None:
        super().__init__()
        self._session_id    = str(uuid4())
        self._ws            = TUIWebSocketClient(api_url, self._session_id)
        self._watcher       = ContextWatcher(interval=context_interval)
        self._win           = TerminalWindowManager()
        self._user_active   = False          # ¿el usuario ha enviado al menos un mensaje?
        self._pending_id: str | None = None
        self._current_tool: str | None = None
        self._collapse_task: asyncio.Task | None = None

    # -- Composición ----------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield HeaderBar(id="header")
        yield ContextPanel(id="context")
        yield ChatView(id="chat")
        yield InputBar(id="input")
        yield StatusBar(id="status")

    def on_mount(self) -> None:
        self.run_worker(self._ws_worker(),  exclusive=True,  name="ws")
        self.run_worker(self._ctx_worker(), exclusive=False, name="ctx")
        self.query_one("#status", StatusBar).session_id = self._session_id
        self.query_one("#chat", ChatView).mount(_WelcomeCard())

    # -- Workers --------------------------------------------------------------

    async def _ws_worker(self) -> None:
        async def on_msg(d: dict) -> None:
            self.post_message(_WSUpdate(d))
        async def on_st(c: bool) -> None:
            self.post_message(_WSStatus(c))
        await self._ws.run(on_message=on_msg, on_status=on_st)

    async def _ctx_worker(self) -> None:
        def on_change(ctx: AppContext) -> None:
            self.post_message(_CtxChanged(ctx))
        await self._watcher.watch(on_change)

    # -- Reactividad de modo --------------------------------------------------

    def watch__mode(self, mode: DisplayMode) -> None:
        # Clases CSS en el Screen según el modo
        screen = self.screen
        screen.remove_class("corner", "strip", "full")
        screen.add_class(mode.value)
        # Redimensionar ventana en background
        self.run_worker(self._win.resize(mode), exclusive=False, name="resize")

    def _set_mode(self, mode: DisplayMode) -> None:
        if self._mode != mode:
            self._mode = mode

    def _schedule_collapse(self, delay: float = 3.0) -> None:
        """Colapsa a CORNER tras `delay` segundos si el usuario no está activo."""
        if self._collapse_task and not self._collapse_task.done():
            self._collapse_task.cancel()

        async def _do() -> None:
            await asyncio.sleep(delay)
            if not self._user_active:
                self._set_mode(DisplayMode.CORNER)

        self._collapse_task = asyncio.ensure_future(_do())

    # -- Manejo de mensajes ---------------------------------------------------

    def on__ws_status(self, event: _WSStatus) -> None:
        header = self.query_one("#header", HeaderBar)
        status = self.query_one("#status", StatusBar)
        header.connected = event.connected
        status.connected = event.connected
        chat = self.query_one("#chat", ChatView)
        if event.connected:
            chat.add_system("conectado", "success")
            header.fase = "silent"
        else:
            chat.add_system("desconectado — reconectando…", "warning")
            header.fase = "init"
            self._set_mode(DisplayMode.CORNER)

    def on__ws_update(self, event: _WSUpdate) -> None:
        data  = event.data
        tipo  = data.get("type", "")
        msg   = data.get("message", "")
        step  = data.get("step") or {}
        state = data.get("state", "")

        header = self.query_one("#header", HeaderBar)
        chat   = self.query_one("#chat", ChatView)
        input_ = self.query_one("#input", InputBar)

        header.fase = tipo or state
        status = self.query_one("#status", StatusBar)
        if model := step.get("model") or step.get("modelo"):
            header.model = str(model)
            status.model = str(model)
        if tokens := step.get("tokens") or step.get("total_tokens"):
            status.tokens = int(tokens)
        if cost := step.get("cost_usd") or step.get("total_cost_usd"):
            status.cost_usd = float(cost)

        # Cancelar collapse si hay actividad
        if self._collapse_task and not self._collapse_task.done():
            self._collapse_task.cancel()

        target_mode = mode_for_state(state, tipo, self._user_active)
        self._set_mode(target_mode)

        if tipo == "thinking":
            chat.add_thinking(msg)

        elif tipo == "acting":
            tool  = str(step.get("herramienta") or step.get("tool") or "herramienta")
            tstatus = str(step.get("status", "active"))
            detail  = str(step.get("descripcion") or step.get("result") or "")
            chat.add_tool(tool, tstatus, detail)
            self._current_tool = tool

        elif tipo == "waiting":
            action_id   = str(step.get("id") or step.get("action_id") or uuid4())
            command     = step.get("herramienta") or step.get("command")
            destructive = bool(step.get("requiere_confirmacion") or step.get("is_destructive"))
            self._pending_id = action_id
            chat.add_confirmation(msg, str(command) if command else None, destructive)
            input_.waiting_confirmation = True

        elif tipo == "done":
            if self._current_tool:
                chat.add_tool(self._current_tool, "completed")
                self._current_tool = None
            chat.add_jarvis(msg)
            header.fase = "done"
            input_.waiting_confirmation = False
            self._pending_id = None
            if not self._user_active:
                self._schedule_collapse(3.0)

        elif tipo == "error":
            chat.add_error(msg)
            header.fase = "error"
            input_.waiting_confirmation = False
            self._pending_id = None
            self._schedule_collapse(5.0)

    def on__ctx_changed(self, event: _CtxChanged) -> None:
        self.query_one("#context", ContextPanel).context = event.ctx

    # -- Eventos de widgets ---------------------------------------------------

    def on_message_submitted(self, event: MessageSubmitted) -> None:
        self._user_active = True
        chat = self.query_one("#chat", ChatView)
        header = self.query_one("#header", HeaderBar)
        chat.add_user(event.text)
        header.fase = "thinking"
        self._set_mode(DisplayMode.FULL)
        self.run_worker(
            self._ws.send_message(event.text),
            exclusive=False, name="send",
        )

    def on_confirmation_response(self, event: ConfirmationResponse) -> None:
        action_id = self._pending_id or ""
        self._pending_id = None
        self.query_one("#input", InputBar).waiting_confirmation = False
        self.run_worker(
            self._ws.send_confirm(action_id, event.confirmed),
            exclusive=False, name="confirm",
        )
        chat = self.query_one("#chat", ChatView)
        chat.add_system("confirmado ✓" if event.confirmed else "cancelado",
                        "success" if event.confirmed else "warning")

    # -- Acciones de teclado --------------------------------------------------

    def action_clear(self) -> None:
        self._user_active = False

        async def _do() -> None:
            chat = self.query_one("#chat", ChatView)
            await chat.clear()
            chat.add_system("historial limpiado", "info")

        self.run_worker(_do(), exclusive=False, name="clear")

    def action_toggle(self) -> None:
        """Alterna entre CORNER y FULL con ` o Ctrl+Space."""
        if self._mode == DisplayMode.FULL:
            self._set_mode(DisplayMode.CORNER)
        else:
            self._set_mode(DisplayMode.FULL)


# ---------------------------------------------------------------------------
# Pantalla de bienvenida
# ---------------------------------------------------------------------------

class _WelcomeCard(Widget):
    DEFAULT_CSS = """
    _WelcomeCard { height: auto; margin: 1 2 2 2; }
    """

    _BANNER = (
        "  ┌─────────────────────────────┐\n"
        "  │                             │\n"
        "  │   ◈  J A R V I S           │\n"
        "  │                             │\n"
        "  └─────────────────────────────┘"
    )

    def on_mount(self) -> None:
        self.styles.opacity = 0.0
        self.styles.animate("opacity", value=1.0, duration=0.6)

    def render(self) -> Panel:
        content = Text(justify="center")
        content.append("\n◈  J A R V I S\n", style="bold #4d9fff")
        content.append("Listo para ayudarte", style=f"dim #334455")

        return Panel(
            content,
            border_style="#1a2535",
            padding=(1, 4),
            expand=True,
        )
