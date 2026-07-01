"""Tests del router (`core/router.py`)."""

from __future__ import annotations

import pytest

from core.router import (
    ContextoRuteo,
    ModeloDestino,
    ModelRouter,
    ModelSelection,
)
from models.base import Mensaje

# ---------------------------------------------------------------------------
# 1. Datos sensibles → siempre LOCAL
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tarea",
    [
        "Mi contraseña es hunter2",
        "guarda este api_key en el llavero",
        "el secret de stripe es sk_live_xxxx",
        "mi DNI es 12345678Z, ¿puedes guardarlo?",
        "transfiere a la cuenta ES9121000418450200051332",
        "número de tarjeta 4111 1111 1111 1111",
        "el AWS_SECRET_ACCESS_KEY de prod",
        "abre 1password y dame la credencial de github",
        "esto es confidencial: no compartir",
    ],
)
def test_datos_sensibles_siempre_local(tarea: str) -> None:
    router = ModelRouter()
    seleccion = router.route(tarea, ContextoRuteo(mensajes=[Mensaje(rol="user", contenido=tarea)]))
    assert seleccion.model_name == ModeloDestino.LOCAL_DEFAULT
    assert seleccion.razon == "datos_sensibles"


# ---------------------------------------------------------------------------
# 2. Datos sensibles en contexto anidado (historial / nombres de archivo)
# ---------------------------------------------------------------------------


def test_datos_sensibles_en_historial() -> None:
    router = ModelRouter()
    historial = [
        Mensaje(rol="user", contenido="hace un rato te dí mi password"),
        Mensaje(rol="assistant", contenido="recibido"),
    ]
    contexto = ContextoRuteo(
        mensajes=[Mensaje(rol="user", contenido="ahora dime el clima")],
        historial=historial,
    )
    seleccion = router.route("ahora dime el clima", contexto)
    assert seleccion.model_name == ModeloDestino.LOCAL_DEFAULT


def test_datos_sensibles_en_nombre_archivo() -> None:
    router = ModelRouter()
    contexto = ContextoRuteo(
        mensajes=[Mensaje(rol="user", contenido="lee el config")],
        nombres_archivos=[".env", "main.py"],
    )
    seleccion = router.route("lee el config", contexto)
    assert seleccion.model_name == ModeloDestino.LOCAL_DEFAULT


# ---------------------------------------------------------------------------
# 3. Sin internet → LOCAL
# ---------------------------------------------------------------------------


def test_sin_internet_va_a_local() -> None:
    router = ModelRouter()
    contexto = ContextoRuteo(
        mensajes=[Mensaje(rol="user", contenido="hola")],
        sin_internet=True,
    )
    seleccion = router.route("hola", contexto)
    assert seleccion.model_name == ModeloDestino.LOCAL_DEFAULT
    assert seleccion.razon == "sin_internet"


# ---------------------------------------------------------------------------
# 4. Visión → KIMI
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tarea",
    [
        "describe lo que hay en la pantalla",
        "haz un screenshot y resume",
        "mira esta imagen y dime qué ves",
        "captura la ventana activa",
    ],
)
def test_keywords_vision_van_a_gemini(tarea: str) -> None:
    router = ModelRouter()
    seleccion = router.route(
        tarea,
        ContextoRuteo(mensajes=[Mensaje(rol="user", contenido=tarea)], sin_internet=False),
    )
    assert seleccion.model_name == ModeloDestino.GEMINI
    assert seleccion.razon == "vision_requerida"


def test_imagen_adjunta_va_a_gemini() -> None:
    router = ModelRouter()
    contexto = ContextoRuteo(
        mensajes=[Mensaje(rol="user", contenido="describe", imagenes_base64=["AAA"])],
        sin_internet=False,
    )
    seleccion = router.route("describe", contexto)
    assert seleccion.model_name == ModeloDestino.GEMINI


# ---------------------------------------------------------------------------
# 5. Compleja + código → GEMINI
# ---------------------------------------------------------------------------


