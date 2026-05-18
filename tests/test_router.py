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
def test_keywords_vision_van_a_kimi(tarea: str) -> None:
    router = ModelRouter()
    seleccion = router.route(
        tarea,
        ContextoRuteo(mensajes=[Mensaje(rol="user", contenido=tarea)], sin_internet=False),
    )
    assert seleccion.model_name == ModeloDestino.KIMI
    assert seleccion.razon == "vision_requerida"


def test_imagen_adjunta_va_a_kimi() -> None:
    router = ModelRouter()
    contexto = ContextoRuteo(
        mensajes=[Mensaje(rol="user", contenido="describe", imagenes_base64=["AAA"])],
        sin_internet=False,
    )
    seleccion = router.route("describe", contexto)
    assert seleccion.model_name == ModeloDestino.KIMI


# ---------------------------------------------------------------------------
# 5. Compleja + código → KIMI
# ---------------------------------------------------------------------------


def test_compleja_con_codigo_va_a_kimi() -> None:
    router = ModelRouter()
    tarea = (
        "Implementa una función Python que refactorice este código y "
        "escribe los tests con pytest. Diseña la arquitectura primero."
    )
    seleccion = router.route(
        tarea,
        ContextoRuteo(mensajes=[Mensaje(rol="user", contenido=tarea)], sin_internet=False),
    )
    assert seleccion.model_name == ModeloDestino.KIMI
    assert seleccion.razon == "tarea_compleja_codigo"


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
    seleccion = router.route(
        "describe la pantalla",
        ContextoRuteo(
            mensajes=[Mensaje(rol="user", contenido="describe la pantalla")],
            sin_internet=False,
        ),
    )
    assert seleccion.model_name == ModeloDestino.KIMI
    assert seleccion.fallback_chain == [
        ModeloDestino.DEEPSEEK,
        ModeloDestino.OPENROUTER,
        ModeloDestino.LOCAL_DEFAULT,
    ]


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
