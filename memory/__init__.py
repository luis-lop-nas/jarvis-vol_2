"""Memoria multinivel: corto plazo, largo plazo, episódica, procedural y vault."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from pydantic import BaseModel

from config import settings
from memory.episodic import Episode, EpisodicMemory
from memory.long_term import COLECCION_WORKFLOWS, LongTermMemory, MemoryEntry
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
    "HealthStatus",
    "Episode",
    "Workflow",
    "MemoryEntry",
    "Message",
]


class HealthStatus(BaseModel):
    """Estado de salud detallado del sistema de memoria.

    Ejemplo::
        estado = await memory_system.health_check()
        print(estado.status, estado.details["latencia_query_ms"])
    """

    status: Literal["healthy", "degraded", "down"]
    details: dict[str, Any]


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
        if procedural is None:
            workflow_store = LongTermMemory(collection_name=COLECCION_WORKFLOWS)
            self._procedural = ProceduralMemory(store=workflow_store, summarizer=summarizer)
        else:
            self._procedural = procedural
        self._vault = vault or Vault()

    async def store_interaction(
        self,
        user_msg: str | Message,
        assistant_msg: str | Message,
    ) -> None:
        """Guarda la interacción en corto plazo y, si es relevante, en largo plazo.

        Ejemplo::
            await memory.store_interaction("pregunta", "respuesta")
        """
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
        """Construye el contexto completo que se inyectará en el prompt.

        Ejemplo::
            ctx = await memory.get_context("organiza archivos", max_tokens=2000)
        """
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
        """Registra un episodio y dispara el aprendizaje procedural.

        Ejemplo::
            ident = await memory.record_episode(episodio)
        """
        ident = await self._episodic.record(episode)
        try:
            await self._procedural.learn_from_episode(episode)
        except Exception as exc:
            log.warning("No se pudo aprender workflow desde episodio: %s", exc)
        log.info("Episodio registrado en memoria: %s", ident)
        return ident

    async def find_workflow(self, task: str) -> Workflow | None:
        """Busca un workflow pertinente antes de planificar.

        Ejemplo::
            wf = await memory.find_workflow("organiza archivos")
        """
        try:
            return await self._procedural.find_workflow(task)
        except Exception as exc:
            log.debug("Memoria procedural no disponible: %s", exc)
            return None

    async def store_memory(self, entry: MemoryEntry) -> str:
        """Guarda una entrada explícita en memoria de largo plazo.

        Ejemplo::
            ident = await memory.store_memory(entrada)

        Args:
            entry: Entrada Pydantic de memoria persistente.

        Returns:
            Identificador de la entrada guardada.
        """
        return await self._long_term.store(entry)

    async def search_memory(self, query: str, limit: int = 5) -> list[MemoryEntry]:
        """Busca en memoria de largo plazo con estrategia híbrida.

        Ejemplo::
            entradas = await memory.search_memory("correo reportes", limit=5)

        Args:
            query: Consulta del usuario o tarea actual.
            limit: Máximo de resultados.

        Returns:
            Entradas relevantes deduplicadas.
        """
        return await self._long_term.search_hybrid(query, limit=limit)

    async def get_secret(self, service: str) -> str | None:
        """Recupera un secreto de 1Password usando el servicio indicado.

        Ejemplo::
            clave = await memory.get_secret("Kimi")
        """
        secret = await self._vault.get_api_key(service)
        if secret:
            return secret
        return await self._vault.get_password(service)

    async def clear_session(self) -> None:
        """Limpia la memoria de corto plazo al finalizar una sesión.

        Ejemplo::
            await memory.clear_session()
        """
        await self._short_term.clear()

    async def get_agent_instructions(self) -> list[str]:
        """Devuelve las instrucciones aprendidas activas del agente.

        Ejemplo::
            instrucciones = await memory.get_agent_instructions()

        Returns:
            Lista de instrucciones (máx. 10) ordenadas por recencia.
        """
        return await self._procedural.get_agent_instructions()

    async def update_agent_instructions(
        self,
        feedback: str,
        confirm_callback: Callable[[str], Awaitable[bool]] | None = None,
    ) -> bool:
        """Añade o actualiza una instrucción aprendida para el system prompt.

        Ejemplo::
            ok = await memory.update_agent_instructions("Responder siempre en español")

        Args:
            feedback: Texto de la instrucción aprendida.
            confirm_callback: Función async de confirmación del usuario.

        Returns:
            ``True`` si la instrucción fue guardada.
        """
        return await self._procedural.update_agent_instructions(
            feedback, confirm_callback=confirm_callback
        )

    async def health_check(self) -> HealthStatus:
        """Verifica la salud del sistema de memoria con métricas detalladas.

        Comprueba conectividad ChromaDB, latencia de query, entradas totales,
        entradas expiradas y disponibilidad del vault.

        Ejemplo::
            estado = await memory.health_check()
            print(estado.status)  # "healthy" | "degraded" | "down"

        Returns:
            ``HealthStatus`` con estado global y detalles por componente.
        """
        chroma_ok = False
        vault_ok = False
        total_entradas = 0
        expiradas = 0
        latencia_ms = 0.0

        try:
            chroma_ok, vault_ok = await asyncio.gather(
                self._long_term.health_check(),
                self._vault.is_available(),
                return_exceptions=False,
            )
        except Exception as exc:
            log.debug("Error en health_check gather: %s", exc)
            chroma_ok = False
            vault_ok = False

        if chroma_ok:
            try:
                t0 = time.monotonic()
                # Query de prueba: embed + search para medir latencia real
                await self._long_term.search("health check probe", limit=1)
                latencia_ms = round((time.monotonic() - t0) * 1000, 1)
            except Exception:
                latencia_ms = -1.0

            try:
                total_entradas = await self._long_term.count()
            except Exception:
                pass

            try:
                expiradas = await self._long_term.count_expired()
            except Exception:
                pass

        if not chroma_ok:
            estado_global: Literal["healthy", "degraded", "down"] = "down"
        elif latencia_ms > 500 or latencia_ms < 0:
            estado_global = "degraded"
        else:
            estado_global = "healthy"

        return HealthStatus(
            status=estado_global,
            details={
                "chroma": chroma_ok,
                "ollama_embeddings": chroma_ok,
                "vault_available": bool(vault_ok),
                "total_entradas": total_entradas,
                "entradas_expiradas": expiradas,
                "latencia_query_ms": latencia_ms,
            },
        )

    def _to_message(self, value: str | Message, role: str) -> Message:
        """Normaliza cadenas o mensajes existentes a ``Message``.

        Ejemplo::
            msg = memory._to_message("hola", "user")

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

        Ejemplo::
            score = memory._estimate_importance(user_msg, assistant_msg)

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
