"""Embeddings locales con caché SQLite.

Backend por defecto: `nomic-embed-text` vía Ollama (768 dimensiones).
Los vectores se normalizan a L2=1 para que la distancia coseno coincida con
el producto escalar — coherente con `MemoriaLargoPlazo` (ChromaDB cosine).

Caché persistente en SQLite: misma frase no se reembebe entre sesiones.

Ejemplo:
    >>> async def uso():
    ...     async with EmbeddingsClient() as e:
    ...         v = await e.embed_text("hola mundo")
    ...     return len(v)  # 768
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import sqlite3
import struct
from pathlib import Path
from types import TracebackType
from typing import Self

from config import settings
from models.base import BaseModel
from models.ollama_client import OllamaModel

log = logging.getLogger(__name__)

DIMENSION_ESPERADA: int = 768


class CacheEmbeddings:
    """Caché SQLite de vectores empaquetados como blobs de floats."""

    def __init__(self, ruta: Path | None = None) -> None:
        self._ruta = (ruta or settings.embed_cache_path).expanduser().resolve()
        self._ruta.parent.mkdir(parents=True, exist_ok=True)
        self._lock = asyncio.Lock()
        self._inicializar_sync()

    def _inicializar_sync(self) -> None:
        with sqlite3.connect(self._ruta) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS embeddings (
                    hash TEXT PRIMARY KEY,
                    modelo TEXT NOT NULL,
                    dimension INTEGER NOT NULL,
                    vector BLOB NOT NULL,
                    creado_en REAL NOT NULL
                )
                """
            )

    async def obtener(self, texto: str, modelo: str) -> list[float] | None:
        clave = self._hash(texto, modelo)
        async with self._lock:
            return await asyncio.to_thread(self._obtener_sync, clave)

    def _obtener_sync(self, clave: str) -> list[float] | None:
        with sqlite3.connect(self._ruta) as conn:
            fila = conn.execute(
                "SELECT dimension, vector FROM embeddings WHERE hash = ?", (clave,)
            ).fetchone()
        if fila is None:
            return None
        dimension, blob = fila
        return list(struct.unpack(f"{dimension}f", blob))

    async def guardar(self, texto: str, modelo: str, vector: list[float]) -> None:
        clave = self._hash(texto, modelo)
        blob = struct.pack(f"{len(vector)}f", *vector)
        async with self._lock:
            await asyncio.to_thread(self._guardar_sync, clave, modelo, len(vector), blob)

    def _guardar_sync(self, clave: str, modelo: str, dimension: int, blob: bytes) -> None:
        import time

        with sqlite3.connect(self._ruta) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO embeddings(hash, modelo, dimension, vector, creado_en)
                VALUES (?, ?, ?, ?, ?)
                """,
                (clave, modelo, dimension, blob, time.time()),
            )

    @staticmethod
    def _hash(texto: str, modelo: str) -> str:
        h = hashlib.sha256()
        h.update(modelo.encode())
        h.update(b"\0")
        h.update(texto.encode("utf-8"))
        return h.hexdigest()


def _normalizar_l2(vector: list[float]) -> list[float]:
    """Normaliza un vector a longitud 1 (L2). Vector cero → vector cero."""
    norma = math.sqrt(sum(v * v for v in vector))
    if norma == 0.0:
        return vector
    return [v / norma for v in vector]


class EmbeddingsClient:
    """Frontal único para calcular embeddings con caché persistente."""

    def __init__(
        self,
        proveedor: BaseModel | None = None,
        cache: CacheEmbeddings | None = None,
        modelo_id: str | None = None,
    ) -> None:
        self._proveedor = proveedor or OllamaModel()
        self._cache = cache or CacheEmbeddings()
        self._modelo_id = modelo_id or settings.ollama_model_embed

    async def embed_text(self, texto: str) -> list[float]:
        """Embedding de un único texto, normalizado L2."""
        cacheado = await self._cache.obtener(texto, self._modelo_id)
        if cacheado is not None:
            return cacheado

        vector = (await self._proveedor.embed([texto]))[0]
        if len(vector) != DIMENSION_ESPERADA:
            log.warning(
                "Dimensión inesperada %d (esperada %d) en %s",
                len(vector),
                DIMENSION_ESPERADA,
                self._modelo_id,
            )
        normalizado = _normalizar_l2(vector)
        await self._cache.guardar(texto, self._modelo_id, normalizado)
        return normalizado

    async def embed_batch(self, textos: list[str]) -> list[list[float]]:
        """Embedding por lotes — rellena la caché y agrupa los faltantes."""
        resultados: list[list[float] | None] = [None] * len(textos)
        pendientes: list[tuple[int, str]] = []

        for i, texto in enumerate(textos):
            cacheado = await self._cache.obtener(texto, self._modelo_id)
            if cacheado is not None:
                resultados[i] = cacheado
            else:
                pendientes.append((i, texto))

        if pendientes:
            crudos = await self._proveedor.embed([t for _, t in pendientes])
            for (idx, texto), vector in zip(pendientes, crudos, strict=True):
                normalizado = _normalizar_l2(vector)
                resultados[idx] = normalizado
                await self._cache.guardar(texto, self._modelo_id, normalizado)

        return [r for r in resultados if r is not None]

    # Aliases compatibles con la API histórica usada por `memory/`.
    async def embed(self, textos: list[str]) -> list[list[float]]:
        return await self.embed_batch(textos)

    async def embed_uno(self, texto: str) -> list[float]:
        return await self.embed_text(texto)

    async def cerrar(self) -> None:
        await self._proveedor.cerrar()

    async def health_check(self) -> bool:
        """Verifica que el proveedor local de embeddings responde.

        Returns:
            `True` si el proveedor está disponible; `False` si falla.
        """
        try:
            return await self._proveedor.health_check()
        except Exception:
            log.exception("Health check de embeddings falló")
            return False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.cerrar()
