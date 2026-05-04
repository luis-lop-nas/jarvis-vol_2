"""Reflexión post-ejecución: evalúa resultado y decide siguiente movimiento."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import orjson

from core.planner import Plan
from models.base import BaseModel, Mensaje

RUTA_PROMPT = Path(__file__).parent.parent / "config" / "prompts" / "reflector.md"

Veredicto = Literal["exito", "fallo_parcial", "fallo_total", "requiere_humano"]
SiguienteAccion = Literal["continuar", "reintentar", "replanificar", "parar"]


@dataclass(slots=True)
class Reflexion:
    """Resultado estructurado de la reflexión sobre la ejecución."""

    veredicto: Veredicto
    razonamiento: str
    criterio_exito_cumplido: bool
    siguiente_accion: SiguienteAccion
    aprendizaje: str | None = None


class Reflector:
    """Pide al modelo una autoevaluación tras ejecutar un plan."""

    def __init__(self, modelo: BaseModel) -> None:
        self._modelo = modelo
        self._prompt_sistema = RUTA_PROMPT.read_text(encoding="utf-8")

    async def reflexionar(self, plan: Plan, resultado: dict[str, Any]) -> Reflexion:
        """Devuelve la `Reflexion` correspondiente al plan ejecutado."""
        prompt = (
            f"Plan original:\n{orjson.dumps(plan.__dict__, default=str).decode()}\n\n"
            f"Resultado de la ejecución:\n{orjson.dumps(resultado, default=str).decode()}"
        )
        respuesta = await self._modelo.complete(
            [
                Mensaje(rol="system", contenido=self._prompt_sistema),
                Mensaje(rol="user", contenido=prompt),
            ],
            temperatura=0.1,
        )
        return self._parsear(respuesta.contenido)

    @staticmethod
    def _parsear(texto: str) -> Reflexion:
        limpio = texto.strip()
        if limpio.startswith("```"):
            limpio = limpio.split("```")[1]
            if limpio.startswith("json"):
                limpio = limpio[4:]
            limpio = limpio.strip()
        datos = orjson.loads(limpio)
        return Reflexion(
            veredicto=datos["veredicto"],
            razonamiento=datos["razonamiento"],
            criterio_exito_cumplido=bool(datos.get("criterio_exito_cumplido", False)),
            siguiente_accion=datos["siguiente_accion"],
            aprendizaje=datos.get("aprendizaje"),
        )
