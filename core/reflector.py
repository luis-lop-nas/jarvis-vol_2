"""Reflexión post-ejecución: evalúa resultado y decide siguiente movimiento."""

from __future__ import annotations

import logging
from enum import StrEnum
from pathlib import Path
from typing import Any

import orjson
from pydantic import BaseModel as _PBase
from pydantic import Field

from core.planner import PasoAccion, PlanEjecucion
from models.base import BaseModel as _ModelBase
from models.base import Mensaje

_PROMPT_EXPLAIN = (
    "Eres el reflector de JARVIS. Explica brevemente por qué falló este paso "
    "y qué debe evitar el planificador al generar un plan alternativo. "
    "Máximo 2 frases en español. Sé concreto: menciona el recurso o condición que falló."
)

log = logging.getLogger(__name__)

RUTA_PROMPT = Path(__file__).parent.parent / "config" / "prompts" / "reflector.md"


class ResultadoPaso(_PBase):
    """Resultado de ejecutar un paso del plan.

    Ejemplo::
        r = ResultadoPaso(id_paso="paso_1", exito=True, salida="contenido")
    """

    id_paso: str
    exito: bool
    salida: Any = None
    error: str | None = None
    duracion_ms: int = 0
    efectos_secundarios: list[str] = Field(default_factory=list)


class DecisionReflexion(StrEnum):
    """Decisión del reflector tras evaluar el resultado de un paso."""

    CONTINUAR = "continuar"
    REINTENTAR = "reintentar"
    REPLANIFICAR = "replanificar"
    ABORTAR = "abortar"
    ESPERAR_USUARIO = "esperar_usuario"


