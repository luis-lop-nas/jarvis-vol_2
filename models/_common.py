"""Utilidades compartidas por los clientes de modelos.

- `RetryPolicy`: backoff exponencial sobre 429/5xx.
- `TTLCache`: caché LRU + TTL por hash de mensajes.
- `estimar_tokens`: aproximación grosera (no para facturación, solo logs).
- `aplicar_imagenes`: empaqueta imágenes base64 al formato OpenAI-compat.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

import httpx

from models.base import Mensaje

T = TypeVar("T")
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Retry con backoff exponencial
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RetryPolicy:
    """Política de reintentos sobre errores transitorios HTTP.

    Reintenta en 429 (rate limit) y 5xx, con backoff exponencial + jitter.

    Ejemplo:
        >>> RetryPolicy(max_intentos=3, base_segundos=0.5).max_intentos
        3
    """

    max_intentos: int = 3
    base_segundos: float = 1.0
    factor: float = 2.0
    max_segundos: float = 30.0

    async def ejecutar(self, fn: Callable[[], Awaitable[T]]) -> T:
        """Ejecuta `fn` aplicando reintentos sobre errores transitorios."""
        ultimo_error: Exception | None = None
        for intento in range(1, self.max_intentos + 1):
            try:
                return await fn()
            except httpx.HTTPStatusError as exc:
                codigo = exc.response.status_code
                if codigo not in (429, 500, 502, 503, 504) or intento == self.max_intentos:
                    raise
                ultimo_error = exc
            except (TimeoutError, httpx.TransportError) as exc:
                if intento == self.max_intentos:
                    raise
                ultimo_error = exc

            espera = min(
                self.max_segundos,
                self.base_segundos * (self.factor ** (intento - 1)),
            ) + random.uniform(0, 0.3)
            log.warning(
                "Reintento %d/%d tras %.2fs (%s)",
                intento,
                self.max_intentos,
                espera,
                ultimo_error,
            )
            await asyncio.sleep(espera)

        raise RuntimeError("ejecutar() llegó a un estado imposible")


# ---------------------------------------------------------------------------
# Caché TTL para respuestas idénticas
# ---------------------------------------------------------------------------


class TTLCache:
    """Caché LRU + TTL para `complete()` (no aplica a streaming).

    La clave se construye como hash SHA-256 del modelo + mensajes + temperatura.

    Ejemplo:
        >>> c = TTLCache(max_entradas=8, ttl_segundos=60)
        >>> c.put("k", "v")
        >>> c.get("k")
        'v'
    """

    def __init__(self, max_entradas: int = 256, ttl_segundos: int = 300) -> None:
        self._datos: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._max = max_entradas
        self._ttl = ttl_segundos

    def clave(
        self,
        modelo: str,
        mensajes: list[Mensaje],
        temperatura: float,
        extras: dict[str, Any] | None = None,
    ) -> str:
        """Calcula una clave determinista para el conjunto de inputs."""
        h = hashlib.sha256()
        h.update(modelo.encode())
        h.update(f"{temperatura:.4f}".encode())
        for m in mensajes:
            h.update(m.rol.encode())
            h.update(m.contenido.encode())
            for img in m.imagenes_base64:
                h.update(img.encode())
        if extras:
            for k in sorted(extras):
                h.update(f"{k}={extras[k]}".encode())
        return h.hexdigest()

    def get(self, clave: str) -> Any | None:
        """Devuelve el valor si existe y no ha expirado; mueve al final (LRU)."""
        entrada = self._datos.get(clave)
        if entrada is None:
            return None
        creado, valor = entrada
        if time.monotonic() - creado > self._ttl:
            self._datos.pop(clave, None)
            return None
        self._datos.move_to_end(clave)
        return valor

    def put(self, clave: str, valor: Any) -> None:
        """Inserta o actualiza; expulsa la entrada menos reciente si hace falta."""
        self._datos[clave] = (time.monotonic(), valor)
        self._datos.move_to_end(clave)
        if len(self._datos) > self._max:
            self._datos.popitem(last=False)

    def limpiar(self) -> None:
        self._datos.clear()


# ---------------------------------------------------------------------------
# Helpers de mensajes y tokens
# ---------------------------------------------------------------------------


def estimar_tokens(texto: str) -> int:
    """Estimación grosera: ~4 caracteres por token. Solo para logs/heurísticas."""
    return max(1, len(texto) // 4)


def mensaje_a_dict(mensaje: Mensaje) -> dict[str, Any]:
    """Serializa un `Mensaje` al formato OpenAI-compat, expandiendo imágenes."""
    if not mensaje.imagenes_base64:
        base: dict[str, Any] = {"role": mensaje.rol, "content": mensaje.contenido}
        if mensaje.nombre:
            base["name"] = mensaje.nombre
        return base

    partes: list[dict[str, Any]] = [{"type": "text", "text": mensaje.contenido}]
    for img in mensaje.imagenes_base64:
        url = img if img.startswith("data:") else f"data:image/png;base64,{img}"
        partes.append({"type": "image_url", "image_url": {"url": url}})
    return {"role": mensaje.rol, "content": partes}
