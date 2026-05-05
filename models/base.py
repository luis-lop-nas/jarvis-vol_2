"""Interfaz abstracta común a todos los proveedores de modelos.

Define el contrato uniforme (`BaseModel`) y los tipos de datos compartidos
(`Mensaje`, `ModelResponse`, `StreamChunk`, `ModelCapability`, `ModelConfig`).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Flag, auto
from types import TracebackType
from typing import Any, AsyncIterator, Literal, Self

Rol = Literal["system", "user", "assistant", "tool"]


# ---------------------------------------------------------------------------
# Mensajes y respuestas
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Mensaje:
    """Mensaje individual dentro de una conversación.

    Si `imagenes_base64` no está vacío, los proveedores con capacidad
    `VISION` deben empaquetarlas según su formato (data URL en OpenAI-compat).

    Ejemplo:
        >>> Mensaje(rol="user", contenido="¿Qué ves?", imagenes_base64=["..."])
    """

    rol: Rol
    contenido: str
    nombre: str | None = None
    imagenes_base64: list[str] = field(default_factory=list)
    metadatos: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ModelResponse:
    """Respuesta normalizada devuelta por cualquier modelo.

    Ejemplo:
        >>> resp = ModelResponse(content="hola", model="kimi-k2.6",
        ...                      tokens_input=10, tokens_output=2)
        >>> resp.cached
        False
    """

    content: str
    model: str
    tokens_input: int = 0
    tokens_output: int = 0
    duration_ms: int = 0
    cached: bool = False
    finish_reason: str | None = None
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    thinking: str | None = None
    cost_usd: float = 0.0
    metadatos: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StreamChunk:
    """Trozo individual emitido durante streaming.

    Ejemplo:
        >>> StreamChunk(content="hola", model="kimi-k2.6").content
        'hola'
    """

    content: str
    model: str
    is_thinking: bool = False
    is_final: bool = False
    tokens_per_second: float | None = None


# ---------------------------------------------------------------------------
# Capacidades y configuración
# ---------------------------------------------------------------------------


class ModelCapability(Flag):
    """Capacidades soportadas por un modelo.

    Ejemplo:
        >>> bool(ModelCapability.TEXT & (ModelCapability.TEXT | ModelCapability.VISION))
        True
    """

    TEXT = auto()
    VISION = auto()
    EMBEDDING = auto()
    TOOL_USE = auto()
    THINKING = auto()


@dataclass(slots=True)
class ModelConfig:
    """Configuración de un cliente concreto.

    Ejemplo:
        >>> ModelConfig(name="kimi-k2.6").timeout
        60.0
    """

    name: str
    api_key: str = ""
    base_url: str = ""
    timeout: float = 60.0
    max_retries: int = 3
    capabilities: ModelCapability = ModelCapability.TEXT


# ---------------------------------------------------------------------------
# Interfaz abstracta
# ---------------------------------------------------------------------------


class BaseModel(ABC):
    """Contrato uniforme para proveedores de modelos.

    Toda implementación concreta (Kimi, DeepSeek, Ollama, OpenRouter) debe
    implementar `complete`, `stream` y `health_check`. Los proveedores que
    no soporten embeddings dejan la implementación por defecto, que lanza
    `NotImplementedError`.

    Soporta uso como context manager asíncrono:

    Ejemplo:
        >>> async def uso():
        ...     async with KimiModel() as kimi:
        ...         return await kimi.health_check()
    """

    nombre: str = "base"

    def __init__(self, config: ModelConfig) -> None:
        self.config = config

    # --- API principal ---------------------------------------------------

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
    ) -> ModelResponse:
        """Genera una respuesta completa de forma síncrona desde el cliente."""

    @abstractmethod
    def stream(
        self,
        mensajes: list[Mensaje],
        *,
        modelo: str | None = None,
        temperatura: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Genera la respuesta token a token como `AsyncIterator[StreamChunk]`."""

    async def embed(self, textos: list[str]) -> list[list[float]]:
        """Calcula embeddings; sobrescrito por proveedores con la capacidad."""
        raise NotImplementedError(
            f"{self.__class__.__name__} no soporta embeddings."
        )

    @abstractmethod
    async def health_check(self) -> bool:
        """Devuelve `True` si el proveedor responde correctamente."""

    # --- Capacidades -----------------------------------------------------

    def soporta(self, capacidad: ModelCapability) -> bool:
        """`True` si el modelo declara la capacidad indicada."""
        return capacidad in self.config.capabilities

    # --- Ciclo de vida ---------------------------------------------------

    async def cerrar(self) -> None:
        """Libera recursos (conexiones HTTP, sockets). Override opcional."""
        return None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.cerrar()
