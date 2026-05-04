"""Captura de pantalla en macOS usando Quartz."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from PIL import Image


@dataclass(slots=True)
class Captura:
    """Captura serializable de la pantalla."""

    imagen: Image.Image
    ancho: int
    alto: int
    pantalla_id: int


class CapturadorPantalla:
    """Encapsula la API de captura nativa para todas las pantallas conectadas."""

    def __init__(self) -> None:
        # Importación perezosa: pyobjc solo está disponible en macOS.
        from Quartz import CGMainDisplayID  # type: ignore[import-not-found]

        self._main_display_id = CGMainDisplayID()

    async def capturar_principal(self) -> Captura:
        """Captura la pantalla principal."""
        return await asyncio.to_thread(self._capturar_sync, self._main_display_id)

    async def capturar_region(self, x: int, y: int, ancho: int, alto: int) -> Captura:
        """Captura un rectángulo concreto de la pantalla principal."""
        return await asyncio.to_thread(self._capturar_region_sync, x, y, ancho, alto)

    async def guardar(self, captura: Captura, destino: Path) -> Path:
        """Persiste la captura en disco como PNG."""
        await asyncio.to_thread(captura.imagen.save, destino, "PNG")
        return destino

    # ------------------------------------------------------------------
    # Implementación (bloqueante, ejecutada en thread pool)
    # ------------------------------------------------------------------

    def _capturar_sync(self, display_id: int) -> Captura:
        from Quartz import CGDisplayCreateImage  # type: ignore[import-not-found]

        cg_imagen = CGDisplayCreateImage(display_id)
        return self._cgimage_a_captura(cg_imagen, display_id)

    def _capturar_region_sync(self, x: int, y: int, ancho: int, alto: int) -> Captura:
        from Quartz import (  # type: ignore[import-not-found]
            CGDisplayCreateImageForRect,
            CGRectMake,
        )

        rect = CGRectMake(x, y, ancho, alto)
        cg_imagen = CGDisplayCreateImageForRect(self._main_display_id, rect)
        return self._cgimage_a_captura(cg_imagen, self._main_display_id)

    @staticmethod
    def _cgimage_a_captura(cg_imagen: object, display_id: int) -> Captura:
        from Quartz import (  # type: ignore[import-not-found]
            CGImageGetHeight,
            CGImageGetWidth,
        )

        ancho = CGImageGetWidth(cg_imagen)
        alto = CGImageGetHeight(cg_imagen)
        # Conversión a PIL: el camino más fiable es vía buffer crudo.
        imagen = _cgimage_a_pil(cg_imagen, ancho, alto)
        return Captura(imagen=imagen, ancho=ancho, alto=alto, pantalla_id=display_id)


def _cgimage_a_pil(cg_imagen: object, ancho: int, alto: int) -> Image.Image:
    """Convierte un CGImageRef en una imagen PIL."""
    from Quartz import (  # type: ignore[import-not-found]
        CGDataProviderCopyData,
        CGImageGetDataProvider,
    )

    proveedor = CGImageGetDataProvider(cg_imagen)
    datos = CGDataProviderCopyData(proveedor)
    bytes_imagen = bytes(datos)
    return Image.frombuffer("RGBA", (ancho, alto), bytes_imagen, "raw", "BGRA", 0, 1)
