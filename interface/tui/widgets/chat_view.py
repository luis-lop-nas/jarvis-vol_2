"""Contenedor del chat. Monta cards animadas por cada evento del agente."""
from __future__ import annotations

from textual.containers import ScrollableContainer
from textual.widget import Widget

from .cards import (
    ConfirmCard,
    JARVISCard,
    SubagentCard,
    SystemLine,
    ThinkingLine,
    ToolCard,
    UserMessage,
)

# Prefijos de herramientas que se muestran como SubagentCard
_AGENT_PREFIXES = ("agente.", "subagente.", "agent.", "delegado.", "debugger", "architect")


def _is_agent_tool(name: str) -> bool:
    lower = name.lower()
    return any(lower.startswith(p) or lower == p for p in _AGENT_PREFIXES)


class ChatView(ScrollableContainer):
    """Chat scrollable. Cada evento es un Widget independiente con animación propia.

    API::
        chat.add_user("analiza este archivo")
        chat.add_thinking("leyendo el contexto…")
        chat.add_tool("filesystem.read", "active", "main.py")
        chat.add_tool("filesystem.read", "completed", "342 líneas · 23ms")
        chat.add_jarvis("He encontrado el problema…")
        chat.add_confirmation("Eliminar archivos", "rm -rf /tmp", True)
        chat.add_system("conectado", "success")
    """

    DEFAULT_CSS = """
    ChatView {
        height: 1fr;
        background: #0d0d10;
        padding: 1 0;
        scrollbar-color: #1e2433 #0d0d10;
        scrollbar-size: 1 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._active_thinking: ThinkingLine | None = None
        self._active_tool: ToolCard | None = None
        self._active_agent: SubagentCard | None = None

    # -- API pública -----------------------------------------------------------

    def add_user(self, text: str) -> None:
        self._freeze_all()
        self._mount(UserMessage(text))

    def add_thinking(self, text: str) -> None:
        if self._active_thinking:
            self._active_thinking.freeze()
        card = ThinkingLine(text)
        self._active_thinking = card
        self._mount(card)

    def add_tool(self, name: str, status: str, detail: str = "") -> None:
        if _is_agent_tool(name):
            self._handle_agent(name, status, detail)
            return

        if status == "active":
            self._freeze_thinking()
            if self._active_tool:
                self._active_tool.complete()
            card = ToolCard(name, detail)
            self._active_tool = card
            self._mount(card)

        elif status == "completed":
            if self._active_tool and self._active_tool.tool_name == name:
                self._active_tool.complete(detail)
                self._active_tool = None

        elif status == "failed":
            if self._active_tool and self._active_tool.tool_name == name:
                self._active_tool.fail(detail)
                self._active_tool = None

    def add_jarvis(self, text: str) -> None:
        self._freeze_all()
        self._mount(JARVISCard(text))

    def add_confirmation(
        self, description: str, command: str | None, is_destructive: bool
    ) -> None:
        self._freeze_thinking()
        self._mount(ConfirmCard(description, command, is_destructive))

    def add_system(self, text: str, level: str = "info") -> None:
        self._mount(SystemLine(text, level))

    def add_error(self, message: str) -> None:
        self._freeze_all()
        self._mount(SystemLine(f"✗  {message}", "error"))

    # -- Privado ---------------------------------------------------------------

    def _handle_agent(self, name: str, status: str, detail: str) -> None:
        if status == "active":
            self._freeze_thinking()
            card = SubagentCard(name)
            if detail:
                card.add_step(detail, "active")
            self._active_agent = card
            self._mount(card)

        elif self._active_agent:
            if status == "completed":
                if detail:
                    self._active_agent.add_step(detail, "completed")
                self._active_agent.complete()
                self._active_agent = None
            elif status == "failed":
                if detail:
                    self._active_agent.add_step(detail, "failed")
                self._active_agent.complete()
                self._active_agent = None
            else:
                self._active_agent.add_step(detail or name, status)

    def _freeze_thinking(self) -> None:
        if self._active_thinking:
            self._active_thinking.freeze()
            self._active_thinking = None

    def _freeze_all(self) -> None:
        self._freeze_thinking()
        if self._active_tool:
            self._active_tool.complete()
            self._active_tool = None
        if self._active_agent:
            self._active_agent.complete()
            self._active_agent = None

    async def clear(self) -> None:
        self._active_thinking = None
        self._active_tool = None
        self._active_agent = None
        await self.remove_children()

    def _mount(self, widget: Widget) -> None:
        self.mount(widget)
        self.call_after_refresh(lambda: self.scroll_end(animate=False))
