"""Agente principal: orquesta percepción, planificación, ejecución y reflexión."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator
from uuid import uuid4

from config import settings
from core.planner import Plan, Planner
from core.reflector import Reflector, Reflexion
from core.router import ContextoRuteo, Router
from memory.episodic import MemoriaEpisodica
from memory.short_term import MemoriaCortoPlazo
from models.base import Mensaje
from security.audit_log import AuditLog
from security.confirmation import GestorConfirmacion

log = logging.getLogger(__name__)


@dataclass(slots=True)
class EstadoAgente:
    """Estado mutable de una sesión del agente."""

    sesion_id: str = field(default_factory=lambda: uuid4().hex)
    historial: list[Mensaje] = field(default_factory=list)
    acciones_consecutivas: int = 0
    plan_actual: Plan | None = None


class Agente:
    """Punto de entrada de alto nivel para procesar peticiones del usuario."""

    def __init__(
        self,
        router: Router,
        planner: Planner,
        reflector: Reflector,
        memoria_corto: MemoriaCortoPlazo,
        memoria_episodica: MemoriaEpisodica,
        confirmacion: GestorConfirmacion,
        auditoria: AuditLog,
    ) -> None:
        self._router = router
        self._planner = planner
        self._reflector = reflector
        self._memoria_corto = memoria_corto
        self._memoria_episodica = memoria_episodica
        self._confirmacion = confirmacion
        self._auditoria = auditoria
        self._estado = EstadoAgente()

    # ------------------------------------------------------------------
    # API principal
    # ------------------------------------------------------------------

    async def procesar(self, peticion: str) -> str:
        """Procesa una petición del usuario y devuelve la respuesta final."""
        await self._auditoria.registrar("peticion_recibida", {"texto": peticion})
        self._estado.historial.append(Mensaje(rol="user", contenido=peticion))

        plan = await self._planner.crear_plan(peticion, self._estado.historial)
        self._estado.plan_actual = plan

        resultado = await self._ejecutar_plan(plan)

        reflexion = await self._reflector.reflexionar(plan, resultado)
        await self._post_reflexion(reflexion)

        respuesta = resultado.get("respuesta_final", "")
        self._estado.historial.append(Mensaje(rol="assistant", contenido=respuesta))
        return respuesta

    async def stream(self, peticion: str) -> AsyncIterator[str]:
        """Versión streaming: emite tokens conforme se generan."""
        self._estado.historial.append(Mensaje(rol="user", contenido=peticion))
        contexto = ContextoRuteo(mensajes=self._estado.historial)
        decision = self._router.decidir(contexto)
        modelo = self._router.obtener_modelo(decision)

        buffer: list[str] = []
        async for trozo in modelo.stream(self._estado.historial):
            buffer.append(trozo)
            yield trozo

        self._estado.historial.append(Mensaje(rol="assistant", contenido="".join(buffer)))

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    async def _ejecutar_plan(self, plan: Plan) -> dict[str, Any]:
        """Recorre los pasos del plan, pidiendo confirmación cuando proceda."""
        resultados: dict[int, Any] = {}
        for paso in plan.pasos:
            if self._estado.acciones_consecutivas >= settings.max_acciones_autonomas:
                log.warning("Límite de acciones autónomas alcanzado; pausando.")
                break

            if paso.requiere_confirmacion or (
                paso.es_destructivo and settings.confirmacion_destructiva
            ):
                if not await self._confirmacion.solicitar(paso):
                    await self._auditoria.registrar(
                        "paso_cancelado", {"paso": paso.id, "motivo": "usuario"}
                    )
                    break

            try:
                resultado = await self._ejecutar_paso(paso, resultados)
                resultados[paso.id] = resultado
                self._estado.acciones_consecutivas += 1
            except Exception as exc:  # noqa: BLE001
                log.exception("Fallo ejecutando paso %s", paso.id)
                resultados[paso.id] = {"error": str(exc)}
                break

        return {"pasos": resultados, "respuesta_final": resultados.get(len(plan.pasos), "")}

    async def _ejecutar_paso(self, paso: Any, previos: dict[int, Any]) -> Any:
        """Despacha la herramienta indicada por el paso (a implementar con MCP)."""
        # TODO: enrutar a los servidores MCP según `paso.herramienta`.
        raise NotImplementedError("Ejecución de herramientas pendiente del bus MCP.")

    async def _post_reflexion(self, reflexion: Reflexion) -> None:
        """Guarda los aprendizajes y registra el episodio en memoria."""
        if reflexion.aprendizaje:
            await self._memoria_episodica.guardar_aprendizaje(reflexion.aprendizaje)
        await self._auditoria.registrar("reflexion", reflexion.__dict__)

    @property
    def estado(self) -> EstadoAgente:
        return self._estado
