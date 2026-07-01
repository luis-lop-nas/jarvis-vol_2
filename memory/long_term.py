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
from rich.console import Console

from config import settings
from models.embeddings import EmbeddingsClient

log = logging.getLogger(__name__)
console = Console(stderr=True)

COLECCION_MEMORIA = "jarvis_memory"
COLECCION_DOCUMENTOS = "jarvis_documents"
COLECCION_WORKFLOWS = "jarvis_workflows"

# Umbral de similitud por encima del cual se considera "idéntico" (skip)
_SIMILITUD_IDENTICA = 0.99


class MemoryEntry(BaseModel):
    """Entrada persistente en la memoria semántica."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    content: str
    summary: str
    category: str
    source: str
    importance: float = Field(default=0.0, ge=0.0, le=1.0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_accessed: datetime = Field(default_factory=lambda: datetime.now(UTC))
    access_count: int = Field(default=0, ge=0)
    version: int = Field(default=1, ge=1)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
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
            if settings.chroma_mode == "docker":
                # Servidor ChromaDB en Docker (HTTP). Consume ~3.8 GB del VM.
                self._cliente = chromadb.HttpClient(
                    host=settings.chroma_host,
                    port=settings.chroma_port,
                )
            else:
                # Modo local embebido: sin Docker, persiste en disco. Libera la
                # RAM del VM para que quepa un modelo local capaz (el cerebro).
                settings.chromadb_path.mkdir(parents=True, exist_ok=True)
                self._cliente = chromadb.PersistentClient(
                    path=str(settings.chromadb_path),
                )
            self._coleccion = self._cliente.get_or_create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            log.info(
                "Colección ChromaDB lista (%s): %s",
                settings.chroma_mode,
                self._collection_name,
            )
        except Exception as exc:
            log.warning("ChromaDB no disponible para %s: %s", self._collection_name, exc)
        self._embeddings = embeddings or EmbeddingsClient()

    async def store(self, entry: MemoryEntry, *, dedup: bool = True) -> str:
        """Almacena una entrada semántica persistente con deduplicación activa.

        Antes de insertar, busca entradas similares. Si la similitud supera
        ``settings.memory_dedup_threshold``:

        - Idéntica (sim ≥ 0.99) → descarta la nueva silenciosamente.
        - Complemento → fusiona contenidos y actualiza la entrada existente.
        - Contradicción → expira la entrada antigua (valid_until = ahora) y crea la nueva.

        Ejemplo::
            ident = await memoria.store(MemoryEntry(content="hecho", ...))

        Args:
            entry: Entrada a persistir.
            dedup: Si ``False``, omite la comprobación de duplicados.

        Returns:
            Identificador de la entrada guardada o de la existente reutilizada.
        """
        coleccion = self._collection()
        if not entry.summary:
            entry.summary = entry.content[:256]
        entry.last_accessed = datetime.now(UTC)

        if dedup:
            similares = await self._search_with_scores(
                entry.content, limit=5, category=entry.category
            )
            for existente, similitud in similares:
                if similitud >= settings.memory_dedup_threshold:
                    accion = self._dedup_action(entry.content, existente.content, similitud)
                    if accion == "skip":
                        console.log(
                            f"[dim]Dedup skip:[/dim] {existente.id[:8]} "
                            f"(sim={similitud:.3f}, cat={existente.category})"
                        )
                        return existente.id

                    if accion == "complement":
                        sello = datetime.now(UTC).isoformat()
                        contenido_merged = (
                            f"{existente.content}\n\n"
                            f"[Actualizado {sello}] {entry.content}"
                        )
                        existente.content = contenido_merged
                        existente.summary = contenido_merged[:256]
                        existente.updated_at = datetime.now(UTC)
                        existente.version += 1
                        vector = await self._embeddings.embed_text(contenido_merged)
                        await asyncio.to_thread(
                            coleccion.update,
                            ids=[existente.id],
                            documents=[contenido_merged],
                            embeddings=[vector],
                            metadatas=[self._metadata_from_entry(existente)],
                        )
                        console.log(
                            f"[cyan]Dedup complement:[/cyan] {existente.id[:8]} "
                            f"v{existente.version} (sim={similitud:.3f})"
                        )
                        return existente.id

                    if accion == "contradict":
                        # Expira la entrada antigua antes de crear la nueva
                        existente.valid_until = datetime.now(UTC)
                        await self._update_entry_metadata(existente)
                        console.log(
                            f"[yellow]Dedup contradict:[/yellow] {existente.id[:8]} "
                            f"expirado (sim={similitud:.3f})"
                        )
                        break

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
        include_expired: bool = False,
    ) -> list[MemoryEntry]:
        """Busca semánticamente las entradas más relevantes para la consulta.

        Por defecto filtra entradas expiradas (``valid_until < ahora``).

        Ejemplo::
            resultados = await memoria.search("correo reportes", limit=3)

        Args:
            query: Texto de búsqueda.
            limit: Número máximo de resultados.
            category_filter: Si se indica, restringe a esa categoría.
            include_expired: Si ``True``, incluye entradas con ``valid_until`` pasado.

        Returns:
            Lista de entradas ordenadas por relevancia.
        """
        coleccion = self._collection()
        filtro = {"category": category_filter} if category_filter else None
        vector = await self._embeddings.embed_text(query)
        resultado = await asyncio.to_thread(
            coleccion.query,
            query_embeddings=[vector],
            n_results=limit * 2 if not include_expired else limit,
            where=filtro,
        )
        entradas = self._parse_query_results(resultado)
        if not include_expired:
            ahora = datetime.now(UTC)
            entradas = [
                e for e in entradas
                if e.valid_until is None or e.valid_until > ahora
            ]
        return entradas[:limit]

    async def search_hybrid(
        self,
        query: str,
        limit: int = 5,
        include_expired: bool = False,
    ) -> list[MemoryEntry]:
        """Combina búsqueda semántica y de palabras clave, eliminando duplicados.

        Ejemplo::
            resultados = await memoria.search_hybrid("README", limit=5)

        Args:
            query: Texto de búsqueda.
            limit: Número máximo de resultados.
            include_expired: Si ``True``, incluye entradas expiradas.

        Returns:
            Lista deduplicada de entradas relevantes.
        """
        semantica = await self.search(query, limit=limit, include_expired=include_expired)
        keywords = await asyncio.to_thread(
            self._keyword_search, query, limit, include_expired
        )

        encontrados: dict[str, MemoryEntry] = {entry.id: entry for entry in semantica}
        for entry in keywords:
            encontrados.setdefault(entry.id, entry)
        return list(encontrados.values())[:limit]

    async def get(self, ident: str) -> MemoryEntry | None:
        """Recupera una entrada por su id.

        Ejemplo::
            entrada = await memoria.get("abc123")

        Args:
            ident: Identificador de la entrada.

        Returns:
            Entrada Pydantic o ``None`` si no existe.
        """
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
        """Actualiza el contenido y el embedding de una entrada existente.

        Incrementa ``version`` y actualiza ``updated_at``.

        Ejemplo::
            actualizado = await memoria.update("abc123", "nuevo contenido")

        Args:
            ident: Identificador de la entrada.
            content: Nuevo contenido.

        Returns:
            ``True`` si la actualización fue exitosa.
        """
        actual = await self.get(ident)
        if actual is None:
            return False
        coleccion = self._collection()
        actual.content = content
        actual.summary = content[:256]
        actual.updated_at = datetime.now(UTC)
        actual.last_accessed = datetime.now(UTC)
        actual.version += 1
        vector = await self._embeddings.embed_text(content)

        await asyncio.to_thread(
            coleccion.update,
            ids=[ident],
            documents=[content],
            embeddings=[vector],
            metadatas=[self._metadata_from_entry(actual)],
        )
        log.info("Memoria actualizada: %s v%d", ident, actual.version)
        return True

    async def delete(self, ident: str) -> bool:
        """Elimina una entrada por su id.

        Ejemplo::
            ok = await memoria.delete("abc123")

        Args:
            ident: Identificador de la entrada.

        Returns:
            ``True`` si la eliminación fue exitosa.
        """
        coleccion = self._collection()
        try:
            await asyncio.to_thread(coleccion.delete, ids=[ident])
            log.info("Memoria eliminada: %s", ident)
            return True
        except Exception as exc:
            log.warning("No se pudo eliminar memoria %s: %s", ident, exc)
            return False

    async def get_by_category(self, category: str, limit: int = 5) -> list[MemoryEntry]:
        """Recupera entradas de una categoría concreta.

        Ejemplo::
            entradas = await memoria.get_by_category("preferencia", limit=10)

        Args:
            category: Nombre de la categoría.
            limit: Máximo de resultados.

        Returns:
            Lista de entradas de esa categoría.
        """
        coleccion = self._collection()
        resultado = await asyncio.to_thread(
            coleccion.get,
            where={"category": category},
            include=["documents", "metadatas"],
        )
        entradas = self._parse_get_results(resultado)
        return entradas[:limit]

    async def get_recent(self, limit: int = 5) -> list[MemoryEntry]:
        """Recupera las entradas más recientes por último acceso.

        Ejemplo::
            recientes = await memoria.get_recent(limit=5)

        Args:
            limit: Máximo de resultados.

        Returns:
            Lista ordenada por ``last_accessed`` descendente.
        """
        coleccion = self._collection()
        resultados = await asyncio.to_thread(
            coleccion.get,
            include=["documents", "metadatas"],
        )
        entradas = self._parse_get_results(resultados)
        entradas.sort(key=lambda e: e.last_accessed, reverse=True)
        return entradas[:limit]

    async def get_important(self, threshold: float = 0.5, limit: int = 5) -> list[MemoryEntry]:
        """Recupera entradas con importancia mayor o igual al umbral.

        Ejemplo::
            importantes = await memoria.get_important(threshold=0.8)

        Args:
            threshold: Importancia mínima.
            limit: Máximo de resultados.

        Returns:
            Lista ordenada por importancia descendente.
        """
        coleccion = self._collection()
        resultados = await asyncio.to_thread(
            coleccion.get,
            include=["documents", "metadatas"],
        )
        entradas = [e for e in self._parse_get_results(resultados) if e.importance >= threshold]
        entradas.sort(key=lambda e: e.importance, reverse=True)
        return entradas[:limit]

    async def count_expired(self) -> int:
        """Cuenta entradas cuyo ``valid_until`` ha expirado.

        Ejemplo::
            n = await memoria.count_expired()

        Returns:
            Número de entradas expiradas.
        """
        coleccion = self._collection()
        try:
            resultados = await asyncio.to_thread(
                coleccion.get,
                include=["metadatas"],
            )
            ahora = datetime.now(UTC)
            ids_raw = resultados.get("ids", [])
            metas_raw = resultados.get("metadatas", [])
            ids = ids_raw[0] if ids_raw and isinstance(ids_raw[0], list) else ids_raw
            metas = metas_raw[0] if metas_raw and isinstance(metas_raw[0], list) else metas_raw
            expiradas = 0
            for _ident, meta in zip(ids, metas, strict=False):
                valid_until_str = (meta or {}).get("valid_until")
                if valid_until_str:
                    vu = self._parse_datetime(valid_until_str)
                    if vu <= ahora:
                        expiradas += 1
            return expiradas
        except Exception:
            return 0

    async def count(self) -> int:
        """Devuelve el número aproximado de entradas en la colección.

        Ejemplo::
            total = await memoria.count()

        Returns:
            Número total de entradas.
        """
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
        """Construye un texto breve con memorias relevantes para una tarea.

        Ejemplo::
            ctx = await memoria.build_context("organiza archivos")

        Args:
            task: Descripción de la tarea actual.

        Returns:
            Texto con las memorias relevantes formateadas.
        """
        entradas = await self.search(task, limit=5)
        if not entradas:
            return ""
        textos = [f"- [{e.category}] {e.summary or e.content}" for e in entradas]
        return "Memorias relevantes:\n" + "\n".join(textos)

    async def health_check(self) -> bool:
        """Verifica que la colección y el proveedor de embeddings están disponibles.

        Ejemplo::
            ok = await memoria.health_check()

        Returns:
            ``True`` si ChromaDB y los embeddings responden correctamente.
        """
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

    async def _search_with_scores(
        self, query: str, limit: int = 5, category: str | None = None
    ) -> list[tuple[MemoryEntry, float]]:
        """Busca entradas y devuelve pares (entrada, similitud) en [0, 1].

        La similitud se calcula como ``1 - distancia`` para espacio coseno.
        Solo devuelve entradas no expiradas y, si se indica, de la misma categoría.

        Ejemplo::
            pares = await memoria._search_with_scores("correo", limit=3, category="preferencia")

        Args:
            query: Texto de búsqueda.
            limit: Máximo de resultados.
            category: Si se indica, restringe a esa categoría.

        Returns:
            Lista de ``(MemoryEntry, similitud_coseno)`` ordenada por similitud.
        """
        coleccion = self._collection()
        vector = await self._embeddings.embed_text(query)
        filtro = {"category": category} if category else None
        resultado = await asyncio.to_thread(
            coleccion.query,
            query_embeddings=[vector],
            n_results=limit,
            where=filtro,
        )
        ids = resultado.get("ids", [[]])[0]
        documentos = resultado.get("documents", [[]])[0]
        metadatas = resultado.get("metadatas", [[]])[0]
        distancias = resultado.get("distances", [[1.0] * len(ids)])[0]

        ahora = datetime.now(UTC)
        pares: list[tuple[MemoryEntry, float]] = []
        for ident, texto, meta, distancia in zip(
            ids, documentos, metadatas, distancias, strict=True
        ):
            similitud = max(0.0, 1.0 - float(distancia))
            entrada = self._entry_from_parts(ident, texto, meta or {})
            # Excluye entradas expiradas de la deduplicación
            if entrada.valid_until is not None and entrada.valid_until <= ahora:
                continue
            pares.append((entrada, similitud))
        return pares

    def _dedup_action(
        self, new_content: str, existing_content: str, similarity: float
    ) -> str:
        """Determina la acción de deduplicación entre dos entradas similares.

        Heurística basada en similitud de embedding y solapamiento de palabras:
        - sim ≥ 0.99 → skip (prácticamente idénticos).
        - solapamiento léxico bajo (< 0.2) pese a alta similitud semántica → contradict.
        - resto → complement (fusionar contenidos).

        Ejemplo::
            accion = memoria._dedup_action("correo para informes", "correo semanal", 0.95)
            # → "complement"

        Args:
            new_content: Contenido de la nueva entrada.
            existing_content: Contenido de la entrada existente.
            similarity: Similitud coseno entre ambas (0–1).

        Returns:
            ``"skip"``, ``"complement"`` o ``"contradict"``.
        """
        if similarity >= _SIMILITUD_IDENTICA:
            return "skip"
        jaccard = self._word_jaccard(new_content, existing_content)
        if jaccard < 0.2:
            return "contradict"
        return "complement"

    @staticmethod
    def _word_jaccard(a: str, b: str) -> float:
        """Similitud de Jaccard sobre conjuntos de palabras.

        Ejemplo::
            score = LongTermMemory._word_jaccard("hola mundo", "mundo real")
            # → 0.333

        Args:
            a: Primer texto.
            b: Segundo texto.

        Returns:
            Valor en [0, 1]; 0 si alguno está vacío.
        """
        palabras_a = set(a.lower().split())
        palabras_b = set(b.lower().split())
        if not palabras_a or not palabras_b:
            return 0.0
        union = palabras_a | palabras_b
        return len(palabras_a & palabras_b) / len(union)

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

    def _keyword_search(
        self, query: str, limit: int, include_expired: bool = False
    ) -> list[MemoryEntry]:
        """Busca coincidencias literales en contenido y resumen.

        Ejemplo::
            entradas = memoria._keyword_search("README", limit=5)

        Args:
            query: Texto buscado.
            limit: Número máximo de entradas devueltas.
            include_expired: Si ``True``, incluye entradas expiradas.

        Returns:
            Entradas cuyo contenido o resumen contienen la consulta.
        """
        texto = query.lower()
        coleccion = self._collection()
        resultado = coleccion.get(include=["documents", "metadatas"])
        entradas = self._parse_get_results(resultado)
        ahora = datetime.now(UTC)
        encontrados = []
        for e in entradas:
            if not include_expired and e.valid_until is not None and e.valid_until <= ahora:
                continue
            if texto in e.content.lower() or texto in e.summary.lower():
                encontrados.append(e)
        return encontrados[:limit]

    async def _update_entry_metadata(self, entry: MemoryEntry) -> None:
        """Actualiza solo los metadatos de una entrada.

        Ejemplo::
            await memoria._update_entry_metadata(entrada)

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

        Ejemplo::
            meta = memoria._metadata_from_entry(entrada)

        Args:
            entry: Entrada de memoria que se persistirá.

        Returns:
            Diccionario plano con tipos primitivos compatibles con ChromaDB.
        """
        meta: dict[str, str | int | float | bool] = {
            "summary": entry.summary,
            "category": entry.category,
            "source": entry.source,
            "importance": entry.importance,
            "created_at": entry.created_at.isoformat(),
            "updated_at": entry.updated_at.isoformat(),
            "last_accessed": entry.last_accessed.isoformat(),
            "access_count": entry.access_count,
            "version": entry.version,
            "metadata_json": json.dumps(entry.metadata, default=str, ensure_ascii=False),
        }
        if entry.valid_from is not None:
            meta["valid_from"] = entry.valid_from.isoformat()
        if entry.valid_until is not None:
            meta["valid_until"] = entry.valid_until.isoformat()
        return meta

    def _entry_from_parts(
        self, ident: str, content: str, meta: dict[str, Any]
    ) -> MemoryEntry:
        """Reconstruye una entrada desde los fragmentos devueltos por ChromaDB.

        Ejemplo::
            entrada = memoria._entry_from_parts("abc", "contenido", meta_dict)

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
            updated_at=self._parse_datetime(meta.get("updated_at")),
            last_accessed=self._parse_datetime(meta.get("last_accessed")),
            access_count=int(meta.get("access_count", 0)),
            version=int(meta.get("version", 1)),
            valid_from=self._parse_datetime_optional(meta.get("valid_from")),
            valid_until=self._parse_datetime_optional(meta.get("valid_until")),
            metadata=metadata,
        )

    @staticmethod
    def _parse_datetime(value: str | datetime | None) -> datetime:
        """Convierte un valor externo en ``datetime`` con fallback seguro.

        Ejemplo::
            dt = LongTermMemory._parse_datetime("2026-01-01T00:00:00+00:00")

        Args:
            value: Valor en formato ISO, ``datetime`` o ``None``.

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

    @staticmethod
    def _parse_datetime_optional(value: str | datetime | None) -> datetime | None:
        """Convierte un valor a ``datetime`` o devuelve ``None`` si está ausente.

        Ejemplo::
            dt = LongTermMemory._parse_datetime_optional(None)  # → None

        Args:
            value: Valor en formato ISO, ``datetime`` o ``None``.

        Returns:
            Fecha parseada o ``None``.
        """
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                pass
        return None


MemoriaLargoPlazo = LongTermMemory
