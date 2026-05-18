"""Planificador: convierte una petición libre en un plan ejecutable."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import orjson
from pydantic import BaseModel as _PBase
from pydantic import Field

from models.base import BaseModel as _ModelBase
from models.base import Mensaje

log = logging.getLogger(__name__)

RUTA_PROMPT = Path(__file__).parent.parent / "config" / "prompts" / "planner.md"

_HERRAMIENTAS_CONFIRMACION: frozenset[str] = frozenset({
    "filesystem.eliminar", "filesystem.mover", "filesystem.escribir",
    "terminal.python", "mail.enviar", "mail.eliminar",
    "imessage.enviar", "whatsapp.enviar", "telegram.enviar",
    "browser.ejecutar_js",
})

_HERRAMIENTAS_VALIDAS: frozenset[str] = frozenset({
    "filesystem.leer", "filesystem.escribir", "filesystem.eliminar",
    "filesystem.listar", "filesystem.mover", "filesystem.copiar",
    "filesystem.buscar",
    "terminal.ejecutar", "terminal.transmitir", "terminal.python",
    "sistema.abrir_app", "sistema.cerrar_app", "sistema.volumen",
    "sistema.clipboard", "sistema.notificacion", "sistema.brillo",
    "teclado.escribir", "teclado.atajo", "teclado.click",
    "teclado.doble_click", "teclado.scroll",
    "browser.abrir", "browser.leer", "browser.click",
    "browser.fill", "browser.ejecutar_js", "browser.screenshot",
    "percepcion.screenshot", "percepcion.accesibilidad",
    "mail.leer", "mail.enviar", "mail.eliminar",
    "imessage.leer", "imessage.enviar",
    "whatsapp.leer", "whatsapp.enviar",
    "telegram.leer", "telegram.enviar",
    "pedir_aclaracion",
})

_KW_COMPLEJO = (
    "implementa", "programa", "diseña", "refactoriza", "analiza",
    "crea", "optimiza", "investiga", "planifica", "depura", "construye",
)
_KW_SENSIBLE = (
    "contraseña", "password", "token", "secreto", "privado",
    "credencial", "dni", "tarjeta", "cuenta bancaria", "api key",
)


class PasoAccion(_PBase):
    """Paso atómico dentro de un plan de ejecución.

    Ejemplo::
        paso = PasoAccion(id="leer_1", descripcion="Lee el README",
                          herramienta="filesystem.leer",
                          parametros={"ruta": "~/README.md"})
    """

    id: str
    descripcion: str
    herramienta: str
    parametros: dict[str, Any] = Field(default_factory=dict)
    requiere_confirmacion: bool = False
    depende_de: list[str] = Field(default_factory=list)
    duracion_estimada_ms: int = 500
    puede_fallar: bool = False


class PlanEjecucion(_PBase):
    """Plan completo generado por el planificador.

    Ejemplo::
        plan = PlanEjecucion(tarea="Lee el README", pasos=[paso])
    """

    id: str = Field(default_factory=lambda: uuid4().hex)
    tarea: str
    pasos: list[PasoAccion]
    duracion_total_ms: int = 0
    requiere_internet: bool = False
    toca_datos_sensibles: bool = False
    modelo_usado: str = ""
    creado_en: datetime = Field(default_factory=datetime.now)


# Alias de compatibilidad hacia atrás (security/confirmation.py los referencia)
PasoPlan = PasoAccion
Plan = PlanEjecucion


class Planner:
    """Genera planes JSON estructurados a partir de instrucciones del usuario.

    Ejemplo::
        planner = Planner(modelo=kimi)
        plan = await planner.plan("Organiza mis descargas")
        print(plan.pasos)
    """

    def __init__(self, modelo: _ModelBase) -> None:
        self._modelo = modelo
        try:
            self._prompt_sistema = RUTA_PROMPT.read_text(encoding="utf-8")
        except FileNotFoundError:
            self._prompt_sistema = "Eres el planificador de JARVIS. Responde solo con JSON válido."

    async def plan(
        self,
        tarea: str,
        contexto: dict[str, Any] | None = None,
        herramientas: list[str] | None = None,
    ) -> PlanEjecucion:
        """Genera un plan estructurado para la tarea indicada.

        Ejemplo::
            plan = await planner.plan("Lee el archivo README.md")
        """
        ctx = f"\n\nContexto:\n{orjson.dumps(contexto, default=str).decode()}" if contexto else ""
        herr = f"\n\nHerramientas: {', '.join(herramientas)}" if herramientas else ""

        mensajes: list[Mensaje] = [
            Mensaje(rol="system", contenido=self._prompt_sistema),
            Mensaje(rol="user", contenido=f"Tarea:\n{tarea}{ctx}{herr}"),
        ]
        respuesta = await self._modelo.complete(mensajes, temperatura=0.2, max_tokens=2048)
        plan = self._parsear(respuesta.content)
        return plan.model_copy(update={
            "tarea": tarea,
            "modelo_usado": respuesta.model,
            "toca_datos_sensibles": self._detectar_sensible(tarea),
            "duracion_total_ms": sum(p.duracion_estimada_ms for p in plan.pasos),
        })

    async def replan(
        self,
        paso_fallido: PasoAccion,
        plan: PlanEjecucion,
        error: str,
        contexto: dict[str, Any] | None = None,
    ) -> PlanEjecucion:
        """Plan alternativo desde el punto de fallo.

        Ejemplo::
            nuevo = await planner.replan(paso, plan, "FileNotFoundError")
        """
        completados = [p.id for p in plan.pasos if p.id != paso_fallido.id]
        prompt = (
            f"Paso fallido: '{paso_fallido.descripcion}' "
            f"(herramienta: {paso_fallido.herramienta})\n"
            f"Error: {error}\n"
            f"Pasos ya completados: {completados}\n"
            f"Tarea original: {plan.tarea}\n\n"
            "Genera un plan alternativo para completar la tarea desde el punto de fallo."
        )
        respuesta = await self._modelo.complete(
            [
                Mensaje(rol="system", contenido=self._prompt_sistema),
                Mensaje(rol="user", contenido=prompt),
            ],
            temperatura=0.3,
            max_tokens=2048,
        )
        nuevo = self._parsear(respuesta.content)
        return nuevo.model_copy(update={
            "tarea": plan.tarea,
            "modelo_usado": respuesta.model,
            "duracion_total_ms": sum(p.duracion_estimada_ms for p in nuevo.pasos),
        })

    def validate_plan(self, plan: PlanEjecucion) -> list[str]:
        """Verifica la consistencia del plan. Devuelve lista de errores encontrados.

        Ejemplo::
            errores = planner.validate_plan(plan)
            assert not errores, errores
        """
        errores: list[str] = []
        ids_vistos: set[str] = set()

        if len(plan.pasos) > 20:
            errores.append(f"Demasiados pasos: {len(plan.pasos)} (máx 20)")

        for paso in plan.pasos:
            if paso.id in ids_vistos:
                errores.append(f"ID duplicado: {paso.id}")
            ids_vistos.add(paso.id)

            if paso.herramienta not in _HERRAMIENTAS_VALIDAS:
                errores.append(f"Herramienta desconocida en '{paso.id}': {paso.herramienta}")

            if paso.herramienta in _HERRAMIENTAS_CONFIRMACION and not paso.requiere_confirmacion:
                errores.append(
                    f"Paso '{paso.id}' usa '{paso.herramienta}' sin requiere_confirmacion=True"
                )

        grafo: dict[str, list[str]] = {p.id: p.depende_de for p in plan.pasos}
        if _tiene_ciclo(grafo):
            errores.append("El plan tiene dependencias circulares")

        return errores

    def estimate_complexity(self, tarea: str) -> float:
        """Estima la complejidad de una tarea (0.0 trivial → 1.0 muy compleja).

        Ejemplo::
            c = planner.estimate_complexity("abre Safari")  # ~0.1
        """
        lower = tarea.lower()
        puntos = sum(0.15 for kw in _KW_COMPLEJO if kw in lower)
        if len(tarea.split()) > 20:
            puntos += 0.2
        if any(s in lower for s in _KW_SENSIBLE):
            puntos += 0.1
        return min(1.0, puntos)

    async def crear_plan(self, peticion: str, historial: list[Mensaje]) -> PlanEjecucion:
        """Wrapper de compatibilidad hacia atrás."""
        return await self.plan(peticion)

    # ------------------------------------------------------------------
    # Helpers privados
    # ------------------------------------------------------------------

    @staticmethod
    def _parsear(json_texto: str) -> PlanEjecucion:
        limpio = json_texto.strip()
        if limpio.startswith("```"):
            limpio = limpio.split("```")[1]
            if limpio.startswith("json"):
                limpio = limpio[4:]
            limpio = limpio.strip()
        datos = orjson.loads(limpio)
        pasos = [PasoAccion(**p) for p in datos.get("pasos", datos.get("steps", []))]
        return PlanEjecucion(
            tarea=datos.get("objetivo", datos.get("task", "")),
            pasos=pasos,
        )

    @staticmethod
    def _detectar_sensible(texto: str) -> bool:
        lower = texto.lower()
        return any(kw in lower for kw in _KW_SENSIBLE)


def _tiene_ciclo(grafo: dict[str, list[str]]) -> bool:
    visitados: set[str] = set()
    en_pila: set[str] = set()

    def dfs(nodo: str) -> bool:
        visitados.add(nodo)
        en_pila.add(nodo)
        for vecino in grafo.get(nodo, []):
            if vecino not in visitados:
                if dfs(vecino):
                    return True
            elif vecino in en_pila:
                return True
        en_pila.discard(nodo)
        return False

    return any(nodo not in visitados and dfs(nodo) for nodo in list(grafo))
