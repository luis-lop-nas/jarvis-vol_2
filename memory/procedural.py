"""Memoria procedural: workflows, recetas reutilizables e instrucciones del agente."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from memory.episodic import Episode
from memory.long_term import LongTermMemory, MemoryEntry
from models.base import BaseModel as ModelBase

log = logging.getLogger(__name__)

COLECCION_INSTRUCCIONES = "jarvis_instructions"
MAX_INSTRUCCIONES_ACTIVAS = 10


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
    """Gestor de workflows semánticos e instrucciones aprendidas del agente."""

    def __init__(
        self,
        store: LongTermMemory | None = None,
        summarizer: ModelBase | None = None,
        instructions_store: LongTermMemory | None = None,
    ) -> None:
        self._store = store or LongTermMemory(collection_name="jarvis_workflows")
        self._summarizer = summarizer
        self._instructions_store = instructions_store or LongTermMemory(
            collection_name=COLECCION_INSTRUCCIONES
        )

    async def save_workflow(self, workflow: Workflow) -> str:
        """Guarda un workflow y lo hace buscable por similitud.

        Ejemplo::
            ident = await procedural.save_workflow(workflow)

        Args:
            workflow: Workflow a persistir.

        Returns:
            Identificador de la entrada guardada.
        """
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
        """Busca un workflow aplicable a la tarea dada.

        Ejemplo::
            wf = await procedural.find_workflow("organiza descargas")

        Args:
            task: Descripción de la tarea.

        Returns:
            Workflow más relevante o ``None`` si no hay coincidencia.
        """
        entradas = await self._store.search(task, limit=5, category_filter="workflow")
        if not entradas:
            return None
        datos = entradas[0].metadata
        if not datos:
            return None
        return self._workflow_from_entry(entradas[0])

    async def learn_from_episode(self, episode: Episode) -> Workflow | None:
        """Aprende un workflow a partir de un episodio exitoso recurrente.

        Ejemplo::
            wf = await procedural.learn_from_episode(episodio)

        Args:
            episode: Episodio con resultado exitoso y pasos del plan.

        Returns:
            Workflow existente actualizado o nuevo creado, o ``None`` si no aplica.
        """
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
        """Actualiza las estadísticas de uso de un workflow.

        Ejemplo::
            await procedural.update_stats("abc123", success=True)

        Args:
            ident: Identificador del workflow.
            success: ``True`` si el workflow se completó con éxito.
        """
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
        """Devuelve todos los workflows guardados.

        Ejemplo::
            workflows = await procedural.get_all()

        Returns:
            Lista completa de workflows persistidos.
        """
        resultados = await self._store.get_by_category("workflow", limit=100)
        workflows = await asyncio.gather(
            *[self.find_workflow(entry.content) for entry in resultados]
        )
        return [workflow for workflow in workflows if workflow is not None]

    async def delete(self, ident: str) -> bool:
        """Elimina un workflow de la memoria.

        Ejemplo::
            ok = await procedural.delete("abc123")

        Args:
            ident: Identificador del workflow.

        Returns:
            ``True`` si la eliminación fue exitosa.
        """
        return await self._store.delete(ident)

    async def export_workflows(self) -> str:
        """Exporta todos los workflows en formato YAML para revisión humana.

        Ejemplo::
            yaml_str = await procedural.export_workflows()

        Returns:
            Cadena YAML con todos los workflows activos.
        """
        workflows = [
            w for w in await asyncio.gather(
                *[
                    self.find_workflow(entry.content)
                    for entry in await self._store.get_by_category("workflow", limit=100)
                ]
            )
            if w
        ]
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

    # ------------------------------------------------------------------
    # Instrucciones aprendidas (patrón LangMem)
    # ------------------------------------------------------------------

    async def get_agent_instructions(self) -> list[str]:
        """Devuelve las instrucciones aprendidas activas (máx. 10).

        Las instrucciones se cargan al inicio de cada ``run()`` del agente
        y se añaden al system prompt como contexto adicional.

        Ejemplo::
            instrucciones = await procedural.get_agent_instructions()

        Returns:
            Lista de instrucciones ordenadas por ``last_accessed`` descendente.
        """
        try:
            entradas = await self._instructions_store.get_recent(limit=MAX_INSTRUCCIONES_ACTIVAS)
            return [e.content for e in entradas]
        except Exception as exc:
            log.debug("Instrucciones aprendidas no disponibles: %s", exc)
            return []

    async def update_agent_instructions(
        self,
        feedback: str,
        confirm_callback: Callable[[str], Awaitable[bool]] | None = None,
    ) -> bool:
        """Añade o actualiza una instrucción aprendida para el sistema del agente.

        Requiere confirmación explícita del usuario cuando se proporciona
        ``confirm_callback``. Si hay más de 10 instrucciones activas, archiva
        la más antigua (establece ``valid_until = ahora``).

        Ejemplo::
            ok = await procedural.update_agent_instructions(
                "Responder siempre en español",
                confirm_callback=confirmacion_usuario,
            )

        Args:
            feedback: Texto de la instrucción aprendida.
            confirm_callback: Función async que devuelve ``True`` si el usuario
                aprueba guardar la instrucción.

        Returns:
            ``True`` si la instrucción fue guardada, ``False`` si fue rechazada.
        """
        if confirm_callback is not None:
            aprobado = await confirm_callback(
                f"¿Guardar instrucción aprendida?\n{feedback}"
            )
            if not aprobado:
                log.info("Instrucción rechazada por el usuario: %s", feedback[:60])
                return False

        try:
            instrucciones_actuales = await self._instructions_store.get_recent(
                limit=MAX_INSTRUCCIONES_ACTIVAS + 1
            )
            if len(instrucciones_actuales) >= MAX_INSTRUCCIONES_ACTIVAS:
                # Archiva la más antigua (el último de la lista ordenada por last_accessed desc)
                mas_antigua = instrucciones_actuales[-1]
                mas_antigua.valid_until = datetime.now(UTC)
                await self._instructions_store._update_entry_metadata(mas_antigua)
                log.info(
                    "Instrucción archivada (límite %d): %s",
                    MAX_INSTRUCCIONES_ACTIVAS,
                    mas_antigua.id[:8],
                )

            await self._instructions_store.store(
                MemoryEntry(
                    content=feedback,
                    summary=feedback[:256],
                    category="instruccion",
                    source="feedback",
                    importance=1.0,
                ),
                dedup=False,
            )
            log.info("Instrucción aprendida guardada: %s", feedback[:60])
            return True
        except Exception as exc:
            log.warning("No se pudo guardar instrucción aprendida: %s", exc)
            return False

    def _workflow_from_entry(self, entry: MemoryEntry) -> Workflow:
        """Reconstruye un workflow desde una entrada de largo plazo.

        Ejemplo::
            wf = procedural._workflow_from_entry(entrada)

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
        """Convierte un valor externo a ``datetime``.

        Ejemplo::
            dt = ProceduralMemory._parse_datetime("2026-01-01T00:00:00+00:00")

        Args:
            value: Fecha ISO, ``datetime`` o ``None``.

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