def test_compleja_con_codigo_va_a_gemini() -> None:
    router = ModelRouter()
    tarea = (
        "Implementa una función Python que refactorice este código y "
        "escribe los tests con pytest. Diseña la arquitectura primero."
    )
    seleccion = router.route(
        tarea,
        ContextoRuteo(mensajes=[Mensaje(rol="user", contenido=tarea)], sin_internet=False),
    )
    assert seleccion.model_name == ModeloDestino.GEMINI
    assert seleccion.razon == "tarea_compleja_codigo"


def test_razonamiento_profundo_va_a_gemini() -> None:
    router = ModelRouter()
    tarea = "Analiza y planifica la arquitectura completa del sistema de facturación."
    seleccion = router.route(
        tarea,
        ContextoRuteo(mensajes=[Mensaje(rol="user", contenido=tarea)], sin_internet=False),
    )
    assert seleccion.model_name == ModeloDestino.GEMINI
    assert seleccion.razon == "razonamiento_profundo"


# ---------------------------------------------------------------------------
# 6. Embeddings / clasificación → LOCAL_EMBED
# ---------------------------------------------------------------------------


def test_clasificacion_va_a_embed_local() -> None:
    router = ModelRouter()
    tarea = "Clasifica estos textos por tema"
    seleccion = router.route(
        tarea,
        ContextoRuteo(mensajes=[Mensaje(rol="user", contenido=tarea)], sin_internet=False),
    )
    assert seleccion.model_name == ModeloDestino.LOCAL_EMBED
    assert seleccion.razon == "embeddings_clasificacion"


# ---------------------------------------------------------------------------
# 7. Default → DEEPSEEK
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tarea",
    ["hola, ¿qué tal?", "dime un chiste", "¿cuál es la capital de Francia?"],
)
def test_default_es_deepseek(tarea: str) -> None:
    router = ModelRouter()
    seleccion = router.route(
        tarea,
        ContextoRuteo(mensajes=[Mensaje(rol="user", contenido=tarea)], sin_internet=False),
    )
    assert seleccion.model_name == ModeloDestino.DEEPSEEK


# ---------------------------------------------------------------------------
# Fallback chain
# ---------------------------------------------------------------------------


def test_fallback_kimi_va_a_deepseek_y_openrouter() -> None:
    router = ModelRouter()
    # Kimi ya no es destino primario (solo fallback); comprobamos su cadena directamente.
    cadena = router._fallback_para(ModeloDestino.KIMI)  # noqa: SLF001
    assert cadena == [
        ModeloDestino.DEEPSEEK,
        ModeloDestino.GEMINI,
        ModeloDestino.OPENROUTER,
        ModeloDestino.LOCAL_DEFAULT,
    ]


def test_fallback_gemini_incluye_kimi_para_vision() -> None:
    router = ModelRouter()
    cadena = router._fallback_para(ModeloDestino.GEMINI)  # noqa: SLF001
    assert cadena == [
        ModeloDestino.KIMI,
        ModeloDestino.DEEPSEEK,
        ModeloDestino.OPENROUTER,
        ModeloDestino.LOCAL_DEFAULT,
    ]


def test_construye_cliente_gemini() -> None:
    from models.gemini import GeminiModel

    router = ModelRouter()
    cliente = router.obtener_cliente(ModeloDestino.GEMINI)
    assert isinstance(cliente, GeminiModel)


def test_fallback_deepseek_va_a_kimi_y_openrouter() -> None:
    router = ModelRouter()
    seleccion = router.route(
        "hola",
        ContextoRuteo(mensajes=[Mensaje(rol="user", contenido="hola")], sin_internet=False),
    )
    assert seleccion.model_name == ModeloDestino.DEEPSEEK
    assert seleccion.fallback_chain[0] == ModeloDestino.KIMI
    assert ModeloDestino.OPENROUTER in seleccion.fallback_chain
    assert seleccion.fallback_chain[-1] == ModeloDestino.LOCAL_DEFAULT


