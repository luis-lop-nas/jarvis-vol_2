"""Utilidades compartidas por los clientes de modelos.

- `RetryPolicy`: backoff exponencial sobre 429/5xx.
- `TTLCache`: caché LRU + TTL por hash de mensajes.
- `CircuitBreaker`: cortocircuito por proveedor (3 fallos / 60 s → OPEN 5 min).
- `log_model_call`: registra métricas de llamada en el audit_log.
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
from enum import StrEnum
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


# ---------------------------------------------------------------------------
# Circuit breaker por proveedor
# ---------------------------------------------------------------------------


class EstadoCircuito(StrEnum):
    """Estados posibles del circuit breaker."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Cortocircuito por proveedor: 3 fallos en 60 s → OPEN 5 min → HALF_OPEN.

    Ejemplo::
        cb = CircuitBreaker()
        if cb.is_open():
            raise RuntimeError("Proveedor no disponible")
        try:
            result = await call_provider()
            cb.registrar_exito()
        except Exception:
            cb.registrar_fallo()
            raise
    """

    def __init__(
        self,
        max_fallos: int = 3,
        ventana_s: float = 60.0,
        tiempo_recuperacion_s: float = 300.0,
    ) -> None:
        self._max_fallos = max_fallos
        self._ventana = ventana_s
        self._tiempo_recuperacion = tiempo_recuperacion_s
        self._fallos: list[float] = []
        self._apertura: float | None = None

    def is_open(self) -> bool:
        """True si el circuito está OPEN (rechaza peticiones)."""
        if self._apertura is None:
            return False
        return time.monotonic() - self._apertura < self._tiempo_recuperacion

    def estado(self) -> EstadoCircuito:
        """Estado actual del circuito."""
        if self._apertura is None:
            return EstadoCircuito.CLOSED
        if time.monotonic() - self._apertura >= self._tiempo_recuperacion:
            return EstadoCircuito.HALF_OPEN
        return EstadoCircuito.OPEN

    def registrar_fallo(self) -> None:
        """Registra un fallo; abre el circuito si se superan los umbrales."""
        ahora = time.monotonic()
        self._fallos = [t for t in self._fallos if ahora - t < self._ventana]
        self._fallos.append(ahora)
        if len(self._fallos) >= self._max_fallos:
            self._apertura = ahora
            log.warning(
                "CircuitBreaker ABIERTO: %d fallos en %.0f s",
                len(self._fallos),
                self._ventana,
            )

    def registrar_exito(self) -> None:
        """Registra éxito; cierra el circuito si estaba abierto."""
        if self._apertura is not None:
            log.info("CircuitBreaker CERRADO tras recuperación")
        self._fallos.clear()
        self._apertura = None


# ---------------------------------------------------------------------------
# Log estructurado de llamadas a modelo
# ---------------------------------------------------------------------------


async def log_model_call(
    audit_log: Any | None,
    *,
    modelo: str,
    tokens_input: int,
    tokens_output: int,
    latencia_ms: int,
    cost_usd: float,
    cache_hit: bool,
    session_id: str = "",
) -> None:
    """Registra métricas de una llamada a modelo en el audit_log.

    No registra contenido — solo métricas (privacidad por diseño).

    Ejemplo::
        await log_model_call(
            audit_log, modelo="kimi-k2.6",
            tokens_input=120, tokens_output=80,
            latencia_ms=340, cost_usd=0.000030, cache_hit=False,
        )
    """
    if audit_log is None:
        return
    await audit_log.log_action(
        session_id=session_id,
        action_type="model_call",
        action="complete",
        details={
            "modelo": modelo,
            "tokens_input": tokens_input,
            "tokens_output": tokens_output,
            "cost_usd": round(cost_usd, 8),
            "cache_hit": cache_hit,
        },
        result="success",
        risk_level="safe",
        confirmed=True,
        authenticated=False,
        duration_ms=latencia_ms,
    )


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
