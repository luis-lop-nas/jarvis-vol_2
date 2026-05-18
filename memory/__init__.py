"""Memoria multinivel: corto plazo, largo plazo, episódica, procedural y vault."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from config import settings
from memory.episodic import EpisodicMemory, Episode
from memory.long_term import LongTermMemory, MemoryEntry
from memory.procedural import ProceduralMemory, Workflow
from memory.short_term import Message, ShortTermMemory
from memory.vault import Vault

log = logging.getLogger(__name__)

__all__ = [
    "ShortTermMemory",
    "EpisodicMemory",
    "LongTermMemory",
    "ProceduralMemory",
    "Vault",
    "MemorySystem",
    "Episode",
    "Workflow",
    "MemoryEntry",
    "Message",
]


class MemorySystem:
    """Coordinador único de la memoria de JARVIS."""

    def __init__(
        self,
        short_term: ShortTermMemory | None = None,
        long_term: LongTermMemory | None = None,
        episodic: EpisodicMemory | None = None,
        procedural: ProceduralMemory | None = None,
        vault: Vault | None = None,
        summarizer: Any | None = None,
    ) -> None:
        self._short_term = short_term or ShortTermMemory(
            max_messages=settings.short_term_max_messages,
            max_tokens=settings.short_term_max_tokens,
            summarizer=summarizer,
        )
        self._long_term = long_term or LongTermMemory(collection_name=settings.chroma_collection)
        self._episodic = episodic or EpisodicMemory(store=self._long_term, summarizer=summarizer)
        self._procedural = procedural or ProceduralMemory(store=self._long_term, summarizer=summarizer)
        self._vault = vault or Vault()

    async def store_interaction(
        self,
        user_msg: str | Message,
        assistant_msg: str | Message,
    ) -> None:
        """Guarda la interacción en corto plazo y, si es relevante, en largo plazo."""
        usuario = self._to_message(user_msg, "user")
        asistente = self._to_message(assistant_msg, "assistant")

        await self._short_term.add_message(usuario)
        await self._short_term.add_message(asistente)

        importancia = self._estimate_importance(usuario, asistente)
        if importancia >= settings.memory_importance_threshold:
            entry = MemoryEntry(
                content=asistente.content,
                summary=asistente.content[:256],
                category="conversacion",
                source="conversacion",
                importance=importancia,
                metadata={
                    "user_message": usuario.content,
                    "assistant_message": asistente.content,
                },
            )
            try:
                await self._long_term.store(entry)
                log.info("Interacción importante guardada en memoria: %.2f", importancia)
            except Exception as exc:
                log.warning("No se pudo persistir interacción en memoria: %s", exc)

    async def get_context(self, task: str, max_tokens: int) -> str:
        """Construye el contexto completo que se inyectará en el prompt."""
        recientes = await self._short_term.get_context_window(max_tokens)
        conversacion = "\n".join(
            f"{m.role}: {m.content}" for m in recientes
        )
        try:
            memorias = await self._long_term.build_context(task)
        except Exception as exc:
            log.debug("Contexto de largo plazo no disponible: %s", exc)
            memorias = ""
        try:
            workflow = await self._procedural.find_workflow(task)
        except Exception as exc:
            log.debug("Workflow no disponible para contexto: %s", exc)
            workflow = None
        partes = ["Contexto reciente:", conversacion] if conversacion else []
        if memorias:
            partes.extend(["", memorias])
        if workflow:
            partes.extend([
                "", f"Workflow aplicable: {workflow.name}",
                f"Descripción: {workflow.description}",
                f"Patrones: {', '.join(workflow.trigger_patterns)}",
            ])
        return "\n".join(partes).strip()

    async def record_episode(self, episode: Episode) -> str:
        """Registra un episodio y dispara el aprendizaje procedural."""
        ident = await self._episodic.record(episode)
        try:
            await self._procedural.learn_from_episode(episode)
        except Exception as exc:
            log.warning("No se pudo aprender workflow desde episodio: %s", exc)
        log.info("Episodio registrado en memoria: %s", ident)
        return ident

    async def find_workflow(self, task: str) -> Workflow | None:
        """Busca un workflow pertinente antes de planificar."""
        try:
            return await self._procedural.find_workflow(task)
        except Exception as exc:
            log.debug("Memoria procedural no disponible: %s", exc)
            return None

    async def get_secret(self, service: str) -> str | None:
        """Recupera un secreto de 1Password usando el servicio indicado."""
        secret = await self._vault.get_api_key(service)
        if secret:
            return secret
        return await self._vault.get_password(service)

    async def clear_session(self) -> None:
        """Limpia la memoria de corto plazo al finalizar una sesión."""
        await self._short_term.clear()

    async def health_check(self) -> dict[str, Any]:
        """Verifica la salud de todos los backends de memoria."""
        chroma, vault = await asyncio.gather(
            self._long_term.health_check(),
            self._vault.is_available(),
            return_exceptions=True,
        )
        return {
            "chroma": bool(chroma) if not isinstance(chroma, Exception) else False,
            "ollama_embeddings": bool(chroma) if not isinstance(chroma, Exception) else False,
            "vault_available": bool(vault) if not isinstance(vault, Exception) else False,
        }

    def _to_message(self, value: str | Message, role: str) -> Message:
        """Normaliza cadenas o mensajes existentes a `Message`.

        Args:
            value: Texto crudo o mensaje Pydantic.
            role: Rol que se asignará al texto crudo.

        Returns:
            Mensaje normalizado para corto plazo.
        """
        if isinstance(value, Message):
            return value
        return Message(role=role, content=value)

    def _estimate_importance(self, user: Message, assistant: Message) -> float:
        """Calcula una importancia heurística para decidir persistencia.

        Args:
            user: Mensaje del usuario.
            assistant: Respuesta del asistente.

        Returns:
            Puntuación entre 0.0 y 1.0.
        """
        score = min(1.0, max(0.0, len(assistant.content) / 500.0))
        if "importante" in user.content.lower() or "urgente" in user.content.lower():
            score = min(1.0, score + 0.2)
        if len(user.content.split()) > 25:
            score = min(1.0, score + 0.1)
        return score
