"""Tests de los clientes de modelos.

Todos los tests son locales: las APIs externas se mockean con
`httpx.MockTransport` y los métodos asíncronos se ejercitan en modo `auto`.
"""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import patch

import httpx
import orjson
import pytest

from models._common import (
    CircuitBreaker,
    EstadoCircuito,
    RetryPolicy,
    TTLCache,
    log_model_call,
    mensaje_a_dict,
)
from models.base import (
    BaseModel,
    Mensaje,
    ModelCapability,
    ModelResponse,
    StreamChunk,
)
from models.deepseek import DeepSeekModel
from models.gemini import GeminiModel
from models.kimi import KimiModel
from models.ollama_client import OllamaModel
from models.openrouter import OpenRouterModel

# ---------------------------------------------------------------------------
# Helpers para mockear httpx
# ---------------------------------------------------------------------------


def _respuesta_chat(contenido: str = "ok", modelo: str = "kimi-k2.6") -> dict[str, Any]:
    return {
        "id": "x",
        "object": "chat.completion",
        "model": modelo,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": contenido},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
    }


def _transport_chat(contenido: str = "ok") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(200, json=_respuesta_chat(contenido))
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": []})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# Todos los clientes implementan BaseModel
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "clase", [KimiModel, DeepSeekModel, GeminiModel, OllamaModel, OpenRouterModel]
)
def test_implementan_base_model(clase: type[BaseModel]) -> None:
    assert issubclass(clase, BaseModel)
    for metodo in ("complete", "stream", "health_check"):
        assert hasattr(clase, metodo)


def test_capabilities_se_declaran() -> None:
    cliente = KimiModel(cliente=httpx.AsyncClient(transport=_transport_chat()))
    assert cliente.soporta(ModelCapability.VISION)
    assert cliente.soporta(ModelCapability.TOOL_USE)


# ---------------------------------------------------------------------------
# stream() devuelve un async generator
# ---------------------------------------------------------------------------


def test_stream_es_async_generator() -> None:
    for clase in (KimiModel, DeepSeekModel, GeminiModel, OllamaModel, OpenRouterModel):
        # `stream` está declarado en BaseModel; la implementación concreta
        # debe ser una función generadora async.
        impl = clase.stream
        assert inspect.isasyncgenfunction(impl), f"{clase.__name__}.stream no es async generator"


# ---------------------------------------------------------------------------
# complete() de Kimi / DeepSeek / OpenRouter — happy path
# ---------------------------------------------------------------------------


async def test_kimi_complete_devuelve_model_response() -> None:
    cliente_http = httpx.AsyncClient(transport=_transport_chat("hola"), base_url="http://x")
    kimi = KimiModel(cliente=cliente_http)
    resp = await kimi.complete([Mensaje(rol="user", contenido="hola")])
    assert isinstance(resp, ModelResponse)
    assert resp.content == "hola"
    assert resp.tokens_input == 5 and resp.tokens_output == 2
    assert resp.cached is False
    await kimi.cerrar()


async def test_kimi_complete_usa_cache_en_segunda_llamada() -> None:
    contador = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        contador["n"] += 1
        return httpx.Response(200, json=_respuesta_chat("eco"))

    cliente_http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x")
    kimi = KimiModel(cliente=cliente_http, cache=TTLCache(max_entradas=4, ttl_segundos=60))

    primera = await kimi.complete([Mensaje(rol="user", contenido="hola")])
    segunda = await kimi.complete([Mensaje(rol="user", contenido="hola")])

    assert contador["n"] == 1
    assert primera.cached is False
    assert segunda.cached is True
    await kimi.cerrar()


async def test_gemini_complete_devuelve_model_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_respuesta_chat("hola", modelo="gemini-2.5-flash"))

    cliente_http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x")
    gemini = GeminiModel(cliente=cliente_http)
    resp = await gemini.complete([Mensaje(rol="user", contenido="hola")])
    assert isinstance(resp, ModelResponse)
    assert resp.content == "hola"
    assert resp.model == "gemini-2.5-flash"
    await gemini.cerrar()


def test_gemini_declara_vision_y_tool_use() -> None:
    gemini = GeminiModel(cliente=httpx.AsyncClient(transport=_transport_chat()))
    assert gemini.soporta(ModelCapability.VISION)
    assert gemini.soporta(ModelCapability.TOOL_USE)


