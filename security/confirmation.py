"""Gestor de confirmaciones humanas para acciones destructivas."""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from core.planner import PasoPlan

# Función que devuelve True si el usuario aprueba y False si rechaza.
CallbackConfirmacion = Callable[[PasoPlan], Awaitable[bool]]


class GestorConfirmacion:
    """Solicita aprobación humana antes de ejecutar pasos peligrosos.

    El callback puede ser una notificación push, una pregunta en el chat o
    un diálogo nativo de macOS. Por defecto autodeniega (modo seguro).
    """

    def __init__(self, callback: CallbackConfirmacion | None = None, timeout: float = 60.0) -> None:
        self._callback = callback or self._denegar_por_defecto
        self._timeout = timeout

    async def solicitar(self, paso: PasoPlan) -> bool:
        """Pide confirmación; expira en `timeout` segundos como rechazo."""
        try:
            return await asyncio.wait_for(self._callback(paso), timeout=self._timeout)
        except asyncio.TimeoutError:
            return False

    @staticmethod
    async def _denegar_por_defecto(paso: PasoPlan) -> bool:
        _ = paso
        return False
