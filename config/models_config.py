"""Catálogo de modelos disponibles y sus capacidades.

Este módulo es la fuente única de verdad sobre qué modelos puede usar
el router, qué proveedor los sirve y qué características tiene cada uno
(coste, contexto, soporte de visión, etc.).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Proveedor(StrEnum):
    """Proveedores soportados por JARVIS."""

    OLLAMA = "ollama"
    KIMI = "kimi"
    DEEPSEEK = "deepseek"
    OPENROUTER = "openrouter"


class Capacidad(StrEnum):
    """Capacidades que puede tener un modelo."""

    TEXTO = "texto"
    VISION = "vision"
    HERRAMIENTAS = "herramientas"
    EMBEDDINGS = "embeddings"
    RAZONAMIENTO = "razonamiento"


@dataclass(frozen=True, slots=True)
class PerfilModelo:
    """Descripción declarativa de un modelo concreto."""

    id: str
    proveedor: Proveedor
    contexto_maximo: int
    capacidades: frozenset[Capacidad]
    coste_por_1k_entrada: float = 0.0
    coste_por_1k_salida: float = 0.0
    es_local: bool = False


CATALOGO: dict[str, PerfilModelo] = {
    "llama3.2": PerfilModelo(
        id="llama3.2",
        proveedor=Proveedor.OLLAMA,
        contexto_maximo=128_000,
        capacidades=frozenset({Capacidad.TEXTO, Capacidad.HERRAMIENTAS}),
        es_local=True,
    ),
    "qwen2.5-coder": PerfilModelo(
        id="qwen2.5-coder",
        proveedor=Proveedor.OLLAMA,
        contexto_maximo=128_000,
        capacidades=frozenset({Capacidad.TEXTO, Capacidad.HERRAMIENTAS}),
        es_local=True,
    ),
    "nomic-embed-text": PerfilModelo(
        id="nomic-embed-text",
        proveedor=Proveedor.OLLAMA,
        contexto_maximo=8_192,
        capacidades=frozenset({Capacidad.EMBEDDINGS}),
        es_local=True,
    ),
    "moonshot-v1-128k": PerfilModelo(
        id="moonshot-v1-128k",
        proveedor=Proveedor.KIMI,
        contexto_maximo=128_000,
        capacidades=frozenset({Capacidad.TEXTO, Capacidad.HERRAMIENTAS}),
        coste_por_1k_entrada=0.012,
        coste_por_1k_salida=0.012,
    ),
    "deepseek-chat": PerfilModelo(
        id="deepseek-chat",
        proveedor=Proveedor.DEEPSEEK,
        contexto_maximo=64_000,
        capacidades=frozenset({Capacidad.TEXTO, Capacidad.HERRAMIENTAS}),
        coste_por_1k_entrada=0.00014,
        coste_por_1k_salida=0.00028,
    ),
    "deepseek-reasoner": PerfilModelo(
        id="deepseek-reasoner",
        proveedor=Proveedor.DEEPSEEK,
        contexto_maximo=64_000,
        capacidades=frozenset(
            {Capacidad.TEXTO, Capacidad.RAZONAMIENTO, Capacidad.HERRAMIENTAS}
        ),
        coste_por_1k_entrada=0.00055,
        coste_por_1k_salida=0.00219,
    ),
}


def obtener_perfil(model_id: str) -> PerfilModelo:
    """Devuelve el perfil de un modelo por su id; lanza KeyError si no existe."""
    return CATALOGO[model_id]


def modelos_por_proveedor(proveedor: Proveedor) -> list[PerfilModelo]:
    """Lista los modelos disponibles de un proveedor concreto."""
    return [p for p in CATALOGO.values() if p.proveedor == proveedor]


def modelos_con_capacidad(capacidad: Capacidad) -> list[PerfilModelo]:
    """Lista los modelos que ofrecen una capacidad determinada."""
    return [p for p in CATALOGO.values() if capacidad in p.capacidades]
