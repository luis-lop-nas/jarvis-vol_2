"""Memoria de largo plazo respaldada en ChromaDB."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection

from config import settings
from models.embeddings import EmbeddingsClient


@dataclass(slots=True)
class FragmentoMemoria:
    """Pieza atómica almacenada en la memoria de largo plazo."""

    id: str
    texto: str
    metadatos: dict[str, Any]
    distancia: float | None = None


class MemoriaLargoPlazo:
    """Repositorio vectorial de hechos, episodios y aprendizajes."""

    def __init__(
        self,
        coleccion: str = "jarvis_long_term",
        embeddings: EmbeddingsClient | None = None,
    ) -> None:
        self._cliente: ClientAPI = chromadb.HttpClient(
            host="localhost", port=settings.chromadb_port
        )
        self._coleccion: Collection = self._cliente.get_or_create_collection(
            name=coleccion, metadata={"hnsw:space": "cosine"}
        )
        self._embeddings = embeddings or EmbeddingsClient()

    async def guardar(self, texto: str, metadatos: dict[str, Any] | None = None) -> str:
        """Indexa un texto en la colección y devuelve su id."""
        ident = uuid.uuid4().hex
        vector = await self._embeddings.embed_uno(texto)
        self._coleccion.add(
            ids=[ident],
            documents=[texto],
            embeddings=[vector],
            metadatas=[metadatos or {}],
        )
        return ident

    async def buscar(
        self, consulta: str, k: int = 5, filtro: dict[str, Any] | None = None
    ) -> list[FragmentoMemoria]:
        """Recupera los `k` fragmentos más cercanos a la consulta."""
        vector = await self._embeddings.embed_uno(consulta)
        resultado = self._coleccion.query(
            query_embeddings=[vector],
            n_results=k,
            where=filtro,
        )
        ids = resultado["ids"][0]
        textos = resultado["documents"][0]
        metas = resultado["metadatas"][0]
        distancias = resultado.get("distances", [[None] * len(ids)])[0]
        return [
            FragmentoMemoria(id=i, texto=t, metadatos=m or {}, distancia=d)
            for i, t, m, d in zip(ids, textos, metas, distancias, strict=True)
        ]

    async def borrar(self, ident: str) -> None:
        self._coleccion.delete(ids=[ident])
