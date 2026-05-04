"""Cliente unificado de embeddings con caché en memoria."""

from __future__ import annotations

import hashlib
from collections import OrderedDict

from models.base import BaseModel
from models.ollama_client import OllamaModel


class EmbeddingsClient:
    """Frontal único para calcular embeddings.

    Por defecto usa Ollama local (gratis y privado). Mantiene una caché LRU
    en memoria para evitar recomputar vectores idénticos durante una sesión.
    """

    def __init__(
        self,
        proveedor: BaseModel | None = None,
        tamano_cache: int = 4096,
    ) -> None:
        self._proveedor = proveedor or OllamaModel()
        self._tamano_cache = tamano_cache
        self._cache: OrderedDict[str, list[float]] = OrderedDict()

    async def embed(self, textos: list[str]) -> list[list[float]]:
        """Devuelve los embeddings de la lista, usando caché cuando sea posible."""
        resultados: list[list[float] | None] = [None] * len(textos)
        pendientes: list[tuple[int, str, str]] = []

        for i, texto in enumerate(textos):
            clave = self._hash(texto)
            if clave in self._cache:
                self._cache.move_to_end(clave)
                resultados[i] = self._cache[clave]
            else:
                pendientes.append((i, clave, texto))

        if pendientes:
            nuevos = await self._proveedor.embed([p[2] for p in pendientes])
            for (i, clave, _), vector in zip(pendientes, nuevos, strict=True):
                resultados[i] = vector
                self._guardar(clave, vector)

        return [r for r in resultados if r is not None]

    async def embed_uno(self, texto: str) -> list[float]:
        """Atajo para un único texto."""
        return (await self.embed([texto]))[0]

    def _guardar(self, clave: str, vector: list[float]) -> None:
        self._cache[clave] = vector
        if len(self._cache) > self._tamano_cache:
            self._cache.popitem(last=False)

    @staticmethod
    def _hash(texto: str) -> str:
        return hashlib.sha256(texto.encode("utf-8")).hexdigest()

    async def cerrar(self) -> None:
        await self._proveedor.cerrar()