def test_fallback_local_default_termina_en_local_reasoning() -> None:
    router = ModelRouter()
    cadena = router._fallback_para(ModeloDestino.LOCAL_DEFAULT)  # noqa: SLF001
    assert cadena == [ModeloDestino.LOCAL_REASONING]


# ---------------------------------------------------------------------------
# estimate_complexity
# ---------------------------------------------------------------------------


def test_complejidad_texto_corto_baja() -> None:
    assert ModelRouter.estimate_complexity("hola") < 0.2


def test_complejidad_aumenta_con_keywords_y_pasos() -> None:
    simple = ModelRouter.estimate_complexity("hola")
    complejo = ModelRouter.estimate_complexity(
        "Diseña la arquitectura, implementa la solución y luego refactoriza el código y depura los tests"
    )
    assert complejo > simple
    assert complejo >= 0.6


# ---------------------------------------------------------------------------
# detect_sensitive_data — falsos positivos / negativos
# ---------------------------------------------------------------------------


def test_no_falso_positivo_en_texto_inocuo() -> None:
    router = ModelRouter()
    assert not router.detect_sensitive_data(
        "el clima en Madrid hoy",
        ContextoRuteo(mensajes=[]),
    )


def test_detecta_iban_en_medio_de_texto() -> None:
    router = ModelRouter()
    assert router.detect_sensitive_data(
        "transferencia a ES7921000418401234567891",
        ContextoRuteo(mensajes=[]),
    )


# ---------------------------------------------------------------------------
# ModelSelection lleva tiempo de decisión
# ---------------------------------------------------------------------------


def test_seleccion_incluye_tiempo_de_decision() -> None:
    router = ModelRouter()
    seleccion = router.route(
        "hola",
        ContextoRuteo(mensajes=[Mensaje(rol="user", contenido="hola")], sin_internet=False),
    )
    assert isinstance(seleccion, ModelSelection)
    assert seleccion.decision_ms >= 0


# ---------------------------------------------------------------------------
# Circuit breaker en el router
# ---------------------------------------------------------------------------


class TestCircuitBreakerRouter:
    def test_circuit_open_false_por_defecto(self) -> None:
        router = ModelRouter()
        sel = router.route(
            "hola",
            ContextoRuteo(mensajes=[Mensaje(rol="user", contenido="hola")], sin_internet=False),
        )
        assert sel.circuit_open is False

    def test_escala_a_fallback_cuando_circuito_abierto(self) -> None:
        router = ModelRouter()
        # Abrir el circuito de Gemini con 3 fallos
        for _ in range(3):
            router.registrar_fallo_modelo(ModeloDestino.GEMINI)

        # Una tarea que normalmente iría a Gemini (visión)
        sel = router.route(
            "mira la pantalla y dime qué ves",
            ContextoRuteo(
                mensajes=[Mensaje(rol="user", contenido="mira la pantalla")],
                sin_internet=False,
            ),
        )
        # Debe haber escalado al primer fallback (Kimi) en lugar de Gemini
        assert sel.model_name != ModeloDestino.GEMINI
        assert sel.circuit_open is True
        assert "circuit_open" in sel.razon

    def test_exito_cierra_circuito(self) -> None:
        router = ModelRouter()
        for _ in range(3):
            router.registrar_fallo_modelo(ModeloDestino.DEEPSEEK)
        assert router._circuito(ModeloDestino.DEEPSEEK).is_open() is True  # type: ignore[attr-defined]

        router.registrar_exito_modelo(ModeloDestino.DEEPSEEK)
        assert router._circuito(ModeloDestino.DEEPSEEK).is_open() is False  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Acumulación de coste
# ---------------------------------------------------------------------------