async def test_deepseek_complete_calcula_coste_y_cached() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "deepseek-chat",
                "choices": [
                    {"message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}
                ],
                "usage": {
                    "prompt_tokens": 1000,
                    "completion_tokens": 500,
                    "prompt_cache_hit_tokens": 800,
                },
            },
        )

    cliente_http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x")
    ds = DeepSeekModel(cliente=cliente_http)
    resp = await ds.complete([Mensaje(rol="user", contenido="hola")])
    assert resp.metadatos["tokens_cached"] == 800
    assert resp.cost_usd > 0
    await ds.cerrar()


async def test_deepseek_elige_reasoner_si_complejidad_alta() -> None:
    capturadas: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        capturadas.append(orjson.loads(request.content))
        return httpx.Response(200, json=_respuesta_chat("ok", modelo="deepseek-reasoner"))

    cliente_http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x")
    ds = DeepSeekModel(cliente=cliente_http)
    await ds.complete([Mensaje(rol="user", contenido="x")], complejidad=0.9)
    assert capturadas[0]["model"] == "deepseek-reasoner"
    await ds.cerrar()


# ---------------------------------------------------------------------------
# Retry en errores transitorios (429)
# ---------------------------------------------------------------------------


async def test_kimi_reintenta_en_429() -> None:
    intentos = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        intentos["n"] += 1
        if intentos["n"] < 3:
            return httpx.Response(429, json={"error": {"message": "rate"}})
        return httpx.Response(200, json=_respuesta_chat("ok"))

    cliente_http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x")
    kimi = KimiModel(cliente=cliente_http)
    # Reducir esperas para que el test sea rápido.
    kimi._retry = RetryPolicy(max_intentos=4, base_segundos=0.01, max_segundos=0.05)  # noqa: SLF001
    resp = await kimi.complete([Mensaje(rol="user", contenido="hola")])
    assert resp.content == "ok"
    assert intentos["n"] == 3
    await kimi.cerrar()


def test_retry_after_segundos_parsea_entero() -> None:
    resp = httpx.Response(429, headers={"Retry-After": "12"})
    assert RetryPolicy._retry_after_segundos(resp) == 12.0
    assert RetryPolicy._retry_after_segundos(httpx.Response(429)) is None


async def test_retry_respeta_retry_after_en_429() -> None:
    import time as _t

    intentos = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        intentos["n"] += 1
        if intentos["n"] < 2:
            return httpx.Response(429, headers={"Retry-After": "1"}, json={"error": "rate"})
        return httpx.Response(200, json=_respuesta_chat("ok"))

    cliente_http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x")
    gemini = GeminiModel(cliente=cliente_http)
    gemini._min_interval = 0.0  # aislar el efecto del Retry-After  # noqa: SLF001
    t0 = _t.monotonic()
    resp = await gemini.complete([Mensaje(rol="user", contenido="hola")])
    transcurrido = _t.monotonic() - t0
    assert resp.content == "ok"
    assert intentos["n"] == 2
    # Debe haber esperado ~1s (el Retry-After), no el backoff por defecto.
    assert transcurrido >= 1.0
    await gemini.cerrar()


async def test_gemini_throttle_espacia_llamadas() -> None:
    import time as _t

    cliente_http = httpx.AsyncClient(transport=_transport_chat("ok"), base_url="http://x")
    gemini = GeminiModel(cliente=cliente_http)
    gemini._min_interval = 0.3  # noqa: SLF001
    await gemini.complete([Mensaje(rol="user", contenido="a")])
    t0 = _t.monotonic()
    await gemini.complete([Mensaje(rol="user", contenido="b")])
    assert _t.monotonic() - t0 >= 0.3
    await gemini.cerrar()


async def test_retry_se_rinde_tras_max_intentos() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    cliente_http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x")
    kimi = KimiModel(cliente=cliente_http)
    kimi._retry = RetryPolicy(max_intentos=2, base_segundos=0.01, max_segundos=0.02)  # noqa: SLF001
    with pytest.raises(httpx.HTTPStatusError):
        await kimi.complete([Mensaje(rol="user", contenido="x")])
    await kimi.cerrar()


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------


async def test_health_check_detecta_modelo_caido() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    cliente_http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x")
    kimi = KimiModel(cliente=cliente_http)
    assert await kimi.health_check() is False
    await kimi.cerrar()


async def test_health_check_ok() -> None:
    cliente_http = httpx.AsyncClient(transport=_transport_chat(), base_url="http://x")
    kimi = KimiModel(cliente=cliente_http)
    assert await kimi.health_check() is True
    await kimi.cerrar()


# ---------------------------------------------------------------------------
# Ollama — RAM y modelos cargados
# ---------------------------------------------------------------------------


