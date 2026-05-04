"""Cliente para Ollama (modelos locales)."""

from __future__ import annotations

from typing import Any, AsyncIterator

import httpx
import orjson

from config import settings
from models.base import BaseModel, Mensaje, RespuestaModelo


class OllamaModel(BaseModel):
    """Adaptador para el servicio HTTP de Ollama."""

    nombre = "ollama"

    def __init__(self, modelo: str | None = None) -> None:
        super().__init__(modelo or settings.ollama_default_model)
        self._cliente = httpx.AsyncClient(
            base_url=settings.ollama_host,
            timeout=httpx.Timeout(connect=10, read=300, write=60, pool=10),
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
        """Genera una respuesta no-streaming usando `/api/chat`."""
        cuerpo: dict[str, Any] = {
            "model": modelo or self.modelo_por_defecto,
            "messages": [{"role": m.rol, "content": m.contenido} for m in mensajes],
            "stream": False,
            "options": {"temperature": temperatura, **kwargs},
        }
        if max_tokens is not None:
            cuerpo["options"]["num_predict"] = max_tokens
        if herramientas:
            cuerpo["tools"] = herramientas

        respuesta = await self._cliente.post("/api/chat", json=cuerpo)
        respuesta.raise_for_status()
        datos = respuesta.json()
        mensaje = datos.get("message", {})
        return RespuestaModelo(
            contenido=mensaje.get("content", ""),
            modelo=datos.get("model", self.modelo_por_defecto),
            tokens_entrada=datos.get("prompt_eval_count", 0),
            tokens_salida=datos.get("eval_count", 0),
            razon_finalizacion=datos.get("done_reason"),
            llamadas_herramientas=mensaje.get("tool_calls", []) or [],
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
        """Streaming línea a línea (NDJSON) del endpoint `/api/chat`."""
        cuerpo: dict[str, Any] = {
            "model": modelo or self.modelo_por_defecto,
            "messages": [{"role": m.rol, "content": m.contenido} for m in mensajes],
            "stream": True,
            "options": {"temperature": temperatura, **kwargs},
        }
        if max_tokens is not None:
            cuerpo["options"]["num_predict"] = max_tokens

        async with self._cliente.stream("POST", "/api/chat", json=cuerpo) as resp:
            resp.raise_for_status()
            async for linea in resp.aiter_lines():
                if not linea:
                    continue
                evento = orjson.loads(linea)
                trozo = evento.get("message", {}).get("content")
                if trozo:
                    yield trozo
                if evento.get("done"):
                    break

    async def embed(self, textos: list[str]) -> list[list[float]]:
        """Calcula embeddings con el modelo local configurado en `OLLAMA_EMBED_MODEL`."""
        respuesta = await self._cliente.post(
            "/api/embed",
            json={"model": settings.ollama_embed_model, "input": textos},
        )
        respuesta.raise_for_status()
        return respuesta.json()["embeddings"]

    async def cerrar(self) -> None:
        await self._cliente.aclose()
