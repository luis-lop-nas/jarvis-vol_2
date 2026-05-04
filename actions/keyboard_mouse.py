"""Control programático de teclado y ratón."""

from __future__ import annotations

import asyncio


class RatonTeclado:
    """Wrapper asíncrono sobre pyautogui (input system-wide)."""

    def __init__(self, pausa_entre_acciones: float = 0.05) -> None:
        import pyautogui

        pyautogui.PAUSE = pausa_entre_acciones
        pyautogui.FAILSAFE = True
        self._py = pyautogui

    async def mover(self, x: int, y: int, duracion: float = 0.2) -> None:
        """Mueve el cursor al píxel (x, y) con interpolación suave."""
        await asyncio.to_thread(self._py.moveTo, x, y, duracion)

    async def click(self, x: int | None = None, y: int | None = None, boton: str = "left") -> None:
        """Click en la posición indicada o donde esté el cursor."""
        await asyncio.to_thread(self._py.click, x, y, button=boton)

    async def doble_click(self, x: int, y: int) -> None:
        await asyncio.to_thread(self._py.doubleClick, x, y)

    async def arrastrar(
        self, desde: tuple[int, int], hasta: tuple[int, int], duracion: float = 0.5
    ) -> None:
        await asyncio.to_thread(self._py.moveTo, *desde)
        await asyncio.to_thread(
            self._py.dragTo, hasta[0], hasta[1], duration=duracion, button="left"
        )

    async def escribir(self, texto: str, intervalo: float = 0.02) -> None:
        """Escribe texto carácter a carácter."""
        await asyncio.to_thread(self._py.typewrite, texto, intervalo)

    async def pulsar(self, *teclas: str) -> None:
        """Pulsa una combinación de teclas (ej. 'cmd', 'c' para copiar)."""
        await asyncio.to_thread(self._py.hotkey, *teclas)

    async def scroll(self, clicks: int) -> None:
        """Scroll vertical (positivo = arriba)."""
        await asyncio.to_thread(self._py.scroll, clicks)

    async def posicion(self) -> tuple[int, int]:
        return await asyncio.to_thread(lambda: tuple(self._py.position()))  # type: ignore[return-value]
