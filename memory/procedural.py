"""Memoria procedural: workflows y recetas reutilizables aprendidas."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from memory.episodic import Episode
from memory.long_term import LongTermMemory, MemoryEntry
from models.base import BaseModel as ModelBase


class Workflow(BaseModel):
    """Rutina aprendida reutilizable para tareas recurrentes."""

    id: str | None = None
    name: str
    description: str
    trigger_patterns: list[str] = Field(default_factory=list)
    steps: list[dict[str, Any]] = Field(default_factory=list)
    success_count: int = 0
    failure_count: int = 0
    avg_duration_ms: int = 0
    last_used: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    auto_learned: bool = True


class ProceduralMemory:
    """Gestor de workflows semánticos basados en episodios."""

    def __init__(
        self,
        store: LongTermMemory | None = None,
        summarizer: ModelBase | None = None,
    ) -> None:
        self._store = store or LongTermMemory(collection_name="jarvis_workflows")
        self._summarizer = summarizer

    async def save_workflow(self, workflow: Workflow) -> str:
        """Guarda un workflow y lo hace buscable por similitud."""
        workflow.id = workflow.id or uuid4().hex
        metadata = workflow.model_dump(exclude={"id", "description"})
        metadata["tipo"] = "workflow"
        return await self._store.store(
            MemoryEntry(
                id=workflow.id,
                content=workflow.description,
                summary=workflow.description,
                category="workflow",
                source="procedural",
                importance=0.8,
                metadata=metadata,
            )
        )

    async def find_workflow(self, task: str) -> Workflow | None:
        """Busca un workflow aplicable a la tarea dada."""
        entradas = await self._store.search(task, limit=5, category_filter="workflow")
        if not entradas:
            return None
        datos = entradas[0].metadata
        if not datos:
            return None
        return self._workflow_from_entry(entradas[0])

    async def learn_from_episode(self, episode: Episode) -> Workflow | None:
        """Aprende un workflow a partir de un episodio exitoso recurrente."""
        if episode.outcome != "success":
            return None
        pasos = episode.plan_used.get("pasos") or episode.plan_used.get("steps")
        if not episode.plan_used or not pasos:
            return None

        workflow = await self.find_workflow(episode.task)
        if workflow:
            await self.update_stats(workflow.id or "", success=True)
            return workflow

        nueva = Workflow(
            name=episode.task,
            description=f"Workflow aprendido de la tarea: {episode.task}",
            trigger_patterns=[episode.task],
            steps=episode.plan_used.get("pasos", []),
            success_count=1,
            failure_count=0,
            avg_duration_ms=episode.duration_ms,
            last_used=datetime.now(UTC),
            auto_learned=True,
        )
        await self.save_workflow(nueva)
        return nueva

    async def update_stats(self, ident: str, success: bool) -> None:
        """Actualiza las estadísticas de uso de un workflow."""
        entry = await self._store.get(ident)
        if entry is None:
            return
        workflow = self._workflow_from_entry(entry)
        if success:
            workflow.success_count += 1
        else:
            workflow.failure_count += 1
        total = max(1, workflow.success_count + workflow.failure_count)
        anterior = int(entry.metadata.get("avg_duration_ms", workflow.avg_duration_ms))
        workflow.avg_duration_ms = int((anterior * (total - 1) + workflow.avg_duration_ms) / total)
        workflow.last_used = datetime.now(UTC)

        entry.metadata.update(workflow.model_dump(exclude={"id", "description"}))
        await self._store.update(ident, entry.content)

    async def get_all(self) -> list[Workflow]:
        """Devuelve todos los workflows guardados."""
        resultados = await self._store.get_by_category("workflow", limit=100)
        workflows = await asyncio.gather(
            *[self.find_workflow(entry.content) for entry in resultados]
        )
        return [workflow for workflow in workflows if workflow is not None]

    async def delete(self, ident: str) -> bool:
        """Elimina un workflow de la memoria."""
        return await self._store.delete(ident)

    async def export_workflows(self) -> str:
        """Exporta todos los workflows en formato YAML para revisión humana."""
        workflows = [w for w in await asyncio.gather(*[self.find_workflow(entry.content) for entry in await self._store.get_by_category("workflow", limit=100)]) if w]
        lineas: list[str] = ["workflows:"]
        for workflow in workflows:
            lineas.append(f"  - id: {workflow.id}")
            lineas.append(f"    name: {workflow.name}")
            lineas.append(f"    description: {workflow.description}")
            lineas.append("    trigger_patterns:")
            for pattern in workflow.trigger_patterns:
                lineas.append(f"      - {pattern}")
            lineas.append("    steps:")
            for step in workflow.steps:
                lineas.append("      -")
                for key, value in step.items():
                    lineas.append(f"          {key}: {value}")
        return "\n".join(lineas)

    def _workflow_from_entry(self, entry: MemoryEntry) -> Workflow:
        """Reconstruye un workflow desde una entrada de largo plazo.

        Args:
            entry: Entrada persistida con metadatos de workflow.

        Returns:
            Workflow Pydantic listo para usar.
        """
        datos = entry.metadata
        return Workflow(
            id=entry.id,
            name=datos.get("name", entry.content),
            description=entry.content,
            trigger_patterns=datos.get("trigger_patterns", [entry.content]),
            steps=datos.get("steps", []),
            success_count=int(datos.get("success_count", 0)),
            failure_count=int(datos.get("failure_count", 0)),
            avg_duration_ms=int(datos.get("avg_duration_ms", 0)),
            last_used=self._parse_datetime(datos.get("last_used")),
            created_at=self._parse_datetime(datos.get("created_at")),
            auto_learned=bool(datos.get("auto_learned", True)),
        )

    @staticmethod
    def _parse_datetime(value: str | datetime | None) -> datetime:
        """Convierte un valor externo a `datetime`.

        Args:
            value: Fecha ISO, `datetime` o `None`.

        Returns:
            Fecha parseada o fecha actual en UTC.
        """
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                pass
        return datetime.now(UTC)


MemoriaProcedural = ProceduralMemory