class TestCostesRouter:
    def test_total_cost_inicial_cero(self) -> None:
        router = ModelRouter()
        assert router.total_cost_usd == 0.0

    def test_registrar_coste_acumula(self) -> None:
        router = ModelRouter()
        router.registrar_coste(0.000100)
        router.registrar_coste(0.000050)
        assert router.total_cost_usd == pytest.approx(0.000150)

    def test_total_cost_expuesto_en_property(self) -> None:
        router = ModelRouter()
        router.registrar_coste(1.5)
        assert router.total_cost_usd == pytest.approx(1.5)


# ---------------------------------------------------------------------------
# RoutedModel — enrutado per-request + fallback en caliente (Goal 4)
# ---------------------------------------------------------------------------


import time as _time

import httpx

from core.routed_model import RoutedModel
from models.base import BaseModel, ModelConfig, ModelResponse, StreamChunk


def _error_429() -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "http://x/chat/completions")
    resp = httpx.Response(429, request=req)
    return httpx.HTTPStatusError("rate limit", request=req, response=resp)


class _FakeModel(BaseModel):
    def __init__(self, nombre: str, *, fallo: Exception | None = None) -> None:
        super().__init__(ModelConfig(name=nombre))
        self._fallo = fallo

    async def complete(self, mensajes, **kwargs) -> ModelResponse:  # type: ignore[override]
        if self._fallo is not None:
            raise self._fallo
        return ModelResponse(content=f"resp-{self.config.name}", model=self.config.name, cost_usd=0.001)

    async def stream(self, mensajes, **kwargs):  # type: ignore[override]
        if self._fallo is not None:
            raise self._fallo
        yield StreamChunk(content=f"resp-{self.config.name}", model=self.config.name)

    async def health_check(self) -> bool:
        return self._fallo is None


def _router_con_internet(clientes: dict) -> ModelRouter:
    router = ModelRouter(clientes=clientes)
    router._cache_internet = (_time.monotonic(), True)  # type: ignore[attr-defined]
    return router


class TestRoutedModel:
    async def test_usa_modelo_primario_si_responde(self) -> None:
        # "hola" → DEEPSEEK primario
        router = _router_con_internet({ModeloDestino.DEEPSEEK: _FakeModel("deepseek")})
        rm = RoutedModel(router)
        resp = await rm.complete([Mensaje(rol="user", contenido="hola")])
        assert resp.model == "deepseek"
        assert router.total_cost_usd == pytest.approx(0.001)

    async def test_fallback_en_caliente_ante_429(self) -> None:
        # DEEPSEEK (primario) cae con 429 → escala a KIMI (primer fallback)
        router = _router_con_internet({
            ModeloDestino.DEEPSEEK: _FakeModel("deepseek", fallo=_error_429()),
            ModeloDestino.KIMI: _FakeModel("kimi"),
        })
        rm = RoutedModel(router)
        resp = await rm.complete([Mensaje(rol="user", contenido="hola")])
        assert resp.model == "kimi"
        # El circuit breaker de DeepSeek registró el fallo.
        router.registrar_fallo_modelo(ModeloDestino.DEEPSEEK)
        router.registrar_fallo_modelo(ModeloDestino.DEEPSEEK)
        assert router._circuito(ModeloDestino.DEEPSEEK).is_open() is True  # type: ignore[attr-defined]

    async def test_error_no_transitorio_propaga(self) -> None:
        router = _router_con_internet({
            ModeloDestino.DEEPSEEK: _FakeModel("deepseek", fallo=ValueError("bug")),
        })
        rm = RoutedModel(router)
        with pytest.raises(ValueError, match="bug"):
            await rm.complete([Mensaje(rol="user", contenido="hola")])

    async def test_stream_fallback_antes_del_primer_chunk(self) -> None:
        router = _router_con_internet({
            ModeloDestino.DEEPSEEK: _FakeModel("deepseek", fallo=_error_429()),
            ModeloDestino.KIMI: _FakeModel("kimi"),
        })
        rm = RoutedModel(router)
        chunks = [c async for c in rm.stream([Mensaje(rol="user", contenido="hola")])]
        assert chunks and chunks[0].model == "kimi"
