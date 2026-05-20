"""Barra de input: historial ↑↓, modo confirmación, hints contextuales."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Input, Label


class MessageSubmitted(Message):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.text = text


class ConfirmationResponse(Message):
    def __init__(self, confirmed: bool) -> None:
        super().__init__()
        self.confirmed = confirmed


class InputBar(Widget):
    """Input con historial de comandos ↑↓ y modo de confirmación de acciones.

    Ejemplo::
        # Escuchar InputBar.MessageSubmitted para texto normal
        # Escuchar InputBar.ConfirmationResponse para confirmaciones
    """

    DEFAULT_CSS = """
    InputBar {
        height: 3;
        background: #0d0d10;
        border-top: solid #1a1a28;
        padding: 0 2;
        layout: vertical;
    }
    InputBar Input {
        background: #0d0d10;
        border: none;
        color: #e8e8f0;
        height: 2;
        padding: 0 0;
    }
    InputBar Input:focus {
        border: none;
        background: #0d0d10;
    }
    InputBar #hints {
        height: 1;
        color: #1e2433;
        padding: 0 0;
    }
    InputBar #hints.confirm {
        color: #5a4010;
    }
    """

    waiting_confirmation: reactive[bool] = reactive(False)

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._history: list[str] = []
        self._idx: int = -1
        self._draft: str = ""

    def compose(self) -> ComposeResult:
        yield Input(placeholder="▶  Escribe un mensaje…", id="msg-input")
        yield Label(self._hint(), id="hints")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def watch_waiting_confirmation(self, value: bool) -> None:
        label  = self.query_one("#hints", Label)
        input_ = self.query_one(Input)
        if value:
            label.update("Enter confirmar  ·  Esc cancelar")
            label.add_class("confirm")
            input_.placeholder = "▶  Confirmar: Enter = sí  /  Esc = no"
        else:
            label.update(self._hint())
            label.remove_class("confirm")
            input_.placeholder = "▶  Escribe un mensaje…"

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return

        if self.waiting_confirmation:
            confirmed = text.lower() in {"s", "si", "sí", "y", "yes", "ok"}
            self.post_message(ConfirmationResponse(confirmed))
            event.input.clear()
            return

        self._history.insert(0, text)
        if len(self._history) > 200:
            self._history.pop()
        self._idx  = -1
        self._draft = ""
        self.post_message(MessageSubmitted(text))
        event.input.clear()

    def on_key(self, event) -> None:
        if self.waiting_confirmation and event.key == "escape":
            self.post_message(ConfirmationResponse(False))
            event.prevent_default()
            return

        input_ = self.query_one(Input)

        if event.key == "up":
            if not self._history:
                return
            if self._idx == -1:
                self._draft = input_.value
            self._idx = min(self._idx + 1, len(self._history) - 1)
            input_.value = self._history[self._idx]
            input_.cursor_position = len(input_.value)
            event.prevent_default()

        elif event.key == "down":
            if self._idx == -1:
                return
            self._idx -= 1
            input_.value = self._history[self._idx] if self._idx >= 0 else self._draft
            input_.cursor_position = len(input_.value)
            event.prevent_default()

    @staticmethod
    def _hint() -> str:
        return "↑↓ historial  ·  Ctrl+K limpiar  ·  ` alternar modo  ·  Ctrl+C salir"
