"""Planificador: convierte una petición libre en un plan ejecutable."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import orjson

from models.base import BaseModel, Mensaje

log = logging.getLogger(__name__)

RUTA_PROMPT = Path(__file__).parent.parent / "config" / "prompts" / "planner.md"


@dataclass(slots=True)
class PasoPlan:
    """Paso atómico dentro de un plan."""

    id: int
    descripcion: str
    herramienta: str
    argumentos: dict[str, Any] = field(default_factory=dict)
    depende_de: list[int] = field(default_factory=list)
    es_destructivo: bool = False
    requiere_confirmacion: bool = False


@dataclass(slots=True)
class Plan:
    """Plan completo devuelto por el LLM planificador."""

    objetivo: str
    pasos: list[PasoPlan]
    riesgos: list[str] = field(default_factory=list)
    criterio_exito: str = ""


class Planner:
    """Genera planes JSON estructurados a partir de instrucciones del usuario."""

    def __init__(self, modelo: BaseModel) -> None:
        self._modelo = modelo
        self._prompt_sistema = RUTA_PROMPT.read_text(encoding="utf-8")

    async def crear_plan(self, peticion: str, historial: list[Mensaje]) -> Plan:
        """Construye el plan llamando al modelo y parseando su salida JSON."""
        mensajes: list[Mensaje] = [
            Mensaje(rol="system", contenido=self._prompt_sistema),
            *historial,
            Mensaje(rol="user", contenido=f"Petición a planificar:\n{peticion}"),
        ]
        respuesta = await self._modelo.complete(
            mensajes,
            temperatura=0.2,
            max_tokens=2048,
        )
        return self._parsear(respuesta.contenido)

    @staticmethod
    def _parsear(json_texto: str) -> Plan:
        """Parsea JSON del modelo, tolerante a bloques markdown ``` json."""
        limpio = json_texto.strip()
        if limpio.startswith("```"):
            limpio = limpio.split("```")[1]
            if limpio.startswith("json"):
                limpio = limpio[4:]
            limpio = limpio.strip()
        datos = orjson.loads(limpio)
        pasos = [PasoPlan(**p) for p in datos.get("pasos", [])]
        return Plan(
            objetivo=datos["objetivo"],
            pasos=pasos,
            riesgos=datos.get("riesgos", []),
            criterio_exito=datos.get("criterio_exito", ""),
        )
