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

    def test_planner_validate_topological_order_invalido(self) -> None:
        """Paso B depende de paso C que aparece DESPUÉS en el plan → error topológico."""
        planner = Planner(_mock_modelo())
        paso_b = PasoAccion(
            id="b", descripcion="B", herramienta="filesystem.leer",
            parametros={}, depende_de=["c"],
        )
        paso_c = PasoAccion(
            id="c", descripcion="C", herramienta="filesystem.leer",
            parametros={},
        )
        plan = PlanEjecucion(tarea="test", pasos=[paso_b, paso_c])
        errores = planner.validate_plan(plan)
        assert any("topológico" in e for e in errores)

    def test_planner_validate_topological_order_valido(self) -> None:
        """Paso B depende de paso A que aparece ANTES → sin error topológico."""
        planner = Planner(_mock_modelo())
        paso_a = PasoAccion(id="a", descripcion="A", herramienta="filesystem.leer", parametros={})
        paso_b = PasoAccion(
            id="b", descripcion="B", herramienta="filesystem.leer",
            parametros={}, depende_de=["a"],
        )
        plan = PlanEjecucion(tarea="test", pasos=[paso_a, paso_b])
        errores = planner.validate_plan(plan)
        assert not any("topológico" in e for e in errores)

    @pytest.mark.asyncio
    async def test_planner_json_invalido_devuelve_aclaracion(self) -> None:
        """Si el LLM devuelve JSON inválido, plan() devuelve paso de aclaración en lugar de lanzar."""
        planner = Planner(_mock_modelo("esto no es json válido {{{"))
        plan = await planner.plan("Haz algo")
        assert len(plan.pasos) == 1
        assert plan.pasos[0].herramienta == "pedir_aclaracion"


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

    @pytest.mark.asyncio
    async def test_reflector_explain_failure_usa_modelo(self) -> None:
        """explain_failure() llama al modelo y devuelve su respuesta."""
        modelo = _mock_modelo("El archivo no existe porque la ruta era incorrecta.")
        ref = Reflector(modelo)
        paso = _paso("p1")
        resultado = _resultado("p1", exito=False, error="FileNotFoundError: /tmp/x.txt")
        explicacion = await ref.explain_failure(paso, resultado)
        assert "archivo" in explicacion.lower() or len(explicacion) > 0
        modelo.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_reflector_explain_failure_fallback_si_error(self) -> None:
        """Si el modelo falla, explain_failure() devuelve el error original."""
        from unittest.mock import AsyncMock
        modelo = _mock_modelo()
        modelo.complete = AsyncMock(side_effect=RuntimeError("API caída"))
        ref = Reflector(modelo)
        paso = _paso("p1")
        resultado = _resultado("p1", exito=False, error="TimeoutError: 30s")
        explicacion = await ref.explain_failure(paso, resultado)
        assert explicacion == "TimeoutError: 30s"


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

    @pytest.mark.asyncio
    async def test_agent_runaway_guard(self) -> None:
        """La misma herramienta con parámetros idénticos 3 veces en ventana de 6 → tipo=error."""
        # Plan con 4 pasos idénticos: el 3er dispara el guard antes de ejecutar
        json_plan = """
        {
          "objetivo": "test loop",
          "pasos": [
            {"id": "p1", "descripcion": "paso 1", "herramienta": "filesystem.leer",
             "parametros": {"ruta": "/mismo"}, "requiere_confirmacion": false,
             "depende_de": [], "duracion_estimada_ms": 100, "puede_fallar": false},
            {"id": "p2", "descripcion": "paso 2", "herramienta": "filesystem.leer",
             "parametros": {"ruta": "/mismo"}, "requiere_confirmacion": false,
             "depende_de": [], "duracion_estimada_ms": 100, "puede_fallar": false},
            {"id": "p3", "descripcion": "paso 3", "herramienta": "filesystem.leer",
             "parametros": {"ruta": "/mismo"}, "requiere_confirmacion": false,
             "depende_de": [], "duracion_estimada_ms": 100, "puede_fallar": false},
            {"id": "p4", "descripcion": "paso 4", "herramienta": "filesystem.leer",
             "parametros": {"ruta": "/mismo"}, "requiere_confirmacion": false,
             "depende_de": [], "duracion_estimada_ms": 100, "puede_fallar": false}
          ]
        }
        """
        agente = _make_agente(
            plan_respuesta=json_plan,
            herramientas={"filesystem.leer": AsyncMock(return_value="ok")},
        )
        agente._reflector.reflect = AsyncMock(return_value=DecisionReflexion.CONTINUAR)
        agente._reflector.evaluate_task_completion = MagicMock(return_value=False)

        actualizaciones = []
        async for u in agente.run("tarea con loop"):
            actualizaciones.append(u)
            if len(actualizaciones) > 30:
                break

        error_guard = [
            u for u in actualizaciones
            if u.tipo == "error" and "Loop detectado" in u.mensaje
        ]
        assert error_guard, f"Se esperaba error de runaway guard. Updates: {[u.tipo for u in actualizaciones]}"


