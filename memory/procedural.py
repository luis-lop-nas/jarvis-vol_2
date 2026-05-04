"""Memoria procedural: skills, recetas y rutinas aprendidas."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from memory.long_term import MemoriaLargoPlazo


@dataclass(slots=True)
class Skill:
    """Receta paramétrica que JARVIS ha aprendido a ejecutar."""

    nombre: str
    descripcion: str
    pasos: list[dict[str, Any]] = field(default_factory=list)
    parametros: list[str] = field(default_factory=list)
    veces_usada: int = 0
    creado_en: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class MemoriaProcedural:
    """Repositorio de skills indexable por nombre y por similitud semántica."""

    def __init__(self, almacen: MemoriaLargoPlazo | None = None) -> None:
        self._almacen = almacen or MemoriaLargoPlazo(coleccion="jarvis_skills")
        self._indice_local: dict[str, Skill] = {}

    async def registrar(self, skill: Skill) -> str:
        """Guarda una skill nueva e indexa su descripción para búsqueda."""
        self._indice_local[skill.nombre] = skill
        return await self._almacen.guardar(
            f"{skill.nombre}: {skill.descripcion}",
            {
                "tipo": "skill",
                "nombre": skill.nombre,
                "parametros": ",".join(skill.parametros),
            },
        )

    def obtener(self, nombre: str) -> Skill | None:
        """Recupera una skill por nombre exacto."""
        return self._indice_local.get(nombre)

    async def buscar_por_intencion(self, descripcion: str, k: int = 3) -> list[Skill]:
        """Encuentra skills semánticamente cercanas a una descripción libre."""
        fragmentos = await self._almacen.buscar(descripcion, k=k, filtro={"tipo": "skill"})
        skills: list[Skill] = []
        for f in fragmentos:
            nombre = f.metadatos.get("nombre", "")
            if skill := self._indice_local.get(nombre):
                skills.append(skill)
        return skills
