"""Memoria de largo plazo respaldada en ChromaDB."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection
from pydantic import BaseModel, Field

from config import settings
from models.embeddings import EmbeddingsClient

log = logging.getLogger(__name__)

COLECCION_MEMORIA = "jarvis_memory"
COLECCION_DOCUMENTOS = "jarvis_documents"
COLECCION_WORKFLOWS = "jarvis_workflows"


class MemoryEntry(BaseModel):
    """Entrada persistente en la memoria semántica."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    content: str
    summary: str
    category: str
    source: str
    importance: float = Field(default=0.0, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_accessed: datetime = Field(default_factory=lambda: datetime.now(UTC))
    access_count: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class LongTermMemory:
    """Repositorio vectorial de hechos, episodios y workflows usando ChromaDB."""

    def __init__(
        self,
        collection_name: str | None = None,
        embeddings: EmbeddingsClient | None = None,
    ) -> None:
        self._collection_name = collection_name or settings.chroma_collection
        self._cliente: ClientAPI | None = None
        self._coleccion: Collection | None = None
        try:
            self._cliente = chromadb.HttpClient(
                host=settings.chroma_host,
                port=settings.chroma_port,
            )
            self._coleccion = self._cliente.get_or_create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            log.info("Colección ChromaDB lista: %s", self._collection_name)
        except Exception as exc:
            log.warning("ChromaDB no disponible para %s: %s", self._collection_name, exc)
        self._embeddings = embeddings or EmbeddingsClient()

    async def store(self, entry: MemoryEntry) -> str:
        """Almacena una entrada semántica persistente y devuelve su id."""
        coleccion = self._collection()
        if not entry.summary:
            entry.summary = entry.content[:256]
        entry.last_accessed = datetime.now(UTC)
        vector = await self._embeddings.embed_text(entry.content)

        await asyncio.to_thread(
            coleccion.add,
            ids=[entry.id],
            documents=[entry.content],
            embeddings=[vector],
            metadatas=[self._metadata_from_entry(entry)],
        )
        log.info("Memoria guardada: %s (%s)", entry.id, entry.category)
        return entry.id

    async def search(
        self,
        query: str,
        limit: int = 5,
        category_filter: str | None = None,
    ) -> list[MemoryEntry]:
        """Busca semánticamente las entradas más relevantes para la consulta."""
        coleccion = self._collection()
        filtro = {"category": category_filter} if category_filter else None
        vector = await self._embeddings.embed_text(query)
        resultado = await asyncio.to_thread(
            coleccion.query,
            query_embeddings=[vector],
            n_results=limit,
            where=filtro,
        )
        return self._parse_query_results(resultado)

    async def search_hybrid(self, query: str, limit: int = 5) -> list[MemoryEntry]:
        """Combina búsqueda semántica y de palabras clave, eliminando duplicados."""
        semantica = await self.search(query, limit=limit)
        keywords = await asyncio.to_thread(self._keyword_search, query, limit)

        encontrados: dict[str, MemoryEntry] = {entry.id: entry for entry in semantica}
        for entry in keywords:
            encontrados.setdefault(entry.id, entry)
        return list(encontrados.values())[:limit]

    async def get(self, ident: str) -> MemoryEntry | None:
        """Recupera una entrada por su id."""
        coleccion = self._collection()
        try:
            resultado = await asyncio.to_thread(
                coleccion.get,
                ids=[ident],
                include=["documents", "metadatas"],
            )
        except Exception:
            return None

        if not resultado or not resultado.get("ids"):
            return None

        entrada = self._parse_get_result(resultado)
        if entrada:
            entrada.access_count += 1
            entrada.last_accessed = datetime.now(UTC)
            await self._update_entry_metadata(entrada)
            log.info("Memoria recuperada: %s", ident)
        return entrada

    async def update(self, ident: str, content: str) -> bool:
        """Actualiza el contenido y el embedding de una entrada existente."""
        actual = await self.get(ident)
        if actual is None:
            return False
        coleccion = self._collection()
        actual.content = content
        actual.summary = content[:256]
        actual.last_accessed = datetime.now(UTC)
        vector = await self._embeddings.embed_text(content)

        await asyncio.to_thread(
            coleccion.update,
            ids=[ident],
            documents=[content],
            embeddings=[vector],
            metadatas=[self._metadata_from_entry(actual)],
        )
        log.info("Memoria actualizada: %s", ident)
        return True

    async def delete(self, ident: str) -> bool:
        """Elimina una entrada por su id."""
        coleccion = self._collection()
        try:
            await asyncio.to_thread(coleccion.delete, ids=[ident])
            log.info("Memoria eliminada: %s", ident)
            return True
        except Exception as exc:
            log.warning("No se pudo eliminar memoria %s: %s", ident, exc)
            return False

    async def get_by_category(self, category: str, limit: int = 5) -> list[MemoryEntry]:
        """Recupera entradas de una categoría concreta."""
        coleccion = self._collection()
        resultado = await asyncio.to_thread(
            coleccion.get,
            where={"category": category},
            include=["documents", "metadatas"],
        )
        entradas = self._parse_get_results(resultado)
        return entradas[:limit]

    async def get_recent(self, limit: int = 5) -> list[MemoryEntry]:
        """Recupera las entradas más recientes por último acceso."""
        coleccion = self._collection()
        resultados = await asyncio.to_thread(
            coleccion.get,
            include=["documents", "metadatas"],
        )
        entradas = self._parse_get_results(resultados)
        entradas.sort(key=lambda e: e.last_accessed, reverse=True)
        return entradas[:limit]

    async def get_important(self, threshold: float = 0.5, limit: int = 5) -> list[MemoryEntry]:
        """Recupera entradas con importancia mayor o igual al umbral."""
        coleccion = self._collection()
        resultados = await asyncio.to_thread(
            coleccion.get,
            include=["documents", "metadatas"],
        )
        entradas = [e for e in self._parse_get_results(resultados) if e.importance >= threshold]
        entradas.sort(key=lambda e: e.importance, reverse=True)
        return entradas[:limit]

    async def count(self) -> int:
        """Devuelve el número aproximado de entradas en la colección."""
        coleccion = self._collection()
        try:
            return await asyncio.to_thread(coleccion.count)
        except Exception:
            resultado = await asyncio.to_thread(
                coleccion.get,
                include=[],
            )
            return len(resultado.get("ids", []))

    async def build_context(self, task: str) -> str:
        """Construye un texto breve con memorias relevantes para una tarea."""
        entradas = await self.search(task, limit=5)
        if not entradas:
            return ""
        textos = [f"- [{e.category}] {e.summary or e.content}" for e in entradas]
        return "Memorias relevantes:\n" + "\n".join(textos)

    async def health_check(self) -> bool:
        """Verifica que la colección y el proveedor de embeddings están disponibles."""
        if self._coleccion is None:
            return False
        try:
            await asyncio.to_thread(self._coleccion.count)
            if hasattr(self._embeddings, "health_check"):
                return bool(await self._embeddings.health_check())
            proveedor = getattr(self._embeddings, "_proveedor", None)
            if proveedor is not None and hasattr(proveedor, "health_check"):
                return bool(await proveedor.health_check())
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Helpers privados
    # ------------------------------------------------------------------

    def _collection(self) -> Any:
        """Devuelve la colección ChromaDB disponible.

        Raises:
            RuntimeError: Si ChromaDB no está conectado.

        Returns:
            Colección activa para operaciones de lectura/escritura.
        """
        if self._coleccion is None:
            raise RuntimeError("ChromaDB no está disponible")
        return self._coleccion

    def _parse_query_results(self, resultado: dict[str, Any]) -> list[MemoryEntry]:
        ids = resultado.get("ids", [[]])[0]
        documentos = resultado.get("documents", [[]])[0]
        metadatas = resultado.get("metadatas", [[]])[0]
        distancias = resultado.get("distances", [[None] * len(ids)])[0]
        entradas: list[MemoryEntry] = []
        for idx, texto, meta, _dist in zip(ids, documentos, metadatas, distancias, strict=True):
            entradas.append(self._entry_from_parts(idx, texto, meta or {}))
        return entradas

    def _parse_get_result(self, resultado: dict[str, Any]) -> MemoryEntry | None:
        ids = resultado.get("ids", [])
        ids_flat = ids[0] if ids and isinstance(ids[0], list) else ids
        if not ids_flat:
            return None
        idx = ids_flat[0]
        documentos = resultado.get("documents", [])
        metadatas = resultado.get("metadatas", [])
        docs_flat = documentos[0] if documentos and isinstance(documentos[0], list) else documentos
        metas_flat = metadatas[0] if metadatas and isinstance(metadatas[0], list) else metadatas
        texto = docs_flat[0]
        meta = metas_flat[0] or {}
        return self._entry_from_parts(idx, texto, meta)

    def _parse_get_results(self, resultado: dict[str, Any]) -> list[MemoryEntry]:
        ids_raw = resultado.get("ids", [])
        docs_raw = resultado.get("documents", [])
        metas_raw = resultado.get("metadatas", [])
        ids = ids_raw[0] if ids_raw and isinstance(ids_raw[0], list) else ids_raw
        documentos = docs_raw[0] if docs_raw and isinstance(docs_raw[0], list) else docs_raw
        metadatas = metas_raw[0] if metas_raw and isinstance(metas_raw[0], list) else metas_raw
        entradas: list[MemoryEntry] = []
        for idx, texto, meta in zip(ids, documentos, metadatas, strict=True):
            entradas.append(self._entry_from_parts(idx, texto, meta or {}))
        return entradas

    def _keyword_search(self, query: str, limit: int) -> list[MemoryEntry]:
        """Busca coincidencias literales en contenido y resumen.

        Args:
            query: Texto buscado.
            limit: Número máximo de entradas devueltas.

        Returns:
            Entradas cuyo contenido o resumen contienen la consulta.
        """
        texto = query.lower()
        coleccion = self._collection()
        resultado = coleccion.get(include=["documents", "metadatas"])
        entradas = self._parse_get_results(resultado)
        encontrados = [
            e for e in entradas
            if texto in e.content.lower() or texto in e.summary.lower()
        ]
        return encontrados[:limit]

    async def _update_entry_metadata(self, entry: MemoryEntry) -> None:
        """Actualiza solo los metadatos de una entrada.

        Args:
            entry: Entrada con metadatos y estadísticas nuevas.

        Returns:
            None.
        """
        coleccion = self._collection()
        await asyncio.to_thread(
            coleccion.update,
            ids=[entry.id],
            metadatas=[self._metadata_from_entry(entry)],
        )

    def _metadata_from_entry(self, entry: MemoryEntry) -> dict[str, str | int | float | bool]:
        """Serializa metadatos a tipos aceptados por ChromaDB.

        Args:
            entry: Entrada de memoria que se persistirá.

        Returns:
            Diccionario plano con tipos primitivos compatibles con ChromaDB.
        """
        return {
            "summary": entry.summary,
            "category": entry.category,
            "source": entry.source,
            "importance": entry.importance,
            "created_at": entry.created_at.isoformat(),
            "last_accessed": entry.last_accessed.isoformat(),
            "access_count": entry.access_count,
            "metadata_json": json.dumps(entry.metadata, default=str, ensure_ascii=False),
        }

    def _entry_from_parts(
        self, ident: str, content: str, meta: dict[str, Any]
    ) -> MemoryEntry:
        """Reconstruye una entrada desde los fragmentos devueltos por ChromaDB.

        Args:
            ident: Identificador persistido.
            content: Documento almacenado.
            meta: Metadatos planos de ChromaDB.

        Returns:
            Entrada Pydantic lista para usar.
        """
        metadata = meta.get("metadata", {})
        if not isinstance(metadata, dict):
            metadata = {}
        if "metadata_json" in meta:
            try:
                metadata = json.loads(str(meta["metadata_json"]))
            except json.JSONDecodeError:
                metadata = {}
        return MemoryEntry(
            id=ident,
            content=content,
            summary=str(meta.get("summary", content[:256])),
            category=str(meta.get("category", "otro")),
            source=str(meta.get("source", "desconocido")),
            importance=float(meta.get("importance", 0.0)),
            created_at=self._parse_datetime(meta.get("created_at")),
            last_accessed=self._parse_datetime(meta.get("last_accessed")),
            access_count=int(meta.get("access_count", 0)),
            metadata=metadata,
        )

    @staticmethod
    def _parse_datetime(value: str | datetime | None) -> datetime:
        """Convierte un valor externo en `datetime` con fallback seguro.

        Args:
            value: Valor en formato ISO, `datetime` o `None`.

        Returns:
            Fecha parseada o la fecha actual en UTC si no se puede parsear.
        """
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                pass
        return datetime.now(UTC)


MemoriaLargoPlazo = LongTermMemory
