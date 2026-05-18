"""Memoria de corto plazo para la conversación activa."""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from config import settings
from models._common import estimar_tokens
from models.base import Mensaje as ModelMensaje


class Message(BaseModel):
    """Mensaje almacenado en la memoria de corto plazo.

    Ejemplo:
        >>> Message(role="user", content="Hola")
    """

    id: str = Field(default_factory=lambda: uuid4().hex)
    role: Literal["user", "assistant", "system", "tool"]
    content: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    tokens_estimate: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ShortTermMemory:
    """Buffer de mensajes recientes con compresión automática y ventana de contexto."""

    def __init__(
        self,
        max_messages: int = settings.short_term_max_messages,
        max_tokens: int = settings.short_term_max_tokens,
        summarizer: Any | None = None,
    ) -> None:
        self._buffer: deque[Message] = deque()
        self._max_messages = max_messages
        self._max_tokens = max_tokens
        self._summarizer = summarizer
        self._lock = asyncio.Lock()

    async def add_message(self, message: Message) -> None:
        """Añade un mensaje y comprime la memoria si se exceden los límites."""
        if message.tokens_estimate <= 0:
            message.tokens_estimate = estimar_tokens(message.content)

        async with self._lock:
            self._buffer.append(message)
            await self._ensure_capacity()

    async def get_messages(
        self,
        limit: int | None = None,
        role_filter: list[Literal["user", "assistant", "system", "tool"]] | None = None,
    ) -> list[Message]:
        """Devuelve mensajes recientes opcionalmente filtrados por rol."""
        mensajes = list(self._buffer)
        if role_filter is not None:
            mensajes = [m for m in mensajes if m.role in role_filter]
        if limit is not None:
            return mensajes[-limit:]
        return mensajes

    async def get_context_window(self, max_tokens: int) -> list[Message]:
        """Devuelve los mensajes más recientes que caben en el presupuesto de tokens."""
        mensajes: list[Message] = []
        total = 0
        for mensaje in reversed(self._buffer):
            if total + mensaje.tokens_estimate > max_tokens:
                break
            mensajes.append(mensaje)
            total += mensaje.tokens_estimate
        return list(reversed(mensajes))

    async def clear(self) -> None:
        """Vacía la memoria de corto plazo."""
        async with self._lock:
            self._buffer.clear()

    async def summarize(self, messages: list[Message]) -> str:
        """Resume una lista de mensajes antiguos usando un modelo o heurística."""
        if self._summarizer is None:
            return self._naive_summary(messages)

        prompt = (
            "Resume brevemente los siguientes mensajes antiguos de la conversación, "
            "manteniendo solo los hechos más importantes y las decisiones tomadas."
        )
        mensaje_sistema = ModelMensaje(rol="system", contenido=prompt)
        mensajes_modelo = [
            mensaje_sistema,
            *[ModelMensaje(rol=m.role, contenido=m.content) for m in messages],
        ]
        respuesta = await self._summarizer.complete(
            mensajes_modelo,
            temperatura=0.2,
            max_tokens=256,
        )
        return respuesta.content.strip()

    async def get_last_n(self, n: int) -> list[Message]:
        """Devuelve los últimos `n` mensajes de la memoria."""
        return list(self._buffer)[-n:]

    async def search(self, query: str) -> list[Message]:
        """Busca mensajes que contengan el término indicado."""
        lower = query.lower()
        return [
            m for m in self._buffer
            if lower in m.content.lower() or any(lower in str(v).lower() for v in m.metadata.values())
        ]

    async def to_langchain_messages(self) -> list[object]:
        """Convierte los mensajes a objetos `langchain.schema.BaseMessage`."""
        try:
            from langchain.schema import BaseMessage, HumanMessage, AIMessage, SystemMessage, ChatMessage
        except ImportError as exc:
            raise ImportError(
                "LangChain no está instalado. Instala langchain para usar esta función."
            ) from exc

        resultado: list[BaseMessage] = []
        for mensaje in self._buffer:
            if mensaje.role == "user":
                resultado.append(HumanMessage(content=mensaje.content))
            elif mensaje.role == "assistant":
                resultado.append(AIMessage(content=mensaje.content))
            elif mensaje.role == "system":
                resultado.append(SystemMessage(content=mensaje.content))
            else:
                resultado.append(ChatMessage(role=mensaje.role, content=mensaje.content))
        return resultado

    def __len__(self) -> int:
        return len(self._buffer)

    async def _ensure_capacity(self) -> None:
        """Comprime mensajes antiguos hasta respetar límites configurados.

        Returns:
            None.
        """
        if len(self._buffer) <= self._max_messages and self._total_tokens() <= self._max_tokens:
            return

        while len(self._buffer) > self._max_messages or self._total_tokens() > self._max_tokens:
            if len(self._buffer) <= 1:
                break
            mitad = max(1, len(self._buffer) // 2)
            antiguos = [self._buffer.popleft() for _ in range(mitad)]
            resumen = await self.summarize(antiguos)
            resumen_mensaje = Message(
                role="system",
                content=f"Resumen de memoria: {resumen}",
                tokens_estimate=estimar_tokens(resumen),
                metadata={"resumen": True},
            )
            self._buffer.appendleft(resumen_mensaje)

    def _total_tokens(self) -> int:
        """Calcula los tokens estimados actualmente en el buffer.

        Returns:
            Suma de `tokens_estimate` de todos los mensajes.
        """
        return sum(m.tokens_estimate for m in self._buffer)

    @staticmethod
    def _naive_summary(messages: list[Message]) -> str:
        """Crea un resumen heurístico sin llamar a un modelo.

        Args:
            messages: Mensajes antiguos que se deben comprimir.

        Returns:
            Texto breve con el contenido concatenado y recortado.
        """
        textos = [m.content for m in messages if m.content]
        if not textos:
            return ""
        texto = " ".join(textos)
        return texto[:400] + ("..." if len(texto) > 400 else "")


MemoriaCortoPlazo = ShortTermMemory
