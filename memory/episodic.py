"""Memoria episódica: registro de tareas, resultados y lecciones aprendidas."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from memory.long_term import LongTermMemory, MemoryEntry
from models.base import BaseModel as ModelBase, Mensaje


class Episode(BaseModel):
    """Registro de una ejecución de tarea completa."""

    id: str | None = None
    task: str
    plan_used: dict[str, Any]
    steps_completed: int = 0
    steps_failed: int = 0
    outcome: Literal["success", "partial", "failed", "aborted"]
    duration_ms: int = 0
    error_summary: str | None = None
    lessons: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    model_used: str = ""


class EpisodicStats(BaseModel):
    success_rate: float
    avg_duration_ms: int
    most_common_failures: list[str]
    total_episodes: int


class EpisodicMemory:
    """Memoria de episodios que permite recuperar tareas previas y extraer lecciones."""

    def __init__(
        self,
        store: LongTermMemory | None = None,
        summarizer: ModelBase | None = None,
    ) -> None:
        self._store = store or LongTermMemory(collection_name="jarvis_episodic")
        self._summarizer = summarizer

    async def record(self, episode: Episode) -> str:
        """Registra un episodio de ejecución en la memoria."""
        entrada = MemoryEntry(
            id=episode.id or uuid4().hex,
            content=episode.task,
            summary=episode.error_summary or episode.task,
            category="episodio",
            source="conversacion",
            importance=0.7,
            created_at=episode.created_at,
            last_accessed=episode.created_at,
            access_count=0,
            metadata={
                "plan_used": episode.plan_used,
                "steps_completed": episode.steps_completed,
                "steps_failed": episode.steps_failed,
                "outcome": episode.outcome,
                "duration_ms": episode.duration_ms,
                "error_summary": episode.error_summary,
                "lessons": episode.lessons,
                "model_used": episode.model_used,
            },
        )
        return await self._store.store(entrada)

    async def get_similar_tasks(self, task: str, limit: int = 5) -> list[Episode]:
        """Recupera episodios similares usando búsqueda semántica."""
        entradas = await self._store.search(task, limit=limit, category_filter="episodio")
        return [self._to_episode(e) for e in entradas]

    async def get_successful(self, task_pattern: str, limit: int = 5) -> list[Episode]:
        """Recupera episodios exitosos que coinciden con un patrón de tarea."""
        candidatos = await self._store.search_hybrid(task_pattern, limit=limit)
        exitosos = [e for e in candidatos if e.metadata.get("outcome") == "success"]
        return [self._to_episode(e) for e in exitosos[:limit]]

    async def get_failures(self, limit: int = 5) -> list[Episode]:
        """Recupera los episodios recientes que terminaron con fallo."""
        entradas = await self._store.get_recent(limit*5)
        fallidos = [e for e in entradas if e.metadata.get("outcome") in ("failed", "aborted")]
        return [self._to_episode(e) for e in fallidos[:limit]]

    async def extract_lessons(self, episode: Episode) -> list[str]:
        """Extrae lecciones reutilizables de un episodio con ayuda de un modelo."""
        if self._summarizer is None:
            return episode.lessons

        prompt = (
            f"Toma la siguiente ejecución de tarea y extrae lecciones claras "
            f"que puedan reutilizarse en futuros episodios:\n\n" 
            f"Tarea: {episode.task}\n"
            f"Resultado: {episode.outcome}\n"
            f"Error: {episode.error_summary or 'Ninguno'}\n"
            f"Lecciones actuales: {episode.lessons}\n"
            f"Plan: {episode.plan_used}\n"
        )
        respuesta = await self._summarizer.complete(
            [
                Mensaje(rol="system", contenido=prompt),
            ],
            temperatura=0.3,
            max_tokens=256,
        )
        return [line.strip() for line in respuesta.content.splitlines() if line.strip()][:5]

    async def get_best_approach(self, task: str) -> str | None:
        """Devuelve el mejor enfoque encontrado para una tarea similar."""
        exitosos = await self.get_successful(task, limit=3)
        if not exitosos:
            return None
        mejor = exitosos[0]
        return (
            f"Tarea similar: {mejor.task}. Resultado: {mejor.outcome}. "
            f"Duración: {mejor.duration_ms} ms. Lecciones: {mejor.lessons}."
        )

    async def stats(self) -> EpisodicStats:
        """Calcula estadísticas agregadas de episodios almacenados."""
        todas = await self._store.get_recent(100)
        total = len(todas)
        if total == 0:
            return EpisodicStats(
                success_rate=0.0,
                avg_duration_ms=0,
                most_common_failures=[],
                total_episodes=0,
            )
        exitosos = [e for e in todas if e.metadata.get("outcome") == "success"]
        fallas = [e.metadata.get("error_summary", "") for e in todas if e.metadata.get("outcome") in ("failed", "aborted")]
        promedio = int(sum(int(e.metadata.get("duration_ms", 0)) for e in todas) / total)
        return EpisodicStats(
            success_rate=len(exitosos) / total,
            avg_duration_ms=promedio,
            most_common_failures=sorted(set(fallas), key=fallas.count, reverse=True)[:3],
            total_episodes=total,
        )

    def _to_episode(self, entry: MemoryEntry) -> Episode:
        """Convierte una entrada persistente en un episodio Pydantic.

        Args:
            entry: Entrada recuperada desde la memoria semántica.

        Returns:
            Episodio reconstruido con sus metadatos.
        """
        metadata = entry.metadata
        return Episode(
            id=entry.id,
            task=entry.content,
            plan_used=metadata.get("plan_used", {}),
            steps_completed=int(metadata.get("steps_completed", 0)),
            steps_failed=int(metadata.get("steps_failed", 0)),
            outcome=metadata.get("outcome", "partial"),
            duration_ms=int(metadata.get("duration_ms", 0)),
            error_summary=metadata.get("error_summary"),
            lessons=metadata.get("lessons", []),
            created_at=entry.created_at,
            model_used=metadata.get("model_used", ""),
        )


MemoriaEpisodica = EpisodicMemory