async def test_ollama_falla_si_no_hay_ram_y_no_hay_alternativa() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/tags"):
            return httpx.Response(200, json={"models": [{"name": "qwen3:8b"}]})
        return httpx.Response(200, json={})

    cliente_http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x")
    ollama = OllamaModel(modelo="qwen3:8b", cliente=cliente_http)

    with patch("models.ollama_client.psutil.virtual_memory") as fake:
        fake.return_value.available = int(1 * 1024**3)  # 1 GB libres
        with pytest.raises(RuntimeError, match="Sin RAM suficiente"):
            await ollama._preparar_modelo("qwen3:8b")  # noqa: SLF001

    await ollama.cerrar()


async def test_ollama_cae_a_modelo_pequeno_si_no_hay_ram() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/tags"):
            return httpx.Response(
                200,
                json={"models": [{"name": "qwen3:8b"}, {"name": "gemma4:4b"}]},
            )
        return httpx.Response(200, json={})

    cliente_http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x")
    ollama = OllamaModel(modelo="qwen3:8b", cliente=cliente_http)
    await ollama._asegurar_inicializado()  # noqa: SLF001

    with patch("models.ollama_client.psutil.virtual_memory") as fake:
        fake.return_value.available = int(4 * 1024**3)  # 4 GB libres
        elegido = await ollama._preparar_modelo("qwen3:8b")  # noqa: SLF001
        assert elegido == "gemma4:4b"

    await ollama.cerrar()


async def test_ollama_descarga_modelo_anterior_antes_de_cargar_otro() -> None:
    descargas: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/tags"):
            return httpx.Response(
                200,
                json={"models": [{"name": "gemma4:4b"}, {"name": "llama3.2"}]},
            )
        if request.url.path.endswith("/api/generate"):
            cuerpo = orjson.loads(request.content)
            if cuerpo.get("keep_alive") == 0:
                descargas.append(cuerpo["model"])
            return httpx.Response(200, json={})
        return httpx.Response(200, json={})

    cliente_http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x")
    ollama = OllamaModel(modelo="gemma4:4b", cliente=cliente_http)
    await ollama._asegurar_inicializado()  # noqa: SLF001

    with patch("models.ollama_client.psutil.virtual_memory") as fake:
        fake.return_value.available = int(8 * 1024**3)
        await ollama._preparar_modelo("gemma4:4b")  # noqa: SLF001
        await ollama._preparar_modelo("llama3.2")  # noqa: SLF001

    assert descargas == ["gemma4:4b"]
    await ollama.cerrar()


async def test_ollama_calcula_tokens_por_segundo() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/tags"):
            return httpx.Response(200, json={"models": [{"name": "gemma4:4b"}]})
        if request.url.path.endswith("/api/chat"):
            return httpx.Response(
                200,
                json={
                    "model": "gemma4:4b",
                    "message": {"role": "assistant", "content": "hola"},
                    "done": True,
                    "done_reason": "stop",
                    "prompt_eval_count": 5,
                    "eval_count": 100,
                    "eval_duration": 1_000_000_000,  # 1 s en ns
                },
            )
        return httpx.Response(200, json={})

    cliente_http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x")
    ollama = OllamaModel(modelo="gemma4:4b", cliente=cliente_http)
    with patch("models.ollama_client.psutil.virtual_memory") as fake:
        fake.return_value.available = int(8 * 1024**3)
        resp = await ollama.complete([Mensaje(rol="user", contenido="hola")])
    assert resp.metadatos["tokens_per_second"] == pytest.approx(100.0, rel=0.01)
    await ollama.cerrar()


# ---------------------------------------------------------------------------
# OpenRouter — selector de free
# ---------------------------------------------------------------------------


async def test_openrouter_usa_preferido_sin_roundtrip() -> None:
    """complete() prueba el primer :free preferido sin round-trip a /models."""
    llamadas: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        llamadas.append(request.url.path)
        if request.url.path.endswith("/models"):
            raise AssertionError("complete() no debe consultar /models en el camino caliente")
        if request.url.path.endswith("/chat/completions"):
            cuerpo = orjson.loads(request.content)
            assert cuerpo["model"] == "moonshotai/kimi-k2:free"
            return httpx.Response(200, json=_respuesta_chat("ok", modelo=cuerpo["model"]))
        return httpx.Response(404)

    cliente_http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x")
    or_model = OpenRouterModel(cliente=cliente_http)
    resp = await or_model.complete([Mensaje(rol="user", contenido="hola")])
    assert resp.model == "moonshotai/kimi-k2:free"
    assert not any(p.endswith("/models") for p in llamadas)
    await or_model.cerrar()


