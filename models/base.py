"""Interfaz abstracta común a todos los proveedores de modelos."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Literal

Rol = Literal["system", "user", "assistant", "tool"]


@dataclass(slots=True)
class Mensaje:
    """Mensaje individual dentro de una conversación."""

    rol: Rol
    contenido: str
    nombre: str | None = None
    metadatos: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RespuestaModelo:
    """Respuesta normalizada devuelta por cualquier modelo."""

    contenido: str
    modelo: str
    tokens_entrada: int = 0
    tokens_salida: int = 0
    razon_finalizacion: str | None = None
    llamadas_herramientas: list[dict[str, Any]] = field(default_factory=list)
    metadatos: dict[str, Any] = field(default_factory=dict)


class BaseModel(ABC):
    """Contrato uniforme para proveedores de modelos.

    Toda implementación concreta (Kimi, DeepSeek, Ollama, OpenRouter) debe
    implementar `complete`, `stream` y `embed`. Las clases que no soporten
    embeddings deben lanzar `NotImplementedError` en `embed`.
    """

    nombre: str
    modelo_por_defecto: str

    def __init__(self, modelo: str | None = None) -> None:
        if modelo is not None:
            self.modelo_por_defecto = modelo

    @abstractmethod
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
        """Genera una respuesta completa de forma síncrona desde el cliente."""

    @abstractmethod
    async def stream(
        self,
        mensajes: list[Mensaje],
        *,
        modelo: str | None = None,
        temperatura: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Genera la respuesta token a token (yield de strings)."""

    @abstractmethod
    async def embed(self, textos: list[str]) -> list[list[float]]:
        """Devuelve el vector de embedding para cada texto de la lista."""

    async def cerrar(self) -> None:
        """Libera recursos asíncronos (conexiones HTTP, etc.). Override opcional."""
        return None
