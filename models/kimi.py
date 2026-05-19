"""Cliente para Kimi K2.6 (Moonshot AI), API compatible con OpenAI.

Características:
- complete() con tool_use y soporte de visión.
- stream() async generator token a token.
- complete_with_thinking() forzando el modelo `kimi-k2-thinking`.
- Caché en memoria de respuestas idénticas (TTL 5 min).
- Reintentos automáticos en 429/5xx con backoff exponencial.
- Logging de tokens consumidos por llamada.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
import orjson

from config import settings
from models._common import (
    RetryPolicy,
    TTLCache,
    estimar_tokens,
    log_model_call,
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

# Tarifas oficiales Moonshot/Kimi (USD por 1 M tokens).
TARIFAS_USD: dict[str, dict[str, float]] = {
    "kimi-k2.6":       {"input": 0.15, "output": 0.15},
    "kimi-k2-thinking": {"input": 0.15, "output": 0.15},
}


class KimiModel(BaseModel):
    """Adaptador del proveedor Kimi (Moonshot)."""

    nombre = "kimi"

    def __init__(
        self,
        modelo: str | None = None,
        cliente: httpx.AsyncClient | None = None,
        cache: TTLCache | None = None,
        audit_log: AuditLog | None = None,
    ) -> None:
        config = ModelConfig(
            name=modelo or settings.kimi_model_default,
            api_key=settings.kimi_api_key.get_secret_value(),
            base_url=settings.kimi_base_url,
            timeout=120.0,
            capabilities=(
                ModelCapability.TEXT
                | ModelCapability.VISION
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
        self._audit_log = audit_log

    # ------------------------------------------------------------------
    # complete / stream / thinking
    # ------------------------------------------------------------------

    async def complete(
        self,
        mensajes: list[Mensaje],
        *,
        modelo: str | None = None,
        temperatura: float = 0.7,
        max_tokens: int | None = None,
        herramientas: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        """Petición no-streaming a `/chat/completions`."""
        modelo_id = modelo or self.config.name
        clave = self._cache.clave(
            modelo_id,
            mensajes,
            temperatura,
            extras={"max_tokens": max_tokens, "tools": bool(herramientas)},
        )
        cacheada = self._cache.get(clave) if not herramientas else None
        if cacheada is not None:
            log.debug("Caché HIT para %s", modelo_id)
            from dataclasses import replace

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
        coste = self._coste_usd(modelo_id, tokens_in, tokens_out)

        modelo_response = ModelResponse(
            content=eleccion["message"].get("content") or "",
            model=datos.get("model", modelo_id),
            tokens_input=tokens_in,
            tokens_output=tokens_out,
            duration_ms=duracion,
            finish_reason=eleccion.get("finish_reason"),
            tool_calls=eleccion["message"].get("tool_calls") or [],
            cost_usd=coste,
        )
        log.info(
            "Kimi %s: %d→%d tokens, %d ms, $%.6f",
            modelo_response.model,
            tokens_in,
            tokens_out,
            duracion,
            coste,
        )

        if not herramientas:
            self._cache.put(clave, modelo_response)

        await log_model_call(
            self._audit_log,
            modelo=modelo_response.model,
            tokens_input=tokens_in,
            tokens_output=tokens_out,
            latencia_ms=duracion,
            cost_usd=coste,
            cache_hit=False,
        )
        return modelo_response

    async def stream(
        self,
        mensajes: list[Mensaje],
        *,
        modelo: str | None = None,
        temperatura: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Streaming SSE token a token."""
        modelo_id = modelo or self.config.name
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
                delta = evento["choices"][0].get("delta", {}).get("content")
                if delta:
                    tokens_emitidos += estimar_tokens(delta)
                    transcurrido = max(time.monotonic() - inicio, 1e-6)
                    yield StreamChunk(
                        content=delta,
                        model=modelo_id,
                        tokens_per_second=tokens_emitidos / transcurrido,
                    )

    async def complete_with_thinking(
        self, mensajes: list[Mensaje], **kwargs: Any
    ) -> ModelResponse:
        """Atajo que fuerza el modelo `kimi-k2-thinking`."""
        respuesta = await self.complete(
            mensajes, modelo=settings.kimi_model_thinking, **kwargs
        )
        respuesta.thinking = respuesta.metadatos.get("reasoning_content")
        return respuesta

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    @staticmethod
    def _coste_usd(modelo_id: str, tokens_in: int, tokens_out: int) -> float:
        """Calcula el coste estimado en USD según las tarifas de Moonshot."""
        tarifas = TARIFAS_USD.get(modelo_id, {"input": 0.15, "output": 0.15})
        return (tokens_in * tarifas["input"] + tokens_out * tarifas["output"]) / 1_000_000

    async def health_check(self) -> bool:
        """`True` si la API responde a una petición trivial."""
        try:
            resp = await self._cliente.get("/models", timeout=5.0)
            return resp.status_code < 500
        except (httpx.HTTPError, httpx.TransportError):
            return False

    async def cerrar(self) -> None:
        await self._cliente.aclose()


# Importación diferida para evitar ciclos
try:
    from security.audit_log import AuditLog  # noqa: F401
except ImportError:
    AuditLog = None  # type: ignore[assignment,misc]
