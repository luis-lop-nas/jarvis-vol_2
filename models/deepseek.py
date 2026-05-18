"""Cliente para DeepSeek V3.2 (chat) y V3.2-reasoner.

Características:
- complete() / stream() compatibles OpenAI.
- Modo híbrido thinking/non-thinking según `complejidad` indicada o estimada.
- Conciencia de prefix caching (DeepSeek factura menos por cache hits): se
  expone `tokens_cached` y se descuenta del coste estimado.
- Estimación de coste por llamada en USD en tiempo real.
- Reintentos en 429/5xx + caché TTL para prompts repetidos.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

import httpx
import orjson

from config import settings
from models._common import (
    RetryPolicy,
    TTLCache,
    estimar_tokens,
    mensaje_a_dict,
)
from models.base import (
    BaseModel,
    Mensaje,
    ModelCapability,
    ModelConfig,
    ModelResponse,
    StreamChunk,
)

log = logging.getLogger(__name__)

# Tarifas oficiales (USD por 1M tokens). Se actualizan cuando DeepSeek las cambie.
TARIFAS_USD: dict[str, dict[str, float]] = {
    "deepseek-chat":     {"input": 0.27, "input_cached": 0.07, "output": 1.10},
    "deepseek-reasoner": {"input": 0.55, "input_cached": 0.14, "output": 2.19},
}

# Umbral de complejidad por encima del cual se usa el reasoner.
UMBRAL_REASONER: float = 0.65


class DeepSeekModel(BaseModel):
    """Adaptador para DeepSeek V3.2."""

    nombre = "deepseek"

    def __init__(
        self,
        modelo: str | None = None,
        cliente: httpx.AsyncClient | None = None,
        cache: TTLCache | None = None,
    ) -> None:
        config = ModelConfig(
            name=modelo or settings.deepseek_model_default,
            api_key=settings.deepseek_api_key.get_secret_value(),
            base_url=settings.deepseek_base_url,
            timeout=120.0,
            capabilities=(
                ModelCapability.TEXT
                | ModelCapability.TOOL_USE
                | ModelCapability.THINKING
            ),
        )
        super().__init__(config)
        self._cliente = cliente or httpx.AsyncClient(
            base_url=config.base_url,
            headers={"Authorization": f"Bearer {config.api_key}"},
            timeout=httpx.Timeout(connect=10, read=config.timeout, write=30, pool=10),
        )
        self._retry = RetryPolicy(max_intentos=config.max_retries)
        self._cache = cache or TTLCache(max_entradas=128, ttl_segundos=300)

    # ------------------------------------------------------------------
    # complete / stream
    # ------------------------------------------------------------------

    async def complete(
        self,
        mensajes: list[Mensaje],
        *,
        modelo: str | None = None,
        temperatura: float = 0.7,
        max_tokens: int | None = None,
        herramientas: list[dict[str, Any]] | None = None,
        complejidad: float | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Petición no-streaming. Si `complejidad >= UMBRAL_REASONER`, usa el reasoner."""
        modelo_id = modelo or self._elegir_modelo(complejidad)
        clave = self._cache.clave(
            modelo_id,
            mensajes,
            temperatura,
            extras={"max_tokens": max_tokens, "tools": bool(herramientas)},
        )
        cacheada = self._cache.get(clave) if not herramientas else None
        if cacheada is not None:
            log.debug("Caché HIT para %s", modelo_id)
            return replace(cacheada, cached=True)

        cuerpo: dict[str, Any] = {
            "model": modelo_id,
            "messages": [mensaje_a_dict(m) for m in mensajes],
            "temperature": temperatura,
        }
        if max_tokens is not None:
            cuerpo["max_tokens"] = max_tokens
        if herramientas:
            cuerpo["tools"] = herramientas
        cuerpo.update(kwargs)

        inicio = time.monotonic()

        async def _llamar() -> httpx.Response:
            resp = await self._cliente.post("/chat/completions", json=cuerpo)
            resp.raise_for_status()
            return resp

        respuesta = await self._retry.ejecutar(_llamar)
        datos = respuesta.json()
        duracion = int((time.monotonic() - inicio) * 1000)

        eleccion = datos["choices"][0]
        uso = datos.get("usage", {}) or {}
        tokens_in = uso.get("prompt_tokens", 0)
        tokens_out = uso.get("completion_tokens", 0)
        tokens_cached = uso.get("prompt_cache_hit_tokens", 0)

        coste = self._coste_usd(modelo_id, tokens_in, tokens_out, tokens_cached)

        modelo_response = ModelResponse(
            content=eleccion["message"].get("content") or "",
            model=datos.get("model", modelo_id),
            tokens_input=tokens_in,
            tokens_output=tokens_out,
            duration_ms=duracion,
            finish_reason=eleccion.get("finish_reason"),
            tool_calls=eleccion["message"].get("tool_calls") or [],
            thinking=eleccion["message"].get("reasoning_content"),
            cost_usd=coste,
            metadatos={"tokens_cached": tokens_cached},
        )
        log.info(
            "DeepSeek %s: %d→%d (cached %d) tokens, %d ms, $%.6f",
            modelo_response.model,
            tokens_in,
            tokens_out,
            tokens_cached,
            duracion,
            coste,
        )

        if not herramientas:
            self._cache.put(clave, modelo_response)
        return modelo_response

    async def stream(
        self,
        mensajes: list[Mensaje],
        *,
        modelo: str | None = None,
        temperatura: float = 0.7,
        max_tokens: int | None = None,
        complejidad: float | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        modelo_id = modelo or self._elegir_modelo(complejidad)
        cuerpo: dict[str, Any] = {
            "model": modelo_id,
            "messages": [mensaje_a_dict(m) for m in mensajes],
            "temperature": temperatura,
            "stream": True,
        }
        if max_tokens is not None:
            cuerpo["max_tokens"] = max_tokens
        cuerpo.update(kwargs)

        inicio = time.monotonic()
        tokens_emitidos = 0

        async with self._cliente.stream("POST", "/chat/completions", json=cuerpo) as resp:
            resp.raise_for_status()
            async for linea in resp.aiter_lines():
                if not linea or not linea.startswith("data:"):
                    continue
                payload = linea[5:].strip()
                if payload == "[DONE]":
                    yield StreamChunk(content="", model=modelo_id, is_final=True)
                    break
                try:
                    evento = orjson.loads(payload)
                except orjson.JSONDecodeError:
                    continue
                delta = evento["choices"][0].get("delta", {})
                texto = delta.get("content")
                pensamiento = delta.get("reasoning_content")
                if pensamiento:
                    yield StreamChunk(
                        content=pensamiento, model=modelo_id, is_thinking=True
                    )
                if texto:
                    tokens_emitidos += estimar_tokens(texto)
                    transcurrido = max(time.monotonic() - inicio, 1e-6)
                    yield StreamChunk(
                        content=texto,
                        model=modelo_id,
                        tokens_per_second=tokens_emitidos / transcurrido,
                    )

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        try:
            resp = await self._cliente.get("/models", timeout=5.0)
            return resp.status_code < 500
        except (httpx.HTTPError, httpx.TransportError):
            return False

    async def cerrar(self) -> None:
        await self._cliente.aclose()

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _elegir_modelo(self, complejidad: float | None) -> str:
        if complejidad is not None and complejidad >= UMBRAL_REASONER:
            return settings.deepseek_model_reasoner
        return self.config.name

    @staticmethod
    def _coste_usd(modelo: str, tokens_in: int, tokens_out: int, tokens_cached: int) -> float:
        tarifa = TARIFAS_USD.get(modelo)
        if tarifa is None:
            return 0.0
        tokens_in_no_cache = max(0, tokens_in - tokens_cached)
        return (
            tokens_in_no_cache * tarifa["input"]
            + tokens_cached * tarifa["input_cached"]
            + tokens_out * tarifa["output"]
        ) / 1_000_000
