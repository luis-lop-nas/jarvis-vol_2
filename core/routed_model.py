"""Modelo enrutado: adapta el `ModelRouter` a la interfaz `BaseModel`.

Planner y Reflector reciben un único objeto que por dentro:
1. Elige el modelo por petición con `router.route()` (visión→Gemini, sensible→local, …).
2. Ante un fallo transitorio (429/402/5xx, timeout, transporte) recorre la
   `fallback_chain` en caliente en vez de abortar la tarea.
3. Alimenta el circuit breaker y el coste acumulado del router.

Esto sustituye la selección de un único modelo fijo al arrancar (`_seleccionar_modelo`)
por enrutado per-request con fallback real.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

import httpx

from core.router import ContextoRuteo, ModeloDestino, destino_por_defecto
from models.base import BaseModel, Mensaje, ModelConfig, ModelResponse, StreamChunk

if TYPE_CHECKING:
    from core.router import ModelRouter

log = logging.getLogger(__name__)

# Códigos HTTP que se consideran "modelo no disponible" → probar el siguiente.
# 401/403 (auth), 402 (sin saldo), 408/425/429 (rate/timeout), 5xx (servidor).
_TRANSITORIOS: frozenset[int] = frozenset({401, 402, 403, 408, 425, 429, 500, 502, 503, 504})


class RoutedModel(BaseModel):
    """Fachada `BaseModel` que enruta cada petición y hace fallback en caliente."""

    nombre = "routed"

    def __init__(self, router: ModelRouter, *, audit_log: Any = None) -> None:
        super().__init__(ModelConfig(name="routed"))
        self._router = router
        self._audit_log = audit_log

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _tarea(mensajes: list[Mensaje]) -> str:
        """Texto de la petición para las reglas de enrutado (último turno de usuario)."""
        for m in reversed(mensajes):
            if m.rol == "user" and m.contenido:
                return m.contenido
        return mensajes[-1].contenido if mensajes else ""

    def _cadena(self, mensajes: list[Mensaje]) -> list[ModeloDestino]:
        seleccion = self._router.route(
            self._tarea(mensajes), ContextoRuteo(mensajes=mensajes)
        )
        return [seleccion.model_name, *seleccion.fallback_chain]

    @staticmethod
    def _es_transitorio(exc: Exception) -> bool:
        if isinstance(exc, httpx.HTTPStatusError):
            return exc.response.status_code in _TRANSITORIOS
        return isinstance(exc, (httpx.TransportError, TimeoutError))

    # ------------------------------------------------------------------
    # API principal
    # ------------------------------------------------------------------

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
        """Enruta y ejecuta; recorre la cadena de fallback ante fallo transitorio."""
        cadena = self._cadena(mensajes)
        ultimo: Exception | None = None
        for destino in cadena:
            cliente = self._router.obtener_cliente(destino)
            try:
                resp = await cliente.complete(
                    mensajes,
                    temperatura=temperatura,
                    max_tokens=max_tokens,
                    herramientas=herramientas,
                    **kwargs,
                )
                self._router.registrar_exito_modelo(destino)
                self._router.registrar_coste(resp.cost_usd)
                return resp
            except Exception as exc:  # noqa: BLE001 — clasificamos abajo
                if not self._es_transitorio(exc):
                    raise
                self._router.registrar_fallo_modelo(destino)
                ultimo = exc
                log.warning(
                    "Modelo %s no disponible (%s); probando fallback",
                    destino.value, str(exc)[:100],
                )
        raise ultimo or RuntimeError("Ningún modelo disponible en la cadena de enrutado")

    async def stream(
        self,
        mensajes: list[Mensaje],
        *,
        modelo: str | None = None,
        temperatura: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        """Streaming con fallback solo antes del primer chunk (no se puede des-emitir)."""
        cadena = self._cadena(mensajes)
        ultimo: Exception | None = None
        for destino in cadena:
            cliente = self._router.obtener_cliente(destino)
            emitido = False
            try:
                async for chunk in cliente.stream(
                    mensajes, temperatura=temperatura, max_tokens=max_tokens, **kwargs
                ):
                    emitido = True
                    yield chunk
                self._router.registrar_exito_modelo(destino)
                return
            except Exception as exc:  # noqa: BLE001
                if emitido or not self._es_transitorio(exc):
                    raise
                self._router.registrar_fallo_modelo(destino)
                ultimo = exc
                log.warning(
                    "Stream de %s no disponible (%s); probando fallback",
                    destino.value, str(exc)[:100],
                )
        raise ultimo or RuntimeError("Ningún modelo disponible en la cadena de enrutado")

    async def health_check(self) -> bool:
        """`True` si el destino por defecto responde."""
        cliente = self._router.obtener_cliente(destino_por_defecto())
        return await cliente.health_check()

    async def cerrar(self) -> None:
        await self._router.cerrar()
