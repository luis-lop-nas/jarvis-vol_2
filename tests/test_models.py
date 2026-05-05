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

from models._common import RetryPolicy, TTLCache, mensaje_a_dict
from models.base import (
    BaseModel,
    Mensaje,
    ModelCapability,
    ModelConfig,
    ModelResponse,
    StreamChunk,
)
from models.deepseek import DeepSeekModel
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


@pytest.mark.parametrize("clase", [KimiModel, DeepSeekModel, OllamaModel, OpenRouterModel])
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
    for clase in (KimiModel, DeepSeekModel, OllamaModel, OpenRouterModel):
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


async def test_openrouter_elige_primer_free_disponible() -> None:
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
