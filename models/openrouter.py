"""Cliente para OpenRouter — fallback gratuito vía catálogo `:free`.

Se usa cuando Kimi/DeepSeek fallan o sus claves no están configuradas.
Selecciona automáticamente un modelo del free tier disponible siguiendo el
orden de preferencia definido en `MODELOS_FREE_PREFERIDOS`.
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

# Slugs de OpenRouter por orden de preferencia. Todos `:free` salvo que cambie.
MODELOS_FREE_PREFERIDOS: tuple[str, ...] = (
    "moonshotai/kimi-k2:free",
    "deepseek/deepseek-chat-v3:free",
    "qwen/qwen3-coder:free",
    "qwen/qwen3:free",
    "meta-llama/llama-3.3-70b-instruct:free",
)


class OpenRouterModel(BaseModel):
    """Adaptador para OpenRouter (compatible OpenAI)."""

    nombre = "openrouter"

    def __init__(
        self,
        modelo: str | None = None,
        cliente: httpx.AsyncClient | None = None,
        cache: TTLCache | None = None,
        audit_log: AuditLog | None = None,
    ) -> None:
        config = ModelConfig(
            name=modelo or MODELOS_FREE_PREFERIDOS[0],
            api_key=settings.openrouter_api_key.get_secret_value(),
            base_url=settings.openrouter_base_url,
            timeout=120.0,
            capabilities=ModelCapability.TEXT | ModelCapability.TOOL_USE,
        )
        super().__init__(config)
        self._cliente = cliente or httpx.AsyncClient(
            base_url=config.base_url,
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "HTTP-Referer": "https://github.com/luichi/jarvis",
                "X-Title": "JARVIS",
            },
            timeout=httpx.Timeout(connect=10, read=config.timeout, write=30, pool=10),
        )
        self._retry = RetryPolicy(max_intentos=config.max_retries)
        self._cache = cache or TTLCache(max_entradas=64, ttl_segundos=300)
        self._modelos_free_disponibles: list[str] | None = None
        self._audit_log = audit_log

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
        **kwargs: Any,
    ) -> ModelResponse:
        # Candidatos: si el caller fija un modelo, solo ese; si no, la lista de
        # free disponibles para poder rotar cuando uno devuelve 429 (los free
        # populares como kimi:free se saturan constantemente).
        candidatos = [modelo] if modelo else self._lista_free()

        # Caché de respuestas idénticas (mismo patrón que Kimi): un hit devuelve
        # sin tocar la red. Las peticiones con herramientas no se cachean — sus
        # tool_calls dependen del estado.
        clave_cache = self._cache.clave(
            modelo or "openrouter:free-rotate",
            mensajes,
            temperatura,
            extras={"max_tokens": max_tokens, "tools": bool(herramientas)},
        )
        cacheada = self._cache.get(clave_cache) if not herramientas else None
        if cacheada is not None:
            from dataclasses import replace

            log.debug("Caché HIT OpenRouter")
            return replace(cacheada, cached=True)

        inicio = time.monotonic()
        respuesta: httpx.Response | None = None
        modelo_id = candidatos[0]
        ultimo_error: Exception | None = None

        for modelo_id in candidatos:
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

            # Un único intento por modelo: si da 429 (saturación upstream del
            # free tier) rotamos al siguiente en vez de reintentar el mismo, que
            # solo consumiría cuota. El _retry se reserva para errores de red.
            try:
                resp = await self._cliente.post("/chat/completions", json=cuerpo)
                resp.raise_for_status()
                respuesta = resp
                break
            except httpx.HTTPStatusError as exc:
                ultimo_error = exc
                if exc.response.status_code in (429, 502, 503):
                    log.warning("OpenRouter %s no disponible (%d); probando siguiente free",
                                modelo_id, exc.response.status_code)
                    continue
                raise
            except (httpx.HTTPError, httpx.TransportError) as exc:
                ultimo_error = exc
                continue

        if respuesta is None:
            assert ultimo_error is not None
            raise ultimo_error

        datos = orjson.loads(respuesta.content)
        duracion = int((time.monotonic() - inicio) * 1000)

        eleccion = datos["choices"][0]
        uso = datos.get("usage", {}) or {}
        tokens_in = uso.get("prompt_tokens", 0)
        tokens_out = uso.get("completion_tokens", 0)
        # OpenRouter devuelve el coste real en usage.cost (ya en USD)
        coste = float(uso.get("cost", 0.0))

        respuesta_model = ModelResponse(
            content=eleccion["message"].get("content") or "",
            model=datos.get("model", modelo_id),
            tokens_input=tokens_in,
            tokens_output=tokens_out,
            duration_ms=duracion,
            finish_reason=eleccion.get("finish_reason"),
            tool_calls=eleccion["message"].get("tool_calls") or [],
            cost_usd=coste,
        )
        if not herramientas:
            self._cache.put(clave_cache, respuesta_model)
        await log_model_call(
            self._audit_log,
            modelo=respuesta_model.model,
            tokens_input=tokens_in,
            tokens_output=tokens_out,
            latencia_ms=duracion,
            cost_usd=coste,
            cache_hit=False,
        )
        return respuesta_model

    async def stream(
        self,
        mensajes: list[Mensaje],
        *,
        modelo: str | None = None,
        temperatura: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        modelo_id = modelo or await self._elegir_free()
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
    # Selector de modelo free
    # ------------------------------------------------------------------


    def _lista_free(self) -> list[str]:
        """Lista ordenada de modelos `:free` para rotar en 429.

        No toca la red: usa el catálogo refinado si ya se cargó (vía
        ``refrescar_catalogo``), o la lista preferida estática en caso contrario.
        Así la primera petición no paga un round-trip a ``/models`` — si un
        slug ya no existe, OpenRouter devuelve error y rotamos igualmente.
        """
        disponibles = self._modelos_free_disponibles or list(MODELOS_FREE_PREFERIDOS)
        return disponibles or [self.config.name]

    async def _elegir_free(self) -> str:
        """Primer modelo `:free` a probar (sin round-trip en el camino caliente)."""
        return self._lista_free()[0]

    async def refrescar_catalogo(self) -> None:
        """Refina la lista de modelos `:free` contra el catálogo de OpenRouter.

        Opcional y best-effort: pensado para llamarse en background al arrancar,
        nunca en el camino de una petición. Descarta de la rotación los slugs que
        ya no publica OpenRouter, ahorrando intentos fallidos posteriores.
        """
        try:
            resp = await self._cliente.get("/models", timeout=5.0)
            resp.raise_for_status()
            ids = {m["id"] for m in orjson.loads(resp.content).get("data", [])}
            refinada = [m for m in MODELOS_FREE_PREFERIDOS if m in ids]
            if refinada:
                self._modelos_free_disponibles = refinada
        except (httpx.HTTPError, httpx.TransportError) as exc:
            log.warning("No se pudo refrescar catálogo OpenRouter: %s", exc)


# Importación diferida para evitar ciclos
try:
    from security.audit_log import AuditLog  # noqa: F401
except ImportError:
    AuditLog = None  # type: ignore[assignment,misc]
