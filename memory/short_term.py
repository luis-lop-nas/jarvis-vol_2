"""Memoria de corto plazo: ventana de conversación reciente."""

from __future__ import annotations

from collections import deque
from typing import Iterable

from models.base import Mensaje


class MemoriaCortoPlazo:
    """Buffer circular con los últimos `N` turnos de la conversación.

    Es la memoria que se pasa íntegramente al modelo en cada llamada.
    """

    def __init__(self, capacidad: int = 50) -> None:
        self._buffer: deque[Mensaje] = deque(maxlen=capacidad)

    def añadir(self, mensaje: Mensaje) -> None:
        self._buffer.append(mensaje)

    def añadir_muchos(self, mensajes: Iterable[Mensaje]) -> None:
        self._buffer.extend(mensajes)

    def todos(self) -> list[Mensaje]:
        return list(self._buffer)

    def ultimos(self, n: int) -> list[Mensaje]:
        return list(self._buffer)[-n:]

    def limpiar(self) -> None:
        self._buffer.clear()

    def __len__(self) -> int:
        return len(self._buffer)
