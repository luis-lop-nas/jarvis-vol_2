"""Captura de pantalla nativa macOS via screencapture (más rápido que Quartz en M3).

Decisión de diseño: screencapture CLI en vez de Quartz directamente porque en M3
la llamada al proceso externo evita la latencia de binding Python→ObjC para capturas
grandes, y el PNG sale comprimido directamente sin pasar por PIL en el caso normal.
"""

from __future__ import annotations

import asyncio
import base64
import io
import subprocess
import time
from pathlib import Path

# ── Rate limiter ─────────────────────────────────────────────────────────────
# Máximo 2 capturas/segundo en todo el proceso para no saturar el pipeline.
_CAPTURE_LOCK = asyncio.Lock()
_ULTIMA_CAPTURA: float = 0.0
_INTERVALO_MINIMO: float = 0.5


async def _throttle() -> None:
    """Garantiza que no se superen 2 capturas/segundo."""
    global _ULTIMA_CAPTURA
    async with _CAPTURE_LOCK:
        ahora = time.monotonic()
        espera = _INTERVALO_MINIMO - (ahora - _ULTIMA_CAPTURA)
        if espera > 0:
            await asyncio.sleep(espera)
        _ULTIMA_CAPTURA = time.monotonic()


# ── Escala retina ─────────────────────────────────────────────────────────────
def _factor_escala_pantalla() -> float:
    """Devuelve el backingScaleFactor de la pantalla principal (2.0 en M3 retina)."""
    try:
        from AppKit import NSScreen  # type: ignore[import-not-found]

        return float(NSScreen.mainScreen().backingScaleFactor())
    except Exception:
        return 2.0  # M3 siempre es retina; default conservador


def _normalizar_a_1x(png_bytes: bytes) -> bytes:
    """Reduce imagen retina a tamaño lógico (1x) para ahorrar tokens en Vision API."""
    escala = _factor_escala_pantalla()
    if escala <= 1.0:
        return png_bytes
    from PIL import Image  # type: ignore[import-not-found]

    with Image.open(io.BytesIO(png_bytes)) as img:
        nuevo = (int(img.width / escala), int(img.height / escala))
        buf = io.BytesIO()
        img.resize(nuevo, Image.LANCZOS).save(buf, "PNG")
        return buf.getvalue()


# ── Core subprocess ───────────────────────────────────────────────────────────
def _run_screencapture(*extra_args: str) -> bytes:
    """Ejecuta screencapture y devuelve bytes PNG desde stdout. Bloqueante."""
    cmd = ["screencapture", "-x", "-t", "png", *extra_args, "-"]
    resultado = subprocess.run(cmd, capture_output=True, check=True)
    return resultado.stdout


# ── API pública ───────────────────────────────────────────────────────────────
async def capture_screen() -> bytes:
    """Captura la pantalla principal a escala 1x. PNG en bytes, sin tocar disco.

    Ejemplo:
        >>> png = await capture_screen()
        >>> assert png[:4] == b'\\x89PNG'
    """
    await _throttle()
    raw = await asyncio.to_thread(_run_screencapture)
    return _normalizar_a_1x(raw)


async def capture_region(x: int, y: int, width: int, height: int) -> bytes:
    """Captura un rectángulo de la pantalla principal a escala 1x.

    Ejemplo:
        >>> png = await capture_region(0, 0, 1280, 800)
    """
    await _throttle()
    raw = await asyncio.to_thread(_run_screencapture, "-R", f"{x},{y},{width},{height}")
    return _normalizar_a_1x(raw)


async def capture_window(window_id: int) -> bytes:
    """Captura la ventana identificada por su CGWindowID a escala 1x.

    Ejemplo:
        >>> png = await capture_window(1234)
    """
    await _throttle()
    raw = await asyncio.to_thread(_run_screencapture, "-l", str(window_id))
    return _normalizar_a_1x(raw)


async def capture_to_file(path: Path, jpeg_quality: int | None = None) -> Path:
    """Captura la pantalla y la guarda en `path`.

    PNG por defecto. Si `jpeg_quality` (0-100) se especifica, guarda JPEG.
    Útil cuando el tamaño del archivo importa más que la calidad.

    Ejemplo:
        >>> p = await capture_to_file(Path("/tmp/snap.png"))
        >>> p.exists()
        True
    """
    await _throttle()
    fmt = "jpg" if jpeg_quality is not None else "png"
    cmd = ["screencapture", "-x", "-t", fmt]
    if jpeg_quality is not None:
        cmd += ["-q", str(max(0, min(100, jpeg_quality)))]
    cmd.append(str(path))
    await asyncio.to_thread(subprocess.run, cmd, check=True)
    return path


def encode_for_vision(image_bytes: bytes) -> str:
    """Codifica bytes de imagen en base64 para la Vision API de Kimi.

    Devuelve el string base64 listo para insertar en el campo `image_url`.

    Ejemplo:
        >>> b64 = encode_for_vision(b'\\x89PNG...')
        >>> isinstance(b64, str)
        True
    """
    return base64.b64encode(image_bytes).decode("ascii")
