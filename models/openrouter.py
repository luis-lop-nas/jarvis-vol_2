"""Cliente para OpenRouter (fallback genérico a múltiples proveedores)."""

from __future__ import annotations

from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from config import settings
from models.base import BaseModel, Mensaje, RespuestaModelo


class OpenRouterModel(BaseModel):
    """Adaptador para OpenRouter (compatible OpenAI)."""

    nombre = "openrouter"

    def __init__(self, modelo: str = "anthropic/claude-3.5-sonnet") -> None:
        super().__init__(modelo)
        self._cliente = AsyncOpenAI(
            api_key=settings.openrouter_api_key.get_secret_value(),
            base_url=settings.openrouter_base_url,
            default_headers={
                "HTTP-Referer": "https://github.com/luichi/jarvis",
                "X-Title": "JARVIS",
            },
        )

    async def complete(
        self,
        mensajes: list[Mensaje],
        *,
        modelo: str | None = None,
        temperatura: float = 0.7,
        max_tokens: int | None = None,
        herramientas: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> RespuestaModelo:
        """Petición a OpenRouter; el `modelo` debe ser el slug del proveedor."""
        respuesta = await self._cliente.chat.completions.create(
            model=modelo or self.modelo_por_defecto,
            messages=[{"role": m.rol, "content": m.contenido} for m in mensajes],
            temperature=temperatura,
            max_tokens=max_tokens,
            tools=herramientas,
            **kwargs,
        )
        eleccion = respuesta.choices[0]
        return RespuestaModelo(
            contenido=eleccion.message.content or "",
            modelo=respuesta.model,
            tokens_entrada=respuesta.usage.prompt_tokens if respuesta.usage else 0,
            tokens_salida=respuesta.usage.completion_tokens if respuesta.usage else 0,
            razon_finalizacion=eleccion.finish_reason,
            llamadas_herramientas=[
                t.model_dump() for t in (eleccion.message.tool_calls or [])
            ],
        )

    async def stream(
        self,
        mensajes: list[Mensaje],
        *,
        modelo: str | None = None,
        temperatura: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Streaming de tokens vía OpenRouter."""
        flujo = await self._cliente.chat.completions.create(
            model=modelo or self.modelo_por_defecto,
            messages=[{"role": m.rol, "content": m.contenido} for m in mensajes],
            temperature=temperatura,
            max_tokens=max_tokens,
            stream=True,
            **kwargs,
        )
        async for trozo in flujo:
            delta = trozo.choices[0].delta.content
            if delta:
                yield delta

    async def embed(self, textos: list[str]) -> list[list[float]]:
        raise NotImplementedError("Usar Ollama o un proveedor dedicado para embeddings.")

    async def cerrar(self) -> None:
        await self._cliente.close()
