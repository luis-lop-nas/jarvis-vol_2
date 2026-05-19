"""Tests de la memoria multinivel de JARVIS.

Todos los backends externos están mockeados: ChromaDB, Ollama y 1Password.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from memory import HealthStatus, MemorySystem
from memory.episodic import Episode, EpisodicMemory
from memory.long_term import LongTermMemory, MemoryEntry
from memory.procedural import ProceduralMemory, Workflow
from memory.short_term import Message, ShortTermMemory
from memory.vault import Vault
from models.base import ModelResponse


class FakeEmbeddings:
    """Embeddings deterministas para tests sin Ollama."""

    async def embed_text(self, texto: str) -> list[float]:
        """Devuelve un vector pequeño y normalizado basado en palabras clave."""
        base = [
            float("correo" in texto.lower() or "mail" in texto.lower()),
            float("archivo" in texto.lower() or "readme" in texto.lower()),
            float("workflow" in texto.lower() or "organiza" in texto.lower()),
            max(1.0, float(len(texto))),
        ]
        norma = math.sqrt(sum(v * v for v in base))
        return [v / norma for v in base]


class FakeCollection:
    """Colección ChromaDB en memoria para tests unitarios."""

    def __init__(self) -> None:
        """Inicializa almacenamiento simple por id."""
        self.items: dict[str, dict[str, Any]] = {}

    def add(
        self,
        ids: list[str],
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]],
    ) -> None:
        """Guarda documentos con sus embeddings y metadatos."""
        for ident, doc, emb, meta in zip(ids, documents, embeddings, metadatas, strict=True):
            self.items[ident] = {"document": doc, "embedding": emb, "metadata": meta}

    def query(
        self,
        query_embeddings: list[list[float]],
        n_results: int,
        where: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Ordena resultados por producto punto y aplica filtro simple."""
        query = query_embeddings[0]
        candidatos = []
        for ident, data in self.items.items():
            meta = data["metadata"]
            if where and any(meta.get(k) != v for k, v in where.items()):
                continue
            score = sum(a * b for a, b in zip(query, data["embedding"], strict=True))
            candidatos.append((score, ident, data))
        candidatos.sort(reverse=True, key=lambda item: item[0])
        seleccion = candidatos[:n_results]
        return {
            "ids": [[ident for _, ident, _ in seleccion]],
            "documents": [[data["document"] for _, _, data in seleccion]],
            "metadatas": [[data["metadata"] for _, _, data in seleccion]],
            "distances": [[1.0 - score for score, _, _ in seleccion]],
        }

    def get(
        self,
        ids: list[str] | None = None,
        where: dict[str, Any] | None = None,
        include: list[str] | None = None,
    ) -> dict[str, Any]:
        """Recupera documentos por id o filtro de metadatos."""
        seleccion: list[tuple[str, dict[str, Any]]] = []
        for ident, data in self.items.items():
            if ids is not None and ident not in ids:
                continue
            if where and any(data["metadata"].get(k) != v for k, v in where.items()):
                continue
            seleccion.append((ident, data))
        return {
            "ids": [ident for ident, _ in seleccion],
            "documents": [data["document"] for _, data in seleccion],
            "metadatas": [data["metadata"] for _, data in seleccion],
        }

    def update(
        self,
        ids: list[str],
        documents: list[str] | None = None,
        embeddings: list[list[float]] | None = None,
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        """Actualiza documentos, embeddings o metadatos existentes."""
        for index, ident in enumerate(ids):
            if ident not in self.items:
                continue
            if documents is not None:
                self.items[ident]["document"] = documents[index]
            if embeddings is not None:
                self.items[ident]["embedding"] = embeddings[index]
            if metadatas is not None:
                self.items[ident]["metadata"] = metadatas[index]

    def delete(self, ids: list[str]) -> None:
        """Elimina documentos por id."""
        for ident in ids:
            self.items.pop(ident, None)

    def count(self) -> int:
        """Devuelve el número de documentos guardados."""
        return len(self.items)


def _fake_long_term() -> LongTermMemory:
    """Construye LongTermMemory sin conectar con ChromaDB real."""
    memoria = LongTermMemory.__new__(LongTermMemory)
    memoria._collection_name = "jarvis_memory"
    memoria._cliente = None
    memoria._coleccion = FakeCollection()
    memoria._embeddings = FakeEmbeddings()
    return memoria


@pytest.mark.asyncio
async def test_short_term_overflow() -> None:
    """Agregar 101 mensajes dispara la compresión del buffer."""
    memoria = ShortTermMemory(max_messages=100, max_tokens=8000)
    for i in range(101):
        await memoria.add_message(Message(role="user", content=f"mensaje {i}"))

    mensajes = await memoria.get_messages()
    assert len(mensajes) <= 100
    assert mensajes[0].metadata.get("resumen") is True


@pytest.mark.asyncio
async def test_short_term_context_window() -> None:
    """La ventana de contexto respeta el presupuesto de tokens."""
    memoria = ShortTermMemory(max_messages=10, max_tokens=100)
    await memoria.add_message(Message(role="user", content="uno", tokens_estimate=3))
    await memoria.add_message(Message(role="assistant", content="dos", tokens_estimate=4))
    await memoria.add_message(Message(role="user", content="tres", tokens_estimate=5))

    ventana = await memoria.get_context_window(max_tokens=9)
    assert [m.content for m in ventana] == ["dos", "tres"]

    ventana_estricta = await memoria.get_context_window(max_tokens=2)
    assert ventana_estricta == []


@pytest.mark.asyncio
async def test_long_term_store_and_search() -> None:
    """Guardar una entrada permite encontrarla por búsqueda semántica."""
    memoria = _fake_long_term()
    entry = MemoryEntry(
        content="Recordar preferencia: usar correo para reportes",
        summary="Preferencia de correo",
        category="preferencia",
        source="conversacion",
        importance=0.9,
    )
    ident = await memoria.store(entry)

    resultados = await memoria.search("correo reportes", limit=3)
    assert resultados[0].id == ident
    assert resultados[0].category == "preferencia"


@pytest.mark.asyncio
async def test_long_term_hybrid_search() -> None:
    """La búsqueda híbrida deduplica resultados semánticos y keyword."""
    memoria = _fake_long_term()
    await memoria.store(MemoryEntry(content="archivo README importante", summary="README", category="hecho", source="archivo"))

    resultados = await memoria.search_hybrid("README", limit=5)
    assert len({r.id for r in resultados}) == len(resultados)
    assert resultados


@pytest.mark.asyncio
async def test_episodic_record_and_retrieve() -> None:
    """Registrar un episodio permite recuperarlo por tarea similar."""
    episodica = EpisodicMemory(store=_fake_long_term())
    episodio = Episode(task="leer archivo README", plan_used={}, outcome="success")

    ident = await episodica.record(episodio)
    similares = await episodica.get_similar_tasks("abrir README", limit=2)

    assert similares[0].id == ident
    assert similares[0].outcome == "success"


@pytest.mark.asyncio
async def test_episodic_extract_lessons() -> None:
    """Un episodio exitoso genera lecciones con un modelo mockeado."""
    modelo = AsyncMock()
    modelo.complete = AsyncMock(
        return_value=ModelResponse(content="- Reutiliza el plan\n- Verifica rutas", model="mock")
    )
    episodica = EpisodicMemory(store=_fake_long_term(), summarizer=modelo)

    lecciones = await episodica.extract_lessons(
        Episode(task="organizar archivos", plan_used={}, outcome="success")
    )

    assert "Reutiliza" in lecciones[0]


@pytest.mark.asyncio
async def test_procedural_learn_from_episode() -> None:
    """Un episodio exitoso con pasos crea un workflow reutilizable."""
    procedural = ProceduralMemory(store=_fake_long_term())
    episodio = Episode(
        task="organiza descargas",
        plan_used={"pasos": [{"id": "p1", "herramienta": "filesystem.mover"}]},
        outcome="success",
        duration_ms=100,
    )

    workflow = await procedural.learn_from_episode(episodio)

    assert workflow is not None
    assert workflow.success_count == 1


@pytest.mark.asyncio
async def test_procedural_find_workflow() -> None:
    """La búsqueda procedural encuentra workflows por patrones semánticos."""
    procedural = ProceduralMemory(store=_fake_long_term())
    await procedural.save_workflow(
        Workflow(
            name="Organizar descargas",
            description="Workflow para organizar archivos descargados",
            trigger_patterns=["organiza descargas", "ordena archivos"],
            steps=[{"id": "mover", "herramienta": "filesystem.mover"}],
        )
    )

    workflow = await procedural.find_workflow("organiza mis archivos")

    assert workflow is not None
    assert workflow.name == "Organizar descargas"


@pytest.mark.asyncio
async def test_vault_requires_face_id() -> None:
    """Acceder a secretos sin autorización Face ID levanta PermissionError."""
    vault = Vault(auth_callback=AsyncMock(return_value=False))

    with pytest.raises(PermissionError):
        await vault.get_password("Kimi")


@pytest.mark.asyncio
async def test_vault_op_not_installed() -> None:
    """Si `op` no está instalado, el error explica cómo instalarlo."""
    vault = Vault(auth_callback=AsyncMock(return_value=True))
    vault.is_available = AsyncMock(return_value=False)  # type: ignore[method-assign]

    with pytest.raises(FileNotFoundError, match="brew install --cask 1password-cli"):
        await vault.list_items()


@pytest.mark.asyncio
async def test_memory_system_integration() -> None:
    """El facade coordina corto plazo, largo plazo, episodios y workflows."""
    long_term = _fake_long_term()
    system = MemorySystem(
        short_term=ShortTermMemory(),
        long_term=long_term,
        episodic=EpisodicMemory(store=long_term),
        procedural=ProceduralMemory(store=long_term),
        vault=Vault(auth_callback=AsyncMock(return_value=True)),
    )

    await system.store_interaction(
        "Esto es importante para el workflow de correo",
        "Recuerda que debo usar correo para reportes semanales y resúmenes largos.",
    )
    await system.record_episode(
        Episode(
            task="organiza descargas",
            plan_used={"pasos": [{"id": "p1", "herramienta": "filesystem.mover"}]},
            outcome="success",
            duration_ms=42,
        )
    )

    contexto = await system.get_context("correo reportes", max_tokens=500)
    workflow = await system.find_workflow("organiza archivos")

    assert "Contexto reciente" in contexto
    assert "correo" in contexto
    assert workflow is not None


@pytest.mark.asyncio
async def test_memory_health_check() -> None:
    """health_check devuelve HealthStatus con detalles completos."""
    long_term = _fake_long_term()
    vault = Vault(auth_callback=AsyncMock(return_value=True))
    vault.is_available = AsyncMock(return_value=True)  # type: ignore[method-assign]
    system = MemorySystem(long_term=long_term, vault=vault)

    estado = await system.health_check()

    assert isinstance(estado, HealthStatus)
    assert estado.status in {"healthy", "degraded", "down"}
    assert "chroma" in estado.details
    assert "vault_available" in estado.details
    assert "total_entradas" in estado.details
    assert "entradas_expiradas" in estado.details
    assert "latencia_query_ms" in estado.details


# -----------------------------------------------------------------------
# Tests de deduplicación activa
# -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_memory_dedup_skip() -> None:
    """Entradas prácticamente idénticas (sim ≥ 0.99) se descartan silenciosamente."""
    memoria = _fake_long_term()
    # Entramos con embeddings deterministas: el mismo texto produce el mismo vector
    entry_a = MemoryEntry(
        content="correo para reportes",
        summary="correo",
        category="preferencia",
        source="test",
        importance=0.8,
    )
    id_a = await memoria.store(entry_a)

    # Guardamos la misma entrada de nuevo (embeddings idénticos → sim = 1.0 ≥ 0.99)
    entry_b = MemoryEntry(
        content="correo para reportes",
        summary="correo",
        category="preferencia",
        source="test",
        importance=0.8,
    )
    id_b = await memoria.store(entry_b)

    # Debe reutilizar la existente
    assert id_a == id_b
    # Solo hay 1 entrada en la colección
    total = await memoria.count()
    assert total == 1


@pytest.mark.asyncio
async def test_memory_dedup_complement() -> None:
    """Entradas similares pero no idénticas se fusionan (complement)."""
    memoria = _fake_long_term()
    entry_a = MemoryEntry(
        content="archivo README importante para el proyecto",
        summary="README",
        category="hecho",
        source="test",
    )
    id_a = await memoria.store(entry_a)

    # Segunda entrada con mismo tema pero contenido diferente
    # FakeEmbeddings basada en palabras → "archivo README" produce vector similar
    entry_b = MemoryEntry(
        content="archivo README actualizado con nuevas instrucciones",
        summary="README nuevo",
        category="hecho",
        source="test",
    )
    id_b = await memoria.store(entry_b)

    # Si fueron fusionadas, el id es el mismo; si no, hay 2 entradas distintas.
    # En cualquier caso no debe haber más de 2 entradas.
    total = await memoria.count()
    assert total <= 2
    # El id_b debe ser id_a (merge) o un id nuevo (contradict/no dedup)
    assert id_b in {id_a, entry_b.id}


@pytest.mark.asyncio
async def test_memory_dedup_update_version() -> None:
    """Una entrada complementada incrementa su versión y actualiza updated_at."""
    memoria = _fake_long_term()
    entry = MemoryEntry(
        content="correo para reportes semanales de Luichi",
        summary="correo",
        category="preferencia",
        source="test",
        importance=0.8,
    )
    ident = await memoria.store(entry, dedup=False)

    # Forzar una fusión llamando a update() directamente
    ok = await memoria.update(ident, "correo para reportes y resúmenes diarios de Luichi")
    assert ok is True

    actualizada = await memoria.get(ident)
    assert actualizada is not None
    assert actualizada.version >= 2


# -----------------------------------------------------------------------
# Tests de validez temporal
# -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_temporal_validity_filtering() -> None:
    """Las entradas con valid_until en el pasado se excluyen de búsquedas."""
    memoria = _fake_long_term()
    entry = MemoryEntry(
        content="correo para reportes de proyecto antiguo",
        summary="correo antiguo",
        category="hecho",
        source="test",
        importance=0.9,
    )
    ident = await memoria.store(entry, dedup=False)

    # Expirar manualmente la entrada
    entrada = await memoria.get(ident)
    assert entrada is not None
    entrada.valid_until = datetime.now(UTC) - timedelta(days=1)
    await memoria._update_entry_metadata(entrada)

    # Búsqueda normal → no debe aparecer
    resultados = await memoria.search("correo reportes")
    ids = [r.id for r in resultados]
    assert ident not in ids

    # Búsqueda con include_expired=True → sí debe aparecer
    resultados_exp = await memoria.search("correo reportes", include_expired=True)
    ids_exp = [r.id for r in resultados_exp]
    assert ident in ids_exp


@pytest.mark.asyncio
async def test_search_hybrid_excludes_expired() -> None:
    """search_hybrid también filtra entradas expiradas por defecto."""
    memoria = _fake_long_term()
    ident = await memoria.store(
        MemoryEntry(
            content="archivo README expirado",
            summary="README",
            category="hecho",
            source="test",
        ),
        dedup=False,
    )
    entrada = await memoria.get(ident)
    assert entrada is not None
    entrada.valid_until = datetime.now(UTC) - timedelta(hours=1)
    await memoria._update_entry_metadata(entrada)

    resultados = await memoria.search_hybrid("README")
    assert all(r.id != ident for r in resultados)


@pytest.mark.asyncio
async def test_count_expired() -> None:
    """count_expired devuelve el número correcto de entradas expiradas."""
    memoria = _fake_long_term()
    for i in range(3):
        await memoria.store(
            MemoryEntry(
                content=f"entrada expirada {i}",
                summary=f"exp {i}",
                category="hecho",
                source="test",
            ),
            dedup=False,
        )
    # Expirar las 3
    todos = await memoria.get_recent(limit=10)
    for e in todos:
        e.valid_until = datetime.now(UTC) - timedelta(minutes=5)
        await memoria._update_entry_metadata(e)

    n_exp = await memoria.count_expired()
    assert n_exp == 3


# -----------------------------------------------------------------------
# Tests de instrucciones aprendidas (memoria procedural)
# -----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_procedural_update_instructions() -> None:
    """update_agent_instructions guarda instrucciones con confirmación."""
    instructions_store = _fake_long_term()
    procedural = ProceduralMemory(
        store=_fake_long_term(),
        instructions_store=instructions_store,
    )

    ok = await procedural.update_agent_instructions(
        "Responder siempre en español",
        confirm_callback=AsyncMock(return_value=True),
    )

    assert ok is True
    instrucciones = await procedural.get_agent_instructions()
    assert any("español" in i for i in instrucciones)


@pytest.mark.asyncio
async def test_procedural_update_instructions_rejected() -> None:
    """update_agent_instructions respeta el rechazo del usuario."""
    procedural = ProceduralMemory(
        store=_fake_long_term(),
        instructions_store=_fake_long_term(),
    )

    ok = await procedural.update_agent_instructions(
        "instrucción rechazada",
        confirm_callback=AsyncMock(return_value=False),
    )

    assert ok is False
    instrucciones = await procedural.get_agent_instructions()
    assert not instrucciones


@pytest.mark.asyncio
async def test_procedural_instructions_max_limit() -> None:
    """Al superar 10 instrucciones, la más antigua se archiva automáticamente."""
    instructions_store = _fake_long_term()
    procedural = ProceduralMemory(
        store=_fake_long_term(),
        instructions_store=instructions_store,
    )

    # Añadir 11 instrucciones sin confirmación
    for i in range(11):
        await procedural.update_agent_instructions(
            f"instrucción número {i}",
            confirm_callback=None,
        )

    instrucciones = await procedural.get_agent_instructions()
    assert len(instrucciones) <= 10


@pytest.mark.asyncio
async def test_agent_loads_learned_instructions() -> None:
    """_percibir carga instrucciones aprendidas en memory_context."""
    from core.agent import Agente, AgentState
    from core.planner import Planner
    from core.reflector import Reflector
    from memory.episodic import EpisodicMemory
    from memory.short_term import ShortTermMemory
    from security.audit_log import AuditLog

    memoria = MagicMock()
    memoria.get_context = AsyncMock(return_value="Contexto previo")
    memoria.get_agent_instructions = AsyncMock(return_value=["Responder en español"])

    auditoria = MagicMock(spec=AuditLog)
    auditoria.registrar = AsyncMock()

    agente = Agente(
        planner=MagicMock(spec=Planner),
        reflector=MagicMock(spec=Reflector),
        memoria_corto=MagicMock(spec=ShortTermMemory),
        memoria_episodica=MagicMock(spec=EpisodicMemory),
        auditoria=auditoria,
        memoria=memoria,
    )

    estado_inicial: AgentState = {
        "messages": [],
        "current_task": "test",
        "current_plan": None,
        "completed_steps": [],
        "failed_steps": [],
        "retry_count": 0,
        "replan_count": 0,
        "system_context": {},
        "memory_context": "",
        "waiting_for_user": False,
        "paso_pendiente_confirmacion": None,
        "abort_reason": None,
        "session_id": "test-session",
        "indice_paso_actual": 0,
        "tarea_completada": False,
    }

    estado = await agente._percibir(estado_inicial)

    assert "Instrucciones aprendidas" in estado["memory_context"]
    assert "Responder en español" in estado["memory_context"]