class Reflector:
    """Evalúa el resultado de cada paso y decide cómo continuar.

    Combina reglas deterministas (sin LLM) con razonamiento LLM para casos ambiguos.

    Ejemplo::
        decision = await reflector.reflect(paso, resultado, plan, historial)
        if decision == DecisionReflexion.CONTINUAR:
            ...
    """

    MAX_REINTENTOS = 3

    def __init__(self, modelo: _ModelBase) -> None:
        self._modelo = modelo
        try:
            self._prompt_sistema = RUTA_PROMPT.read_text(encoding="utf-8")
        except FileNotFoundError:
            self._prompt_sistema = (
                "Eres el reflector de JARVIS. Evalúa el resultado del paso "
                "y responde SOLO con una de: continuar, reintentar, replanificar, "
                "abortar, esperar_usuario"
            )

    async def reflect(
        self,
        paso: PasoAccion,
        resultado: ResultadoPaso,
        plan: PlanEjecucion,
        historial: list[ResultadoPaso],
    ) -> DecisionReflexion:
        """Decide cómo continuar tras ejecutar un paso.

        Aplica reglas deterministas primero; solo llama al LLM si no resuelven.

        Ejemplo::
            d = await reflector.reflect(paso, res, plan, [])
        """
        if resultado.exito:
            return DecisionReflexion.CONTINUAR

        error = resultado.error or ""

        # Reglas deterministas — sin LLM
        if "PermissionError" in error:
            return DecisionReflexion.ABORTAR

        if "FileNotFoundError" in error:
            return DecisionReflexion.REPLANIFICAR

        if "TimeoutError" in error:
            reintentos = _contar_reintentos(paso.id, historial)
            if reintentos >= self.MAX_REINTENTOS:
                return DecisionReflexion.ABORTAR
            return DecisionReflexion.REINTENTAR

        if not paso.puede_fallar:
            reintentos = _contar_reintentos(paso.id, historial)
            if reintentos >= self.MAX_REINTENTOS:
                return DecisionReflexion.REPLANIFICAR
            return DecisionReflexion.REINTENTAR

        # Paso puede fallar → continuar de todas formas
        return DecisionReflexion.CONTINUAR

    def evaluate_task_completion(
        self, plan: PlanEjecucion, resultados: list[ResultadoPaso]
    ) -> bool:
        """True si todos los pasos obligatorios del plan completaron con éxito.

        Ejemplo::
            done = reflector.evaluate_task_completion(plan, resultados)
        """
        ids_exitosos = {r.id_paso for r in resultados if r.exito}
        return all(p.id in ids_exitosos for p in plan.pasos if not p.puede_fallar)

    async def generate_summary(
        self, plan: PlanEjecucion, resultados: list[ResultadoPaso]
    ) -> str:
        """Genera un resumen en español de lo que JARVIS hizo y el resultado.

        Ejemplo::
            texto = await reflector.generate_summary(plan, resultados)
        """
        exitosos = sum(1 for r in resultados if r.exito)
        total = len(resultados)
        completada = self.evaluate_task_completion(plan, resultados)
        detalle = "\n".join(
            f"- {r.id_paso}: {'OK' if r.exito else 'FALLO'}"
            + (f" — {r.error}" if r.error else "")
            for r in resultados
        )
        prompt = (
            f"Tarea: {plan.tarea}\n"
            f"Pasos completados: {exitosos}/{total}\n"
            f"¿Tarea completada? {'Sí' if completada else 'No'}\n\n"
            f"{detalle}\n\n"
            "Escribe un resumen breve (2-3 frases) en español para el usuario."
        )
        respuesta = await self._modelo.complete(
            [
                Mensaje(rol="system", contenido="Eres el asistente de JARVIS. Resume en español."),
                Mensaje(rol="user", contenido=prompt),
            ],
            temperatura=0.3,
            max_tokens=256,
        )
        return respuesta.content.strip()

    async def explain_failure(
        self,
        paso: PasoAccion,
        resultado: ResultadoPaso,
        contexto_sistema: dict[str, Any] | None = None,
    ) -> str:
        """Genera una explicación del fallo para enriquecer el contexto de replanificación.

        Patrón JARVIS-1 Self-Explain: el planificador recibe no solo el error crudo
        sino una explicación natural de por qué falló y qué evitar.

        Ejemplo::
            exp = await reflector.explain_failure(paso, resultado)
            nuevo_plan = await planner.replan(paso, plan, f"{error}\\n\\nAnálisis: {exp}")
        """
        datos: dict[str, Any] = {
            "herramienta": paso.herramienta,
            "descripcion": paso.descripcion,
            "parametros": paso.parametros,
            "error": resultado.error,
        }
        if contexto_sistema:
            datos["contexto"] = {k: v for k, v in contexto_sistema.items() if k != "screenshot"}
        try:
            respuesta = await self._modelo.complete(
                [
                    Mensaje(rol="system", contenido=_PROMPT_EXPLAIN),
                    Mensaje(rol="user", contenido=orjson.dumps(datos, default=str).decode()),
                ],
                temperatura=0.2,
                max_tokens=150,
            )
            return respuesta.content.strip()
        except Exception:
            log.debug("explain_failure falló — usando mensaje de error original")
            return resultado.error or "fallo desconocido"

    async def _reflexion_llm(
        self,
        paso: PasoAccion,
        resultado: ResultadoPaso,
        plan: PlanEjecucion,
    ) -> DecisionReflexion:
        datos = {"paso": paso.model_dump(), "resultado": resultado.model_dump(), "tarea": plan.tarea}
        respuesta = await self._modelo.complete(
            [
                Mensaje(rol="system", contenido=self._prompt_sistema),
                Mensaje(
                    rol="user",
                    contenido=(
                        "Evalúa y responde SOLO una de: "
                        "continuar, reintentar, replanificar, abortar, esperar_usuario\n\n"
                        + orjson.dumps(datos, default=str).decode()
                    ),
                ),
            ],
            temperatura=0.1,
            max_tokens=50,
        )
        texto = respuesta.content.strip().lower()
        try:
            return DecisionReflexion(texto)
        except ValueError:
            return DecisionReflexion.REPLANIFICAR


def _contar_reintentos(id_paso: str, historial: list[ResultadoPaso]) -> int:
    return sum(1 for r in historial if r.id_paso == id_paso and not r.exito)