async def test_openrouter_refrescar_catalogo_refina_rotacion() -> None:
    """refrescar_catalogo() descarta de la rotación los slugs no publicados."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/models"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "deepseek/deepseek-chat-v3:free"},
                        {"id": "qwen/qwen3-coder:free"},
                    ]
                },
            )
        if request.url.path.endswith("/chat/completions"):
            cuerpo = orjson.loads(request.content)
            assert cuerpo["model"] == "deepseek/deepseek-chat-v3:free"
            return httpx.Response(200, json=_respuesta_chat("ok", modelo=cuerpo["model"]))
        return httpx.Response(404)

    cliente_http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://x")
    or_model = OpenRouterModel(cliente=cliente_http)
    await or_model.refrescar_catalogo()  # refina la lista (kimi no está en el catálogo)
    resp = await or_model.complete([Mensaje(rol="user", contenido="hola")])
    assert resp.model == "deepseek/deepseek-chat-v3:free"
    await or_model.cerrar()


# ---------------------------------------------------------------------------
# Helpers / utilidades
# ---------------------------------------------------------------------------


def test_mensaje_a_dict_simple() -> None:
    d = mensaje_a_dict(Mensaje(rol="user", contenido="hola"))
    assert d == {"role": "user", "content": "hola"}


def test_mensaje_a_dict_con_imagenes_es_array_partes() -> None:
    d = mensaje_a_dict(
        Mensaje(rol="user", contenido="describe", imagenes_base64=["AAA"])
    )
    assert isinstance(d["content"], list)
    assert d["content"][0]["type"] == "text"
    assert d["content"][1]["type"] == "image_url"
    assert d["content"][1]["image_url"]["url"].startswith("data:image/")


def test_ttl_cache_lru_expulsa_la_mas_vieja() -> None:
    cache = TTLCache(max_entradas=2, ttl_segundos=60)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)
    assert cache.get("a") is None
    assert cache.get("b") == 2
    assert cache.get("c") == 3


def test_model_response_y_stream_chunk_son_dataclasses() -> None:
    resp = ModelResponse(content="x", model="m")
    assert resp.cached is False
    chunk = StreamChunk(content="x", model="m")
    assert chunk.is_thinking is False


# ---------------------------------------------------------------------------
# CircuitBreaker
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    def test_estado_inicial_closed(self) -> None:
        cb = CircuitBreaker()
        assert cb.estado() == EstadoCircuito.CLOSED
        assert cb.is_open() is False

    def test_abre_tras_max_fallos(self) -> None:
        cb = CircuitBreaker(max_fallos=3, ventana_s=60.0)
        cb.registrar_fallo()
        cb.registrar_fallo()
        assert cb.is_open() is False
        cb.registrar_fallo()
        assert cb.is_open() is True
        assert cb.estado() == EstadoCircuito.OPEN

    def test_exito_cierra_circuito(self) -> None:
        cb = CircuitBreaker(max_fallos=2)
        cb.registrar_fallo()
        cb.registrar_fallo()
        assert cb.is_open() is True
        cb.registrar_exito()
        assert cb.is_open() is False
        assert cb.estado() == EstadoCircuito.CLOSED

    def test_half_open_tras_recuperacion(self) -> None:
        import time
        cb = CircuitBreaker(max_fallos=2, tiempo_recuperacion_s=10.0)
        cb.registrar_fallo()
        cb.registrar_fallo()
        assert cb.estado() == EstadoCircuito.OPEN

        # Retroceder _apertura para simular que pasó el tiempo de recuperación
        cb._apertura = time.monotonic() - 20.0  # type: ignore[attr-defined]
        assert cb.estado() == EstadoCircuito.HALF_OPEN
        assert cb.is_open() is False

    def test_fallos_fuera_de_ventana_no_abren(self) -> None:
        cb = CircuitBreaker(max_fallos=3, ventana_s=1.0)
        cb.registrar_fallo()
        cb.registrar_fallo()
        # Simula que el tiempo avanzó más allá de la ventana
        cb._fallos = [t - 2.0 for t in cb._fallos]  # type: ignore[attr-defined]
        cb.registrar_fallo()
        # Solo 1 fallo en la ventana → no debe abrirse
        assert cb.is_open() is False


# ---------------------------------------------------------------------------
# log_model_call
# ---------------------------------------------------------------------------


class TestLogModelCall:
    async def test_sin_audit_log_no_falla(self) -> None:
        await log_model_call(
            None,
            modelo="kimi-k2.6",
            tokens_input=10,
            tokens_output=5,
            latencia_ms=200,
            cost_usd=0.0000015,
            cache_hit=False,
        )

    async def test_llama_log_action(self) -> None:
        from unittest.mock import AsyncMock, MagicMock
        audit = MagicMock()
        audit.log_action = AsyncMock()
        await log_model_call(
            audit,
            modelo="deepseek-chat",
            tokens_input=100,
            tokens_output=50,
            latencia_ms=300,
            cost_usd=0.000120,
            cache_hit=True,
            session_id="sess-test",
        )
        audit.log_action.assert_awaited_once()
        call_kwargs = audit.log_action.call_args.kwargs
        assert call_kwargs["action_type"] == "model_call"
        assert call_kwargs["details"]["modelo"] == "deepseek-chat"
        assert call_kwargs["details"]["cache_hit"] is True
        assert call_kwargs["session_id"] == "sess-test"


# ---------------------------------------------------------------------------
# Coste en clientes de modelo
# ---------------------------------------------------------------------------


class TestCostesModelos:
    def _cliente(self, body: dict, base_url: str = "http://x") -> httpx.AsyncClient:
        data = orjson.dumps(body)

        def _handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=data)

        return httpx.AsyncClient(
            transport=httpx.MockTransport(_handler), base_url=base_url
        )

    async def test_kimi_calcula_coste(self) -> None:
        cuerpo = {
            "id": "x",
            "model": "kimi-k2.6",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
        }
        model = KimiModel(cliente=self._cliente(cuerpo))
        resp = await model.complete([Mensaje(rol="user", contenido="test")])
        # 1000 * 0.15 / 1e6 + 500 * 0.15 / 1e6 = 0.000225
        assert resp.cost_usd == pytest.approx(0.000225, rel=1e-3)

    async def test_gemini_calcula_coste(self) -> None:
        cuerpo = {
            "id": "x",
            "model": "gemini-2.5-flash",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 500},
        }
        model = GeminiModel(cliente=self._cliente(cuerpo))
        resp = await model.complete([Mensaje(rol="user", contenido="test")])
        # 1000 * 0.30 / 1e6 + 500 * 2.50 / 1e6 = 0.0003 + 0.00125 = 0.00155
        assert resp.cost_usd == pytest.approx(0.00155, rel=1e-3)

    async def test_openrouter_usa_usage_cost(self) -> None:
        cuerpo = {
            "id": "x",
            "model": "moonshotai/kimi-k2:free",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "cost": 0.000042},
        }
        model = OpenRouterModel(cliente=self._cliente(cuerpo))
        resp = await model.complete([Mensaje(rol="user", contenido="test")])
        assert resp.cost_usd == pytest.approx(0.000042)

    async def test_ollama_coste_por_duracion(self) -> None:
        cuerpo = {
            "model": "gemma4:4b",
            "message": {"role": "assistant", "content": "hola"},
            "done": True,
            "done_reason": "stop",
            "eval_count": 10,
            "eval_duration": 1_000_000_000,  # 1 segundo
            "prompt_eval_count": 5,
        }

        def _handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/tags":
                return httpx.Response(200, content=orjson.dumps({"models": []}))
            return httpx.Response(200, content=orjson.dumps(cuerpo))

        from config import settings as cfg
        cliente = httpx.AsyncClient(
            transport=httpx.MockTransport(_handler), base_url="http://localhost:11434"
        )
        model = OllamaModel(cliente=cliente)
        model._inicializado = True
        model._modelo_cargado = "gemma4:4b"
        resp = await model.complete([Mensaje(rol="user", contenido="test")])
        # duracion_ms / 1000 * ollama_cost_per_second
        esperado = (resp.duration_ms / 1000.0) * cfg.ollama_cost_per_second
        assert resp.cost_usd == pytest.approx(esperado, rel=1e-3)


# ---------------------------------------------------------------------------
# LiteLLMAdapter — solo verifica error cuando deshabilitado
# ---------------------------------------------------------------------------


class TestLiteLLMAdapter:
    def test_error_cuando_deshabilitado(self) -> None:
        from config import settings as cfg
        from models.litellm_adapter import LiteLLMAdapter, LiteLLMNotEnabledError

        original = cfg.litellm_enabled
        try:
            object.__setattr__(cfg, "litellm_enabled", False)
            with pytest.raises(LiteLLMNotEnabledError):
                LiteLLMAdapter("openai/gpt-4o-mini")
        finally:
            object.__setattr__(cfg, "litellm_enabled", original)
