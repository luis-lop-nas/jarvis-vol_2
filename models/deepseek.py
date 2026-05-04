"""Cliente para DeepSeek, compatible con la API de OpenAI."""

from __future__ import annotations

from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from config import settings
from models.base import BaseModel, Mensaje, RespuestaModelo


class DeepSeekModel(BaseModel):
    """Adaptador para los modelos de DeepSeek (chat y reasoner)."""

    nombre = "deepseek"

    def __init__(self, modelo: str | None = None) -> None:
        super().__init__(modelo or settings.deepseek_default_model)
        self._cliente = AsyncOpenAI(
            api_key=settings.deepseek_api_key.get_secret_value(),
            base_url=settings.deepseek_base_url,
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
        """Petición síncrona al endpoint de chat de DeepSeek."""
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
            metadatos={
                "razonamiento": getattr(eleccion.message, "reasoning_content", None),
            },
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
        """Streaming de tokens; en `deepseek-reasoner` precede al razonamiento."""
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
        raise NotImplementedError("DeepSeek no expone embeddings públicos.")

    async def cerrar(self) -> None:
        await self._cliente.close()
