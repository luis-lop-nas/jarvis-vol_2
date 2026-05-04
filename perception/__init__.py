"""Sensores: cómo JARVIS percibe el sistema (pantalla, OCR, accesibilidad)."""

from perception.accessibility import ArbolAccesibilidad
from perception.ocr import OCR
from perception.screenshot import CapturadorPantalla
from perception.system_state import EstadoSistema

__all__ = ["ArbolAccesibilidad", "CapturadorPantalla", "EstadoSistema", "OCR"]
