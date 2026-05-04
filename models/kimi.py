"""Cliente para Kimi (Moonshot AI), compatible con la API de OpenAI."""

from __future__ import annotations

from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from config import settings
from models.base import BaseModel, Mensaje, RespuestaModelo


class KimiModel(BaseModel):
    """Adaptador del proveedor Kimi vía endpoint compatible con OpenAI."""

    nombre = "kimi"

    def __init__(self, modelo: str | None = None) -> None:
        super().__init__(modelo or settings.kimi_default_model)
        self._cliente = AsyncOpenAI(
            api_key=settings.kimi_api_key.get_secret_value(),
            base_url=settings.kimi_base_url,
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
        """Genera una respuesta completa usando la API de Kimi."""
        respuesta = await self._cliente.chat.completions.create(
            model=modelo or self.modelo_por_defecto,
            messages=[self._a_dict(m) for m in mensajes],
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
        """Itera sobre los deltas de contenido de la respuesta en streaming."""
        flujo = await self._cliente.chat.completions.create(
            model=modelo or self.modelo_por_defecto,
            messages=[self._a_dict(m) for m in mensajes],
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
        """Kimi no expone endpoint de embeddings: usar Ollama o un fallback."""
        raise NotImplementedError("Kimi no soporta embeddings; usar Ollama.")

    async def cerrar(self) -> None:
        await self._cliente.close()

    @staticmethod
    def _a_dict(mensaje: Mensaje) -> dict[str, Any]:
        """Serializa un `Mensaje` al formato esperado por la API."""
        base: dict[str, Any] = {"role": mensaje.rol, "content": mensaje.contenido}
        if mensaje.nombre:
            base["name"] = mensaje.nombre
        return base
