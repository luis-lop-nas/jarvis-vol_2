"""Agente principal: orquesta percepción, planificación, ejecución y reflexión.

Loop: percibir → pensar → actuar → reflexionar → (repetir o responder).
Construido con LangGraph StateGraph; el loop de ejecución es manual para
soportar streaming y pausa/reanudación sin depender de APIs de interrupt
específicas de versión.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncGenerator, Callable
from datetime import UTC, datetime
from typing import Any, TypedDict
from uuid import uuid4

from pydantic import BaseModel as _PBase

from config import settings
from core.mcp_bus import MCPBus
from core.planner import PasoAccion, PlanEjecucion, Planner
from core.reflector import DecisionReflexion, Reflector, ResultadoPaso
from memory import Episode, MemorySystem
from memory.episodic import MemoriaEpisodica
from memory.short_term import MemoriaCortoPlazo
from models.base import Mensaje
from security.audit_log import AuditLog

log = logging.getLogger(__name__)

MAX_PASOS = 50
MAX_REINTENTOS = 3
MAX_REPLANES = 3
TIMEOUT_PASO = 120.0
TIMEOUT_TAREA_GLOBAL = 1800.0  # 30 min — previene DoS por tareas infinitas

# Claves de kwargs que no puede inyectar el LLM (sobreescribirían defaults de seguridad)
_PARAMS_PROHIBIDOS: frozenset[str] = frozenset({
    "shell", "raiz_permitida", "sandbox_habilitado", "callback_confirmacion",
    "audit_log", "timeout", "confirmar", "env_extra", "cwd",
})


# ---------------------------------------------------------------------------
# Estado del grafo
# ---------------------------------------------------------------------------


class AgentState(TypedDict, total=False):
    """Estado completo de una sesión del agente."""

    messages: list[Mensaje]
    current_task: str | None
    current_plan: PlanEjecucion | None
    completed_steps: list[ResultadoPaso]
    failed_steps: list[ResultadoPaso]
    retry_count: int
    replan_count: int
    system_context: dict[str, Any]
    memory_context: str
    waiting_for_user: bool
    paso_pendiente_confirmacion: PasoAccion | None
    abort_reason: str | None
    session_id: str
    indice_paso_actual: int
    tarea_completada: bool


# ---------------------------------------------------------------------------
# Updates al usuario
# ---------------------------------------------------------------------------


class ActualizacionAgente(_PBase):
    """Update emitido por el agente durante la ejecución.

    Ejemplo::
        async for u in agente.run("organiza mis descargas"):
            print(u.tipo, u.progreso)
    """

    tipo: str  # "pensando" | "actuando" | "esperando" | "listo" | "error"
    paso: PasoAccion | None = None
    resultado: ResultadoPaso | None = None
    mensaje: str = ""
    progreso: float = 0.0


# ---------------------------------------------------------------------------
# Agente
# ---------------------------------------------------------------------------


class Agente:
    """Loop principal de JARVIS: percibe → planifica → actúa → reflexiona.

    Ejemplo::
        agente = Agente(planner, reflector, memoria_corto, memoria_ep, auditoria)
        async for u in agente.run("lee el README"):
            print(u.tipo, u.mensaje)
    """

    def __init__(
        self,
        planner: Planner,
        reflector: Reflector,
        memoria_corto: MemoriaCortoPlazo,
        memoria_episodica: MemoriaEpisodica,
        auditoria: AuditLog,
        herramientas: dict[str, Callable[..., Any]] | None = None,
        callback_confirmacion: Callable[[str], asyncio.Future[bool]] | None = None,
        memoria: MemorySystem | None = None,
        mcp_bus: MCPBus | None = None,
    ) -> None:
        self._planner = planner
        self._reflector = reflector
        self._memoria = memoria or MemorySystem()
        self._memoria_corto = memoria_corto or self._memoria._short_term
        self._memoria_episodica = memoria_episodica or self._memoria._episodic
        self._auditoria = auditoria
        self._herramientas: dict[str, Callable[..., Any]] = herramientas or {}
        self._confirmar = callback_confirmacion or _denegar_por_defecto
        self._mcp_bus = mcp_bus

        # Sesiones activas. Cada sesión tiene su propio lock para evitar race conditions
        # entre run(), resume() y cancel() concurrentes.
        self._eventos_resume: dict[str, asyncio.Event] = {}
        self._respuestas_resume: dict[str, bool] = {}
        self._cancelaciones: set[str] = set()
        self._locks_sesion: dict[str, asyncio.Lock] = {}
        self._tareas_paso: dict[str, asyncio.Task[ResultadoPaso]] = {}

        # Grafo LangGraph — compilado para documentación estructural y uso futuro
        self._grafo = _construir_grafo_langgraph(self)

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    async def run(
        self, tarea: str, session_id: str = ""
    ) -> AsyncGenerator[ActualizacionAgente, None]:
        """Ejecuta una tarea y emite actualizaciones por streaming.

        Ejemplo::
            async for u in agente.run("abre Safari"):
                print(u.tipo, u.progreso)
        """
        sid = session_id or uuid4().hex
        evento = asyncio.Event()
        lock = asyncio.Lock()
        self._eventos_resume[sid] = evento
        self._locks_sesion[sid] = lock

        estado: AgentState = {
            "messages": [Mensaje(rol="user", contenido=tarea)],
            "current_task": tarea,
            "current_plan": None,
            "completed_steps": [],
            "failed_steps": [],
            "retry_count": 0,
            "replan_count": 0,
            "system_context": {},
            "memory_context": "",
            "waiting_for_user": False,
            "paso_pendiente_confirmacion": None,
            "abort_reason": None,
            "session_id": sid,
            "indice_paso_actual": 0,
            "tarea_completada": False,
        }
        inicio = time.monotonic()

        await self._auditoria.registrar("tarea_iniciada", {"tarea": tarea, "session_id": sid})
        await self._memoria.store_interaction(tarea, "Inicio de la tarea")

        try:
            # Percibir estado inicial del sistema
            estado = await self._percibir(estado)

            pasos_ejecutados = 0
            replanes = 0

            while True:
                # Comprobaciones de límites y cancelación
                if time.monotonic() - inicio >= TIMEOUT_TAREA_GLOBAL:
                    yield ActualizacionAgente(
                        tipo="error",
                        mensaje=(
                            f"Timeout global: tarea superó "
                            f"{TIMEOUT_TAREA_GLOBAL:.0f}s."
                        ),
                        progreso=1.0,
                    )
                    return

                if sid in self._cancelaciones:
                    yield ActualizacionAgente(tipo="error", mensaje="Tarea cancelada.", progreso=1.0)
                    return

                if estado.get("abort_reason"):
                    yield ActualizacionAgente(
                        tipo="error", mensaje=estado["abort_reason"], progreso=1.0
                    )
                    return

                if pasos_ejecutados >= MAX_PASOS:
                    yield ActualizacionAgente(
                        tipo="error",
                        mensaje=f"Límite de {MAX_PASOS} pasos alcanzado.",
                        progreso=1.0,
                    )
                    return

                # Pensar: planificar si no hay plan, comprobar si está completo
                yield ActualizacionAgente(tipo="pensando", mensaje="Analizando tarea…")
                estado = await self._pensar(estado)

                if estado.get("abort_reason"):
                    continue  # próxima iteración emitirá el error

                plan = estado.get("current_plan")
                if not plan:
                    yield ActualizacionAgente(
                        tipo="error", mensaje="No se pudo generar un plan.", progreso=1.0
                    )
                    return

                completados = estado.get("completed_steps", [])
                if self._reflector.evaluate_task_completion(plan, completados):
                    break

                indice = estado.get("indice_paso_actual", 0)
                if indice >= len(plan.pasos):
                    break

                paso = plan.pasos[indice]
                progreso = indice / max(len(plan.pasos), 1)

                # Confirmación requerida antes de actuar
                if paso.requiere_confirmacion:
                    yield ActualizacionAgente(
                        tipo="esperando",
                        paso=paso,
                        mensaje=f"Confirmación requerida: {paso.descripcion}",
                        progreso=progreso,
                    )
                    await evento.wait()
                    evento.clear()

                    if sid in self._cancelaciones:
                        yield ActualizacionAgente(tipo="error", mensaje="Cancelado.", progreso=1.0)
                        return

                    aprobado = self._respuestas_resume.pop(sid, False)
                    if not aprobado:
                        estado = {**estado, "abort_reason": f"Paso '{paso.id}' rechazado."}
                        continue

                # Actuar
                yield ActualizacionAgente(
                    tipo="actuando",
                    paso=paso,
                    mensaje=paso.descripcion,
                    progreso=progreso,
                )
                resultado = await self._ejecutar_herramienta(paso, sid)
                pasos_ejecutados += 1

                completados_new = list(estado.get("completed_steps", []))
                fallidos_new = list(estado.get("failed_steps", []))
                if resultado.exito:
                    completados_new.append(resultado)
                else:
                    fallidos_new.append(resultado)

                estado = {**estado, "completed_steps": completados_new, "failed_steps": fallidos_new}
                await self._auditoria.registrar(
                    "paso_ejecutado",
                    {"paso": paso.id, "exito": resultado.exito, "error": resultado.error},
                )

                # Reflexionar
                todos = completados_new + fallidos_new
                decision = await self._reflector.reflect(paso, resultado, plan, todos)

                if decision == DecisionReflexion.CONTINUAR:
                    estado = {**estado, "indice_paso_actual": indice + 1, "retry_count": 0}

                elif decision == DecisionReflexion.REINTENTAR:
                    reintentos = estado.get("retry_count", 0) + 1
                    if reintentos > MAX_REINTENTOS:
                        estado = {
                            **estado,
                            "abort_reason": f"Demasiados reintentos en paso '{paso.id}'.",
                        }
                    else:
                        estado = {**estado, "retry_count": reintentos}

                elif decision == DecisionReflexion.REPLANIFICAR:
                    replanes += 1
                    if replanes >= MAX_REPLANES:
                        estado = {**estado, "abort_reason": "Límite de replanes alcanzado."}
                    else:
                        try:
                            nuevo_plan = await self._planner.replan(
                                paso, plan, resultado.error or "fallo desconocido",
                                estado.get("system_context"),
                            )
                            estado = {
                                **estado,
                                "current_plan": nuevo_plan,
                                "indice_paso_actual": 0,
                                "retry_count": 0,
                                "replan_count": replanes,
                            }
                        except Exception as exc:
                            estado = {**estado, "abort_reason": f"Error al replanificar: {exc}"}

                elif decision == DecisionReflexion.ABORTAR:
                    estado = {
                        **estado,
                        "abort_reason": f"Paso '{paso.id}' abortado: {resultado.error}",
                    }

                elif decision == DecisionReflexion.ESPERAR_USUARIO:
                    yield ActualizacionAgente(
                        tipo="esperando",
                        paso=paso,
                        mensaje="Esperando decisión del usuario.",
                        progreso=progreso,
                    )
                    await evento.wait()
                    evento.clear()

                    if sid in self._cancelaciones:
                        yield ActualizacionAgente(tipo="error", mensaje="Cancelado.", progreso=1.0)
                        return

                    aprobado = self._respuestas_resume.pop(sid, False)
                    if aprobado:
                        estado = {**estado, "indice_paso_actual": indice + 1, "retry_count": 0}
                    else:
                        estado = {**estado, "abort_reason": "Usuario rechazó continuar."}

            # Resumen final
            plan = estado.get("current_plan")
            completados = estado.get("completed_steps", [])
            if plan and completados:
                try:
                    resumen = await self._reflector.generate_summary(plan, completados)
                except Exception:
                    log.exception("Error generando resumen final")
                    resumen = "Tarea completada."
            else:
                resumen = "Tarea completada."

            # Guardar episodio en memoria
            if plan and completados:
                try:
                    duracion_ms = int((time.monotonic() - inicio) * 1000)
                    episodio = Episode(
                        task=plan.tarea,
                        plan_used=plan.model_dump() if hasattr(plan, "model_dump") else {},
                        steps_completed=len(completados),
                        steps_failed=len(estado.get("failed_steps", [])),
                        outcome="success",
                        duration_ms=duracion_ms,
                        error_summary=None,
                        lessons=[],
                        created_at=datetime.now(UTC),
                    )
                    await self._memoria.record_episode(episodio)
                except Exception:
                    log.exception("Error guardando episodio en memoria")

            yield ActualizacionAgente(tipo="listo", mensaje=resumen, progreso=1.0)

        finally:
            self._eventos_resume.pop(sid, None)
            self._respuestas_resume.pop(sid, None)
            self._cancelaciones.discard(sid)
            self._locks_sesion.pop(sid, None)
            self._tareas_paso.pop(sid, None)

    async def resume(self, session_id: str, respuesta: str) -> bool:
        """Reanuda un agente en estado WAIT_USER.

        Ejemplo::
            ok = await agente.resume(sid, "si")
        """
        lock = self._locks_sesion.get(session_id)
        if lock is None:
            return False
        async with lock:
            if session_id not in self._eventos_resume:
                return False
            aprobado = respuesta.strip().lower() in ("si", "sí", "yes", "ok", "s", "y")
            self._respuestas_resume[session_id] = aprobado
            self._eventos_resume[session_id].set()
        return True

    async def cancel(self, session_id: str) -> bool:
        """Cancela la tarea activa de forma segura, abortando la herramienta en curso.

        Ejemplo::
            ok = await agente.cancel(sid)
        """
        lock = self._locks_sesion.get(session_id)
        if lock is None:
            return False
        async with lock:
            if session_id not in self._eventos_resume:
                return False
            self._cancelaciones.add(session_id)
            # Abortar la herramienta activa si existe
            tarea_activa = self._tareas_paso.get(session_id)
            if tarea_activa and not tarea_activa.done():
                tarea_activa.cancel()
            self._respuestas_resume[session_id] = False
            self._eventos_resume[session_id].set()
        return True

    # ------------------------------------------------------------------
    # Nodos internos
    # ------------------------------------------------------------------

    async def _percibir(self, state: AgentState) -> AgentState:
        """Captura estado del sistema."""
        try:
            from perception.system_state import get_system_state
            sistema = await get_system_state()
            contexto: dict[str, Any] = {
                "apps_activas": sistema.active_apps[:5] if getattr(sistema, "active_apps", None) else [],
                "bateria": getattr(sistema, "battery_percent", None),
                "memoria_mb": getattr(sistema, "memory_used_mb", None),
            }
        except Exception:
            log.debug("No se pudo capturar estado del sistema (normal en CI)")
            contexto = {}
        tarea = state.get("current_task", "") or ""
        try:
            memoria_contexto = await self._memoria.get_context(
                tarea, settings.short_term_max_tokens
            )
        except Exception as exc:
            log.debug("No se pudo preparar contexto de memoria: %s", exc)
            memoria_contexto = ""
        return {**state, "system_context": contexto, "memory_context": memoria_contexto}

    async def _pensar(self, state: AgentState) -> AgentState:
        """Genera o valida el plan actual."""
        plan = state.get("current_plan")
        tarea = state.get("current_task", "")
        if plan is None:
            try:
                workflow = await self._memoria.find_workflow(tarea)
                contexto = {
                    **state.get("system_context", {}),
                    "memoria": state.get("memory_context", ""),
                }
                if workflow:
                    contexto["workflow"] = {
                        "name": workflow.name,
                        "description": workflow.description,
                        "trigger_patterns": workflow.trigger_patterns,
                    }
                nuevo_plan = await self._planner.plan(tarea, contexto=contexto)
                errores = self._planner.validate_plan(nuevo_plan)
                if errores:
                    log.warning("Errores de validación en plan: %s", errores)
                await self._memoria.store_interaction(tarea, f"Plan generado: {nuevo_plan}")
                return {**state, "current_plan": nuevo_plan, "indice_paso_actual": 0}
            except Exception as exc:
                return {**state, "abort_reason": f"Error al planificar: {exc}"}
        return state

    # ------------------------------------------------------------------
    # Ejecución de herramientas
    # ------------------------------------------------------------------

    async def _ejecutar_herramienta(
        self, paso: PasoAccion, session_id: str = ""
    ) -> ResultadoPaso:
        """Llama a la función registrada para la herramienta del paso.

        Valida que ningún parámetro sobreescriba kwargs internos de seguridad.
        """
        inicio = time.monotonic()
        try:
            fn = self._herramientas.get(paso.herramienta)
            if fn is None and self._mcp_bus is None:
                raise KeyError(f"Herramienta no registrada: {paso.herramienta}")

            # Rechazar claves que podrían sobreescribir defaults de seguridad
            claves_prohibidas = _PARAMS_PROHIBIDOS & set(paso.parametros)
            if claves_prohibidas:
                raise ValueError(
                    f"Parámetros prohibidos en '{paso.herramienta}': {claves_prohibidas}"
                )

            if fn is None:
                assert self._mcp_bus is not None
                tarea_mcp: asyncio.Task[object] = asyncio.create_task(
                    self._mcp_bus.execute(
                        paso.herramienta,
                        paso.parametros,
                        session_id=session_id,
                        requires_confirmation=paso.requiere_confirmacion,
                    )
                )
                if session_id:
                    self._tareas_paso[session_id] = tarea_mcp  # type: ignore[assignment]
                resultado_mcp = await tarea_mcp
                duracion = int((time.monotonic() - inicio) * 1000)
                return ResultadoPaso(
                    id_paso=paso.id,
                    exito=resultado_mcp.success,
                    salida=resultado_mcp.data,
                    error=resultado_mcp.error,
                    duracion_ms=duracion,
                    efectos_secundarios=resultado_mcp.side_effects,
                )

            if asyncio.iscoroutinefunction(fn):
                coro = fn(**paso.parametros)
            else:
                coro = asyncio.to_thread(fn, **paso.parametros)

            tarea: asyncio.Task[object] = asyncio.create_task(
                asyncio.wait_for(coro, timeout=TIMEOUT_PASO)
            )
            if session_id:
                self._tareas_paso[session_id] = tarea  # type: ignore[assignment]

            salida = await tarea
            duracion = int((time.monotonic() - inicio) * 1000)
            return ResultadoPaso(id_paso=paso.id, exito=True, salida=salida, duracion_ms=duracion)

        except TimeoutError:
            duracion = int((time.monotonic() - inicio) * 1000)
            return ResultadoPaso(
                id_paso=paso.id,
                exito=False,
                error=f"TimeoutError: paso superó {TIMEOUT_PASO:.0f}s",
                duracion_ms=duracion,
            )
        except asyncio.CancelledError:
            duracion = int((time.monotonic() - inicio) * 1000)
            return ResultadoPaso(
                id_paso=paso.id,
                exito=False,
                error="CancelledError: paso cancelado por el usuario",
                duracion_ms=duracion,
            )
        except Exception as exc:
            duracion = int((time.monotonic() - inicio) * 1000)
            return ResultadoPaso(
                id_paso=paso.id,
                exito=False,
                error=f"{type(exc).__name__}: {exc}",
                duracion_ms=duracion,
            )
        finally:
            if session_id:
                self._tareas_paso.pop(session_id, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _denegar_por_defecto(descripcion: str) -> bool:
    """Deniega confirmaciones cuando no hay callback explícito.

    Args:
        descripcion: Descripción de la acción que solicita autorización.

    Returns:
        Siempre `False` para mantener comportamiento fail-closed.
    """
    return False


def _construir_grafo_langgraph(agente: Agente) -> object | None:
    """Compila el grafo LangGraph. Devuelve None si langgraph no está disponible."""
    try:
        from langgraph.checkpoint.memory import MemorySaver
        from langgraph.graph import END, StateGraph

        builder: StateGraph = StateGraph(AgentState)
        builder.add_node("percibir", agente._percibir)
        builder.add_node("pensar", agente._pensar)
        builder.add_node("responder", lambda s: s)  # nodo terminal

        builder.set_entry_point("percibir")
        builder.add_edge("percibir", "pensar")
        builder.add_conditional_edges(
            "pensar",
            lambda s: "responder" if s.get("abort_reason") or s.get("tarea_completada") else "pensar",
            {"responder": "responder", "pensar": "pensar"},
        )
        builder.add_edge("responder", END)

        return builder.compile(checkpointer=MemorySaver())
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Alias de compatibilidad con la interfaz anterior de Agente
# ---------------------------------------------------------------------------


# El antiguo EstadoAgente queda reemplazado por AgentState (TypedDict).
# La antigua interfaz procesar()/stream() no se mantiene — usar run().
