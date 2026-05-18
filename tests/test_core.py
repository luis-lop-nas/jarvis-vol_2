"""Tests del núcleo del agente: planner, reflector y agent loop.

Todos los tests mockean modelos de IA y acciones — ninguno llama a APIs reales.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.planner import PasoAccion, PlanEjecucion, Planner, _tiene_ciclo
from core.reflector import DecisionReflexion, Reflector, ResultadoPaso

# ---------------------------------------------------------------------------
# Helpers de fixtures
# ---------------------------------------------------------------------------


def _paso(id: str, herramienta: str = "filesystem.leer", confirmacion: bool = False, puede_fallar: bool = False) -> PasoAccion:
    return PasoAccion(
        id=id,
        descripcion=f"Ejecutar {id}",
        herramienta=herramienta,
        parametros={},
        requiere_confirmacion=confirmacion,
        puede_fallar=puede_fallar,
    )


def _plan(*pasos: PasoAccion, tarea: str = "test") -> PlanEjecucion:
    return PlanEjecucion(tarea=tarea, pasos=list(pasos))


def _resultado(id_paso: str, exito: bool = True, error: str | None = None) -> ResultadoPaso:
    return ResultadoPaso(id_paso=id_paso, exito=exito, error=error, duracion_ms=10)


def _mock_modelo(respuesta: str = "{}") -> MagicMock:
    modelo = MagicMock()
    from models.base import ModelResponse
    modelo.complete = AsyncMock(
        return_value=ModelResponse(content=respuesta, model="mock")
    )
    return modelo


def _mock_auditoria() -> MagicMock:
    audit = MagicMock()
    audit.registrar = AsyncMock()
    return audit


def _mock_memoria() -> MagicMock:
    mem = MagicMock()
    mem.registrar = AsyncMock()
    mem.guardar_aprendizaje = AsyncMock()
    return mem


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


class TestPlanner:

    @pytest.mark.asyncio
    async def test_planner_simple_task(self) -> None:
        """Tarea simple → plan válido con al menos un paso."""
        json_plan = """
        {
          "objetivo": "Leer README",
          "pasos": [
            {
              "id": "leer",
              "descripcion": "Lee el README",
              "herramienta": "filesystem.leer",
              "parametros": {"ruta": "~/README.md"},
              "requiere_confirmacion": false,
              "depende_de": [],
              "duracion_estimada_ms": 100,
              "puede_fallar": false
            }
          ]
        }
        """
        planner = Planner(_mock_modelo(json_plan))
        plan = await planner.plan("Lee el README.md")

        assert isinstance(plan, PlanEjecucion)
        assert len(plan.pasos) == 1
        assert plan.pasos[0].herramienta == "filesystem.leer"
        assert plan.modelo_usado == "mock"

    @pytest.mark.asyncio
    async def test_planner_destructive_requires_confirmation(self) -> None:
        """Herramienta destructiva → validate_plan detecta confirmación faltante."""
        planner = Planner(_mock_modelo("{}"))
        plan = _plan(
            PasoAccion(
                id="borrar",
                descripcion="Borra el archivo",
                herramienta="filesystem.eliminar",
                parametros={"ruta": "~/tmp.txt"},
                requiere_confirmacion=False,  # ← incorrecto intencionalmente
            )
        )
        errores = planner.validate_plan(plan)
        assert any("requiere_confirmacion" in e for e in errores)

    def test_planner_validate_no_cycles(self) -> None:
        """Plan con dependencia circular → validate_plan detecta el ciclo."""
        grafo = {"a": ["b"], "b": ["c"], "c": ["a"]}
        assert _tiene_ciclo(grafo) is True

    def test_planner_validate_no_cycles_valido(self) -> None:
        """Plan sin ciclo → validate_plan no reporta errores de ciclo."""
        grafo = {"a": [], "b": ["a"], "c": ["b"]}
        assert _tiene_ciclo(grafo) is False

    def test_estimate_complexity_trivial(self) -> None:
        planner = Planner(_mock_modelo())
        c = planner.estimate_complexity("abre Safari")
        assert c < 0.3

    def test_estimate_complexity_alta(self) -> None:
        planner = Planner(_mock_modelo())
        c = planner.estimate_complexity(
            "implementa y diseña un servidor HTTP con autenticación, optimiza la base de datos "
            "y crea tests que analicen el rendimiento con más de veinte palabras en total"
        )
        assert c >= 0.3

    @pytest.mark.asyncio
    async def test_planner_replan(self) -> None:
        """replan genera un plan alternativo usando el modelo."""
        json_nuevo = """
        {
          "objetivo": "Alternativa",
          "pasos": [{"id": "alt", "descripcion": "Paso alternativo",
                     "herramienta": "filesystem.leer", "parametros": {},
                     "requiere_confirmacion": false, "depende_de": [],
                     "duracion_estimada_ms": 100, "puede_fallar": true}]
        }
        """
        planner = Planner(_mock_modelo(json_nuevo))
        paso_fallido = _paso("fallo", "terminal.ejecutar")
        plan_original = _plan(paso_fallido)
        nuevo = await planner.replan(paso_fallido, plan_original, "FileNotFoundError")

        assert isinstance(nuevo, PlanEjecucion)
        assert nuevo.pasos[0].id == "alt"


# ---------------------------------------------------------------------------
# Reflector
# ---------------------------------------------------------------------------


class TestReflector:

    def _reflector(self) -> Reflector:
        return Reflector(_mock_modelo("continuar"))

    @pytest.mark.asyncio
    async def test_reflector_retry_on_error(self) -> None:
        """Resultado fallido sin error crítico → REINTENTAR (< MAX_REINTENTOS)."""
        ref = self._reflector()
        paso = _paso("p1")
        resultado = _resultado("p1", exito=False, error="CalledProcessError: returncode 1")
        plan = _plan(paso)

        decision = await ref.reflect(paso, resultado, plan, [])
        assert decision == DecisionReflexion.REINTENTAR

    @pytest.mark.asyncio
    async def test_reflector_abort_on_permission(self) -> None:
        """PermissionError → ABORTAR."""
        ref = self._reflector()
        paso = _paso("p1")
        resultado = _resultado("p1", exito=False, error="PermissionError: acceso denegado")
        plan = _plan(paso)

        decision = await ref.reflect(paso, resultado, plan, [])
        assert decision == DecisionReflexion.ABORTAR

    @pytest.mark.asyncio
    async def test_reflector_replan_after_max_retries(self) -> None:
        """Tres fallos consecutivos del mismo paso → REPLANIFICAR."""
        ref = self._reflector()
        paso = _paso("p1")
        plan = _plan(paso)
        historial = [_resultado("p1", exito=False, error="fallo") for _ in range(Reflector.MAX_REINTENTOS)]

        decision = await ref.reflect(paso, _resultado("p1", exito=False, error="fallo"), plan, historial)
        assert decision == DecisionReflexion.REPLANIFICAR

    @pytest.mark.asyncio
    async def test_reflector_continua_si_exito(self) -> None:
        ref = self._reflector()
        paso = _paso("p1")
        resultado = _resultado("p1", exito=True)
        decision = await ref.reflect(paso, resultado, _plan(paso), [])
        assert decision == DecisionReflexion.CONTINUAR

    @pytest.mark.asyncio
    async def test_reflector_replan_on_file_not_found(self) -> None:
        ref = self._reflector()
        paso = _paso("p1")
        resultado = _resultado("p1", exito=False, error="FileNotFoundError: archivo no existe")
        decision = await ref.reflect(paso, resultado, _plan(paso), [])
        assert decision == DecisionReflexion.REPLANIFICAR

    def test_evaluate_task_completion_completa(self) -> None:
        ref = self._reflector()
        pasos = [_paso("a"), _paso("b")]
        plan = _plan(*pasos)
        resultados = [_resultado("a"), _resultado("b")]
        assert ref.evaluate_task_completion(plan, resultados) is True

    def test_evaluate_task_completion_incompleta(self) -> None:
        ref = self._reflector()
        pasos = [_paso("a"), _paso("b")]
        plan = _plan(*pasos)
        resultados = [_resultado("a")]
        assert ref.evaluate_task_completion(plan, resultados) is False

    def test_evaluate_task_completion_puede_fallar(self) -> None:
        """Un paso con puede_fallar=True no bloquea la completitud."""
        ref = self._reflector()
        pasos = [_paso("a"), _paso("b", puede_fallar=True)]
        plan = _plan(*pasos)
        resultados = [_resultado("a")]  # "b" no completado pero puede_fallar=True
        assert ref.evaluate_task_completion(plan, resultados) is True


# ---------------------------------------------------------------------------
# Agente
# ---------------------------------------------------------------------------


def _make_agente(herramientas=None, plan_respuesta=None, reflection_respuesta=None):
    """Construye un Agente con todos los colaboradores mockeados."""
    from core.agent import Agente
    from memory.short_term import MemoriaCortoPlazo

    json_plan = plan_respuesta or """
    {
      "objetivo": "test",
      "pasos": [{"id": "p1", "descripcion": "Paso 1",
                 "herramienta": "filesystem.leer", "parametros": {},
                 "requiere_confirmacion": false, "depende_de": [],
                 "duracion_estimada_ms": 100, "puede_fallar": false}]
    }
    """
    from models.base import ModelResponse
    modelo_plan = MagicMock()
    modelo_plan.complete = AsyncMock(return_value=ModelResponse(content=json_plan, model="mock"))

    modelo_ref = MagicMock()
    modelo_ref.complete = AsyncMock(return_value=ModelResponse(content="continuar", model="mock"))

    planner = Planner(modelo_plan)
    reflector = Reflector(modelo_ref)

    memoria_corto = MemoriaCortoPlazo()
    memoria_ep = _mock_memoria()
    audit = _mock_auditoria()

    herrs = herramientas or {"filesystem.leer": AsyncMock(return_value="contenido")}

    return Agente(
        planner=planner,
        reflector=reflector,
        memoria_corto=memoria_corto,
        memoria_episodica=memoria_ep,
        auditoria=audit,
        herramientas=herrs,
    )


class TestAgente:

    @pytest.mark.asyncio
    async def test_agent_streaming(self) -> None:
        """run() emite ActualizacionAgente con distintos tipos progresivamente."""

        agente = _make_agente()
        # Mockear reflector para que devuelva CONTINUAR (no REINTENTAR que loop)
        agente._reflector.reflect = AsyncMock(return_value=DecisionReflexion.CONTINUAR)
        agente._reflector.evaluate_task_completion = MagicMock(side_effect=[False, True])
        agente._reflector.generate_summary = AsyncMock(return_value="Tarea completada con éxito.")

        actualizaciones = []
        async for u in agente.run("lee el README"):
            actualizaciones.append(u)

        tipos = [u.tipo for u in actualizaciones]
        assert "pensando" in tipos
        assert "actuando" in tipos
        assert "listo" in tipos

    @pytest.mark.asyncio
    async def test_agent_max_steps(self) -> None:
        """Superar MAX_PASOS → tipo=error con mensaje de límite."""
        import core.agent as agent_module

        agente = _make_agente()
        agente._reflector.reflect = AsyncMock(return_value=DecisionReflexion.CONTINUAR)
        agente._reflector.evaluate_task_completion = MagicMock(return_value=False)

        with patch.object(agent_module, "MAX_PASOS", 1):
            actualizaciones = []
            async for u in agente.run("tarea infinita"):
                actualizaciones.append(u)
                if len(actualizaciones) > 20:
                    break

        assert any(u.tipo == "error" and "Límite" in u.mensaje for u in actualizaciones)

    @pytest.mark.asyncio
    async def test_agent_cancel(self) -> None:
        """cancel() detiene el loop limpiamente."""
        agente = _make_agente()
        agente._reflector.reflect = AsyncMock(return_value=DecisionReflexion.CONTINUAR)
        agente._reflector.evaluate_task_completion = MagicMock(return_value=False)

        sid = "sesion-cancel"
        actualizaciones: list = []

        async def _ejecutar():
            async for u in agente.run("tarea larga", session_id=sid):
                actualizaciones.append(u)

        task = asyncio.create_task(_ejecutar())
        await asyncio.sleep(0)  # dejar arrancar el generador
        await agente.cancel(sid)
        await asyncio.wait_for(task, timeout=3.0)

        assert any(u.tipo == "error" for u in actualizaciones)

    @pytest.mark.asyncio
    async def test_agent_wait_user(self) -> None:
        """Paso con requiere_confirmacion → tipo=esperando emitido."""
        json_plan = """
        {
          "objetivo": "test",
          "pasos": [{"id": "p1", "descripcion": "Borrar archivo",
                     "herramienta": "filesystem.eliminar", "parametros": {},
                     "requiere_confirmacion": true, "depende_de": [],
                     "duracion_estimada_ms": 100, "puede_fallar": false}]
        }
        """
        from models.base import ModelResponse
        modelo = MagicMock()
        modelo.complete = AsyncMock(return_value=ModelResponse(content=json_plan, model="mock"))
        from core.agent import Agente
        from memory.short_term import MemoriaCortoPlazo

        agente = Agente(
            planner=Planner(modelo),
            reflector=Reflector(modelo),
            memoria_corto=MemoriaCortoPlazo(),
            memoria_episodica=_mock_memoria(),
            auditoria=_mock_auditoria(),
            herramientas={"filesystem.eliminar": AsyncMock(return_value=True)},
        )
        agente._reflector.evaluate_task_completion = MagicMock(return_value=False)

        sid = "sesion-wait"
        actualizaciones: list = []

        async def _ejecutar():
            async for u in agente.run("borra el archivo", session_id=sid):
                actualizaciones.append(u)
                if u.tipo == "esperando":
                    # Cancelar tras detectar la espera
                    await agente.cancel(sid)

        await asyncio.wait_for(_ejecutar(), timeout=5.0)
        assert any(u.tipo == "esperando" for u in actualizaciones)

    @pytest.mark.asyncio
    async def test_agent_resume(self) -> None:
        """resume('si') después de esperar confirmación continúa la ejecución."""
        json_plan = """
        {
          "objetivo": "test",
          "pasos": [{"id": "p1", "descripcion": "Borrar archivo",
                     "herramienta": "filesystem.eliminar", "parametros": {},
                     "requiere_confirmacion": true, "depende_de": [],
                     "duracion_estimada_ms": 100, "puede_fallar": false}]
        }
        """
        from models.base import ModelResponse
        modelo = MagicMock()
        modelo.complete = AsyncMock(return_value=ModelResponse(content=json_plan, model="mock"))
        from core.agent import Agente
        from memory.short_term import MemoriaCortoPlazo

        herramienta_mock = AsyncMock(return_value=True)
        agente = Agente(
            planner=Planner(modelo),
            reflector=Reflector(modelo),
            memoria_corto=MemoriaCortoPlazo(),
            memoria_episodica=_mock_memoria(),
            auditoria=_mock_auditoria(),
            herramientas={"filesystem.eliminar": herramienta_mock},
        )
        agente._reflector.reflect = AsyncMock(return_value=DecisionReflexion.CONTINUAR)
        agente._reflector.evaluate_task_completion = MagicMock(side_effect=[False, True])
        agente._reflector.generate_summary = AsyncMock(return_value="Archivo borrado.")

        sid = "sesion-resume"
        actualizaciones: list = []

        async def _ejecutar():
            async for u in agente.run("borra el archivo", session_id=sid):
                actualizaciones.append(u)
                if u.tipo == "esperando":
                    await agente.resume(sid, "si")

        await asyncio.wait_for(_ejecutar(), timeout=5.0)

        assert any(u.tipo == "listo" for u in actualizaciones)
        herramienta_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_full_loop_simple(self) -> None:
        """Tarea 'lee este archivo' end-to-end con herramienta mockeada."""
        agente = _make_agente(
            herramientas={"filesystem.leer": AsyncMock(return_value="Contenido del archivo.")}
        )
        agente._reflector.reflect = AsyncMock(return_value=DecisionReflexion.CONTINUAR)
        agente._reflector.evaluate_task_completion = MagicMock(side_effect=[False, True])
        agente._reflector.generate_summary = AsyncMock(return_value="Leí el archivo correctamente.")

        actualizaciones = []
        async for u in agente.run("lee el archivo README.md"):
            actualizaciones.append(u)

        ultimo = actualizaciones[-1]
        assert ultimo.tipo == "listo"
        assert "Leí" in ultimo.mensaje or ultimo.progreso == 1.0
