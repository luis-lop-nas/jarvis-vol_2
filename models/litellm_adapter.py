"""Adaptador opcional de LiteLLM para JARVIS.

Activo solo si `LITELLM_ENABLED=true` en settings.
Permite usar cualquiera de los 100+ proveedores soportados por LiteLLM
con la misma interfaz `BaseModel` del sistema.

Uso típico:
    LITELLM_ENABLED=true  # en .env
    model = LiteLLMAdapter("openai/gpt-4o")
    respuesta = await model.complete(mensajes)
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from typing import Any

from config import settings
from models._common import log_model_call
from models.base import (
    BaseModel,
    Mensaje,
    ModelCapability,
    ModelConfig,
    ModelResponse,
    StreamChunk,
)

log = logging.getLogger(__name__)


class LiteLLMNotEnabledError(RuntimeError):
    """Lanzada cuando se usa LiteLLMAdapter sin LITELLM_ENABLED=true."""

    def __init__(self) -> None:
        super().__init__(
            "LiteLLMAdapter requiere LITELLM_ENABLED=true en .env "
            "y el paquete 'litellm' instalado (pip install 'jarvis[litellm]')."
        )


class LiteLLMAdapter(BaseModel):
    """Adaptador BaseModel sobre litellm.acompletion().

    Permite acceder a cualquier proveedor LiteLLM con la interfaz unificada
    de JARVIS. Solo disponible cuando `LITELLM_ENABLED=true`.

    Ejemplo::
        model = LiteLLMAdapter("openai/gpt-4o-mini")
        respuesta = await model.complete(mensajes)
        print(respuesta.content, respuesta.cost_usd)
    """

    nombre = "litellm"

    def __init__(
        self,
        modelo: str,
        audit_log: AuditLog | None = None,
    ) -> None:
        if not settings.litellm_enabled:
            raise LiteLLMNotEnabledError()

        try:
            import litellm  # noqa: F401
        except ImportError as exc:
            raise LiteLLMNotEnabledError() from exc

        config = ModelConfig(
            name=modelo,
            capabilities=ModelCapability.TEXT | ModelCapability.TOOL_USE,
        )
        super().__init__(config)
        self._audit_log = audit_log

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
        """Llama a litellm.acompletion() con los parámetros estándar."""
        import litellm

        modelo_id = modelo or self.config.name
        mensajes_dict = [
            {"role": m.rol, "content": m.contenido} for m in mensajes
        ]

        params: dict[str, Any] = {
            "model": modelo_id,
            "messages": mensajes_dict,
            "temperature": temperatura,
        }
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
        if herramientas:
            params["tools"] = herramientas
        params.update(kwargs)

        inicio = time.monotonic()
        respuesta = await litellm.acompletion(**params)
        duracion = int((time.monotonic() - inicio) * 1000)

        eleccion = respuesta.choices[0]
        uso = respuesta.usage or {}
        tokens_in = getattr(uso, "prompt_tokens", 0) or 0
        tokens_out = getattr(uso, "completion_tokens", 0) or 0
        # litellm expone el coste real via response_cost (cuando está disponible)
        coste = float(getattr(respuesta, "_hidden_params", {}).get("response_cost", 0.0))

        resultado = ModelResponse(
            content=eleccion.message.content or "",
            model=modelo_id,
            tokens_input=tokens_in,
            tokens_output=tokens_out,
            duration_ms=duracion,
            finish_reason=eleccion.finish_reason,
            tool_calls=getattr(eleccion.message, "tool_calls", None) or [],
            cost_usd=coste,
        )
        log.info(
            "LiteLLM %s: %d→%d tokens, %d ms, $%.6f",
            modelo_id, tokens_in, tokens_out, duracion, coste,
        )
        await log_model_call(
            self._audit_log,
            modelo=modelo_id,
            tokens_input=tokens_in,
            tokens_output=tokens_out,
            latencia_ms=duracion,
            cost_usd=coste,
            cache_hit=False,
        )
        return resultado

    async def stream(
        self,
        mensajes: list[Mensaje],
        *,
        modelo: str | None = None,
        temperatura: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Streaming via litellm.acompletion(stream=True)."""
        import litellm

        modelo_id = modelo or self.config.name
        mensajes_dict = [{"role": m.rol, "content": m.contenido} for m in mensajes]

        params: dict[str, Any] = {
            "model": modelo_id,
            "messages": mensajes_dict,
            "temperature": temperatura,
            "stream": True,
        }
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
        params.update(kwargs)

        inicio = time.monotonic()
        tokens_emitidos = 0

        async for trozo in await litellm.acompletion(**params):
            delta = trozo.choices[0].delta.content or ""
            if delta:
                tokens_emitidos += 1
                transcurrido = max(time.monotonic() - inicio, 1e-6)
                yield StreamChunk(
                    content=delta,
                    model=modelo_id,
                    tokens_per_second=tokens_emitidos / transcurrido,
                )
            if trozo.choices[0].finish_reason:
                yield StreamChunk(content="", model=modelo_id, is_final=True)
                break

    async def health_check(self) -> bool:
        """`True` si litellm está disponible."""
        try:
            import litellm  # noqa: F401
            return True
        except ImportError:
            return False

    async def cerrar(self) -> None:
        pass


# Importación diferida para evitar ciclos
try:
    from security.audit_log import AuditLog  # noqa: F401
except ImportError:
    AuditLog = None  # type: ignore[assignment,misc]