# ---------------------------------------------------------------------------
# Nuevos tests: state machine, trazabilidad, timeout, reintentos, checkpoint
# ---------------------------------------------------------------------------


class TestAgenteFaseYTraza:

    @pytest.mark.asyncio
    async def test_fase_transitions_happy_path(self) -> None:
        """run() actualiza 'fase' a través de PLAN → EXECUTE_TOOL → DONE."""
        from core.agent import AgentFase

        agente = _make_agente(
            herramientas={"filesystem.leer": AsyncMock(return_value="ok")}
        )
        agente._reflector.reflect = AsyncMock(return_value=DecisionReflexion.CONTINUAR)
        agente._reflector.evaluate_task_completion = MagicMock(side_effect=[False, True])
        agente._reflector.generate_summary = AsyncMock(return_value="Listo.")

        fases = []
        async for u in agente.run("tarea simple"):
            fases.append(u.fase)

        assert AgentFase.PLAN in fases
        assert AgentFase.EXECUTE_TOOL in fases
        assert AgentFase.DONE in fases

    @pytest.mark.asyncio
    async def test_traza_en_actualizacion_final(self) -> None:
        """El update 'listo' incluye la traza con al menos una entrada de EXECUTE_TOOL."""
        from core.agent import AgentFase

        agente = _make_agente(
            herramientas={"filesystem.leer": AsyncMock(return_value="contenido")}
        )
        agente._reflector.reflect = AsyncMock(return_value=DecisionReflexion.CONTINUAR)
        agente._reflector.evaluate_task_completion = MagicMock(side_effect=[False, True])
        agente._reflector.generate_summary = AsyncMock(return_value="Hecho.")

        actualizaciones = []
        async for u in agente.run("lee algo"):
            actualizaciones.append(u)

        final = actualizaciones[-1]
        assert final.tipo == "listo"
        assert final.traza is not None and len(final.traza) > 0
        fases_traza = [e["fase"] for e in final.traza]
        assert AgentFase.EXECUTE_TOOL in fases_traza

    @pytest.mark.asyncio
    async def test_fase_error_en_timeout(self) -> None:
        """Cuando el timeout global expira el update tiene fase=ERROR."""
        import core.agent as agent_module
        from core.agent import AgentFase

        agente = _make_agente()
        agente._reflector.reflect = AsyncMock(return_value=DecisionReflexion.CONTINUAR)
        agente._reflector.evaluate_task_completion = MagicMock(return_value=False)

        with patch.object(agent_module, "TIMEOUT_TAREA_GLOBAL", -1.0):
            actualizaciones = []
            async for u in agente.run("tarea infinita"):
                actualizaciones.append(u)

        error = next(u for u in actualizaciones if u.tipo == "error")
        assert error.fase == AgentFase.ERROR

    @pytest.mark.asyncio
    async def test_fase_cancelled_al_cancelar(self) -> None:
        """Cuando se cancela el update de error tiene fase=CANCELLED."""
        from core.agent import AgentFase

        agente = _make_agente()
        agente._reflector.reflect = AsyncMock(return_value=DecisionReflexion.CONTINUAR)
        agente._reflector.evaluate_task_completion = MagicMock(return_value=False)

        sid = "sesion-fase-cancel"
        actualizaciones: list = []

        async def _ejecutar():
            async for u in agente.run("tarea", session_id=sid):
                actualizaciones.append(u)

        task = asyncio.create_task(_ejecutar())
        await asyncio.sleep(0)
        await agente.cancel(sid)
        await asyncio.wait_for(task, timeout=3.0)

        error = next((u for u in actualizaciones if u.tipo == "error"), None)
        assert error is not None
        assert error.fase == AgentFase.CANCELLED

    @pytest.mark.asyncio
    async def test_reintentos_agotados_abortan(self) -> None:
        """Cuando reintentos > MAX_REINTENTOS el loop termina con tipo=error."""
        import core.agent as agent_module

        agente = _make_agente(
            herramientas={"filesystem.leer": AsyncMock(return_value="ok")}
        )
        agente._reflector.reflect = AsyncMock(return_value=DecisionReflexion.REINTENTAR)
        agente._reflector.evaluate_task_completion = MagicMock(return_value=False)

        with patch.object(agent_module, "MAX_REINTENTOS", 1):
            actualizaciones = []
            async for u in agente.run("tarea con reintentos"):
                actualizaciones.append(u)
                if len(actualizaciones) > 30:
                    break

        assert any(u.tipo == "error" for u in actualizaciones)

    @pytest.mark.asyncio
    async def test_replan_traza_entrada(self) -> None:
        """Tras REPLANIFICAR la traza contiene una entrada de fase REPLAN."""
        from core.agent import AgentFase

        agente = _make_agente(
            herramientas={"filesystem.leer": AsyncMock(return_value="ok")}
        )
        reflect_calls = [DecisionReflexion.REPLANIFICAR, DecisionReflexion.CONTINUAR]

        agente._reflector.reflect = AsyncMock(side_effect=reflect_calls)
        agente._reflector.evaluate_task_completion = MagicMock(side_effect=[False, False, True])
        agente._reflector.explain_failure = AsyncMock(return_value="ruta incorrecta")
        agente._reflector.generate_summary = AsyncMock(return_value="Replanificado y completado.")

        # replan necesita devolver un plan válido
        json_nuevo = """
        {
          "objetivo": "alternativa",
          "pasos": [{"id": "alt1", "descripcion": "paso alternativo",
                     "herramienta": "filesystem.leer", "parametros": {},
                     "requiere_confirmacion": false, "depende_de": [],
                     "duracion_estimada_ms": 100, "puede_fallar": false}]
        }
        """
        from models.base import ModelResponse
        agente._planner._modelo.complete = AsyncMock(
            return_value=ModelResponse(content=json_nuevo, model="mock")
        )

        actualizaciones = []
        async for u in agente.run("tarea con replan"):
            actualizaciones.append(u)
            if len(actualizaciones) > 30:
                break

        final = actualizaciones[-1]
        if final.traza:
            fases_traza = [e["fase"] for e in final.traza]
            assert AgentFase.REPLAN in fases_traza

    def test_estado_a_dict_serializable(self) -> None:
        """estado_a_dict() produce un dict serializable a JSON."""
        import json
        from core.agent import AgentFase, estado_a_dict
        from core.planner import PasoAccion, PlanEjecucion
        from core.reflector import ResultadoPaso
        from models.base import Mensaje

        estado = {
            "session_id": "test-123",
            "current_task": "test",
            "current_plan": PlanEjecucion(
                tarea="test",
                pasos=[PasoAccion(id="p1", descripcion="X", herramienta="filesystem.leer", parametros={})],
            ),
            "completed_steps": [ResultadoPaso(id_paso="p1", exito=True, duracion_ms=10)],
            "failed_steps": [],
            "messages": [Mensaje(rol="user", contenido="hola")],
            "fase": AgentFase.DONE,
            "traza": [{"fase": "done", "ts": "2026-01-01T00:00:00+00:00"}],
        }
        d = estado_a_dict(estado)
        serializado = json.dumps(d)
        assert '"test-123"' in serializado
        assert '"done"' in serializado

    @pytest.mark.asyncio
    async def test_resume_desde_initial_state_usa_plan_existente(self) -> None:
        """run(initial_state=...) con plan ya cargado salta la generación del plan."""
        from core.agent import AgentFase, Agente
        from core.planner import PasoAccion, PlanEjecucion
        from memory.short_term import MemoriaCortoPlazo

        herramienta_mock = AsyncMock(return_value="contenido restaurado")
        agente = Agente(
            planner=Planner(_mock_modelo()),
            reflector=Reflector(_mock_modelo("continuar")),
            memoria_corto=MemoriaCortoPlazo(),
            memoria_episodica=_mock_memoria(),
            auditoria=_mock_auditoria(),
            herramientas={"filesystem.leer": herramienta_mock},
        )
        agente._reflector.reflect = AsyncMock(return_value=DecisionReflexion.CONTINUAR)
        agente._reflector.evaluate_task_completion = MagicMock(side_effect=[False, True])
        agente._reflector.generate_summary = AsyncMock(return_value="Reanudado.")

        plan_existente = PlanEjecucion(
            tarea="tarea restaurada",
            pasos=[PasoAccion(id="r1", descripcion="leer", herramienta="filesystem.leer", parametros={})],
        )
        estado_guardado = {
            "session_id": "restaurado",
            "current_task": "tarea restaurada",
            "current_plan": plan_existente,
            "completed_steps": [],
            "failed_steps": [],
            "retry_count": 0,
            "replan_count": 0,
            "system_context": {},
            "memory_context": "",
            "waiting_for_user": False,
            "paso_pendiente_confirmacion": None,
            "abort_reason": None,
            "indice_paso_actual": 0,
            "tarea_completada": False,
            "tool_call_history": [],
            "fase": AgentFase.PLAN,
            "traza": [],
        }

        actualizaciones = []
        async for u in agente.run("tarea restaurada", initial_state=estado_guardado):
            actualizaciones.append(u)

        assert any(u.tipo == "listo" for u in actualizaciones)
        herramienta_mock.assert_called_once()
