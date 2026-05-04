"""OCR sobre imágenes capturadas (Tesseract por defecto)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytesseract
from PIL import Image


@dataclass(slots=True)
class CajaTexto:
    """Texto detectado con su bounding box en píxeles."""

    texto: str
    x: int
    y: int
    ancho: int
    alto: int
    confianza: float


class OCR:
    """Wrapper asíncrono sobre Tesseract."""

    def __init__(self, idiomas: str = "spa+eng") -> None:
        self._idiomas = idiomas

    async def extraer_texto(self, imagen: Image.Image) -> str:
        """Devuelve todo el texto detectado en una sola cadena."""
        return await asyncio.to_thread(
            pytesseract.image_to_string, imagen, lang=self._idiomas
        )

    async def extraer_cajas(self, imagen: Image.Image) -> list[CajaTexto]:
        """Devuelve las cajas detectadas con su confianza."""
        datos = await asyncio.to_thread(
            pytesseract.image_to_data,
            imagen,
            lang=self._idiomas,
            output_type=pytesseract.Output.DICT,
        )
        cajas: list[CajaTexto] = []
        for i, texto in enumerate(datos["text"]):
            if not texto.strip():
                continue
            cajas.append(
                CajaTexto(
                    texto=texto,
                    x=int(datos["left"][i]),
                    y=int(datos["top"][i]),
                    ancho=int(datos["width"][i]),
                    alto=int(datos["height"][i]),
                    confianza=float(datos["conf"][i]),
                )
            )
        return cajas
