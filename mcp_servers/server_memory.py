"""Servidor MCP que expone la fachada pública `MemorySystem`."""

from __future__ import annotations

from typing import Any

from mcp_servers.base import MCPTool, campo, schema_objeto, serializar_dato
from memory import MemoryEntry, MemorySystem
from memory.episodic import Episode


class ServidorMemoria:
    """Adaptador MCP para memoria sin exponer submódulos internos."""

    nombre = "memory"

    def __init__(self, memory_system: MemorySystem | None = None) -> None:
        self._memory = memory_system or MemorySystem()

    def herramientas(self) -> list[MCPTool]:
        """Declara herramientas de memoria disponibles para el bus."""
        return [
            MCPTool(
                name="memory.contexto",
                description="Construye contexto de memoria.",
                input_schema=schema_objeto({
                    "task": campo("string", "Tarea para la que se construye contexto."),
                    "max_tokens": campo("integer", "Presupuesto máximo aproximado de tokens.", minimum=1),
                }, ["task"]),
            ),
            MCPTool(
                name="memory.guardar",
                description="Guarda una entrada de largo plazo.",
                input_schema=schema_objeto({
                    "content": campo("string", "Contenido completo a recordar."),
                    "summary": campo("string", "Resumen corto opcional."),
                    "category": campo("string", "Categoría: tarea, preferencia, hecho, error o workflow."),
                    "source": campo("string", "Origen de la memoria."),
                    "importance": campo("number", "Importancia entre 0.0 y 1.0.", minimum=0, maximum=1),
                    "metadata": campo("object", "Metadatos planos opcionales."),
                }, ["content"]),
                side_effects=["memory.write"],
            ),
            MCPTool(
                name="memory.buscar",
                description="Busca en memoria semántica.",
                input_schema=schema_objeto({
                    "query": campo("string", "Consulta semántica."),
                    "limit": campo("integer", "Máximo de resultados.", minimum=1),
                }, ["query"]),
            ),
            MCPTool(
                name="memory.workflow",
                description="Busca workflow aplicable.",
                input_schema=schema_objeto({
                    "task": campo("string", "Tarea a comparar con workflows aprendidos."),
                }, ["task"]),
            ),
            MCPTool(
                name="memory.episodio",
                description="Registra un episodio.",
                input_schema=schema_objeto({
                    "episode": campo("object", "Episodio serializado con el schema de memory.Episode."),
                }, ["episode"]),
                side_effects=["memory.episode.write"],
            ),
            MCPTool(
                name="memory.health",
                description="Verifica salud de memoria.",
                input_schema=schema_objeto(),
            ),
        ]

    async def ejecutar(self, tool_name: str, params: dict[str, Any]) -> Any:
        """Ejecuta una herramienta de memoria.

        Args:
            tool_name: Nombre canónico de herramienta.
            params: Parámetros de llamada.

        Returns:
            Resultado serializable de memoria.
        """
        match tool_name:
            case "memory.contexto":
                return await self._memory.get_context(
                    str(params["task"]),
                    int(params.get("max_tokens", 2000)),
                )
            case "memory.guardar":
                entry = MemoryEntry(
                    content=str(params["content"]),
                    summary=str(params.get("summary") or str(params["content"])[:256]),
                    category=str(params.get("category", "hecho")),
                    source=str(params.get("source", "conversacion")),
                    importance=float(params.get("importance", 0.6)),
                    metadata=dict(params.get("metadata", {})),
                )
                ident = await self._memory.store_memory(entry)
                return {"id": ident}
            case "memory.buscar":
                entradas = await self._memory.search_memory(
                    str(params["query"]),
                    limit=int(params.get("limit", 5)),
                )
                return serializar_dato(entradas)
            case "memory.workflow":
                return serializar_dato(await self._memory.find_workflow(str(params["task"])))
            case "memory.episodio":
                episode = Episode(**dict(params["episode"]))
                return {"id": await self._memory.record_episode(episode)}
            case "memory.health":
                return await self._memory.health_check()
            case _:
                raise ValueError(f"Herramienta memory desconocida: {tool_name}")
