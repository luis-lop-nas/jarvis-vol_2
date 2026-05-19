"""Extracción de texto de imágenes con dos estrategias: Tesseract local y Kimi Vision API.

Estrategia automática:
- Imagen > 500 KB → Tesseract primero (evita subir datos grandes); si confianza < 60 → Vision.
- Imagen ≤ 500 KB → Vision API directamente (más precisa para layouts complejos).
- Caché por hash SHA-256 con TTL de 30 s para evitar reprocesar la misma captura.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import time
from typing import Any

# ── Constantes ────────────────────────────────────────────────────────────────
_TTL_CACHE_S: float = 30.0
_LIMITE_LOCAL_BYTES: int = 500 * 1024  # 500 KB

# El umbral de confianza se lee de settings en runtime para que sea configurable.
# Fallback a 60.0 (escala 0-100) si settings no está disponible.
def _umbral_confianza() -> float:
    try:
        from config.settings import settings
        return settings.ocr_confidence_threshold * 100.0
    except Exception:
        return 60.0

# ── Caché ─────────────────────────────────────────────────────────────────────
_CACHE: dict[str, tuple[str, float]] = {}


def _clave(image_bytes: bytes) -> str:
    return hashlib.sha256(image_bytes).hexdigest()


def _get_cache(image_bytes: bytes) -> str | None:
    clave = _clave(image_bytes)
    entrada = _CACHE.get(clave)
    if entrada is not None and (time.monotonic() - entrada[1]) < _TTL_CACHE_S:
        return entrada[0]
    _CACHE.pop(clave, None)
    return None


def _set_cache(image_bytes: bytes, texto: str) -> None:
    _CACHE[_clave(image_bytes)] = (texto, time.monotonic())


# ── Detección de tipo de contenido ───────────────────────────────────────────
_INDICADORES_CODIGO = frozenset({
    "def ", "class ", "import ", "return ", "if ", "for ", "while ",
    "{}","};", "=>", "fn ", "func ", "var ", "let ", "const ",
    "//", "/*", "#include", "public ", "private ",
})
_INDICADORES_TABLA = frozenset({
    "\t\t", "│", "┌", "└", "┐", "┘", "─", "|  ", "  |",
})


def _detectar_psm(image_bytes: bytes) -> int:
    """Detecta el tipo de contenido de la región y devuelve el PSM de Tesseract adecuado.

    - Código (def, class, import…): PSM 6 (bloque uniforme de texto).
    - Formulario/tabla (caracteres de tabla, columnas separadas): PSM 4.
    - Texto corrido: PSM 3 (default automático de Tesseract).

    Ejemplo::
        psm = _detectar_psm(png_bytes)
    """
    try:
        import pytesseract  # type: ignore[import-not-found]
        from PIL import Image  # type: ignore[import-not-found]

        muestra = pytesseract.image_to_string(
            Image.open(io.BytesIO(image_bytes)), lang="spa+eng", config="--psm 3"
        )
        if any(ind in muestra for ind in _INDICADORES_CODIGO):
            return 6
        if any(ind in muestra for ind in _INDICADORES_TABLA):
            return 4
        return 3
    except Exception:
        return 3


# ── Tesseract ─────────────────────────────────────────────────────────────────
def _tesseract_texto_sync(image_bytes: bytes) -> str:
    import pytesseract  # type: ignore[import-not-found]
    from PIL import Image  # type: ignore[import-not-found]

    return pytesseract.image_to_string(Image.open(io.BytesIO(image_bytes)), lang="spa+eng")


def _tesseract_con_psm_sync(image_bytes: bytes, psm: int) -> str:
    """Ejecuta Tesseract con el PSM indicado para el tipo de contenido detectado.

    Ejemplo::
        texto = _tesseract_con_psm_sync(png_bytes, psm=6)  # región de código
    """
    import pytesseract  # type: ignore[import-not-found]
    from PIL import Image  # type: ignore[import-not-found]

    return pytesseract.image_to_string(
        Image.open(io.BytesIO(image_bytes)),
        lang="spa+eng",
        config=f"--psm {psm}",
    )


def _tesseract_confianza_sync(image_bytes: bytes) -> float:
    """Media de confianza por palabra (0-100). Devuelve -1.0 si Tesseract falla."""
    try:
        import pytesseract  # type: ignore[import-not-found]
        from PIL import Image  # type: ignore[import-not-found]

        datos = pytesseract.image_to_data(
            Image.open(io.BytesIO(image_bytes)),
            output_type=pytesseract.Output.DICT,
        )
        confianzas = [float(c) for c in datos["conf"] if isinstance(c, (int, float)) and c >= 0]
        return sum(confianzas) / len(confianzas) if confianzas else -1.0
    except Exception:
        return -1.0


# ── Kimi Vision ───────────────────────────────────────────────────────────────
async def _kimi_vision_sync(image_bytes: bytes) -> str:
    """Llama a Kimi Vision API para extraer texto de una imagen."""
    import base64

    import httpx

    from config.settings import settings

    api_key = settings.kimi_api_key.get_secret_value()
    if not api_key:
        raise RuntimeError("KIMI_API_KEY no configurado; no se puede usar OCR por visión")

    b64 = base64.b64encode(image_bytes).decode("ascii")
    payload: dict[str, Any] = {
        "model": settings.kimi_model_default,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    },
                    {
                        "type": "text",
                        "text": (
                            "Extrae todo el texto visible en esta imagen."
                            " Devuelve únicamente el texto, sin explicaciones ni formato extra."
                        ),
                    },
                ],
            }
        ],
        "max_tokens": 2048,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{settings.kimi_base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
        resp.raise_for_status()
        return str(resp.json()["choices"][0]["message"]["content"])


# ── API pública ───────────────────────────────────────────────────────────────
async def extract_text_local(image_bytes: bytes) -> str:
    """Extrae texto con Tesseract. Siempre local; nunca envía datos a la nube.

    Ejemplo:
        >>> texto = await extract_text_local(png_bytes)
        >>> isinstance(texto, str)
        True
    """
    cached = _get_cache(image_bytes)
    if cached is not None:
        return cached
    texto = await asyncio.to_thread(_tesseract_texto_sync, image_bytes)
    _set_cache(image_bytes, texto)
    return texto


async def extract_text_vision(image_bytes: bytes) -> str:
    """Extrae texto usando Kimi Vision API. Más preciso en layouts y código.

    Requiere KIMI_API_KEY configurado. Para datos privados usa extract_text_local().

    Ejemplo:
        >>> texto = await extract_text_vision(png_bytes)
    """
    cached = _get_cache(image_bytes)
    if cached is not None:
        return cached
    texto = await _kimi_vision_sync(image_bytes)
    _set_cache(image_bytes, texto)
    return texto


async def extract_text(image_bytes: bytes) -> str:
    """Extrae texto eligiendo la estrategia automáticamente según tamaño y tipo de contenido.

    - Imagen > 500 KB: detecta tipo de región → Tesseract con PSM adaptativo;
      si confianza < ocr_confidence_threshold → Vision API.
    - Imagen ≤ 500 KB: Vision API directamente (más precisa en layouts complejos).

    Ejemplo:
        >>> texto = await extract_text(png_bytes)
    """
    cached = _get_cache(image_bytes)
    if cached is not None:
        return cached

    if len(image_bytes) > _LIMITE_LOCAL_BYTES:
        confianza = await asyncio.to_thread(_tesseract_confianza_sync, image_bytes)
        if confianza >= _umbral_confianza():
            psm = await asyncio.to_thread(_detectar_psm, image_bytes)
            if psm != 3:
                # Contenido especializado: usar PSM adaptativo
                texto = await asyncio.to_thread(_tesseract_con_psm_sync, image_bytes, psm)
                _set_cache(image_bytes, texto)
                return texto
            return await extract_text_local(image_bytes)

    return await extract_text_vision(image_bytes)


async def extract_structured(image_bytes: bytes) -> dict[str, Any]:
    """Extrae información estructurada: tipo de contenido, bloques de texto, idioma, confianza.

    Devuelve:
        content_type: "code" | "text" | "ui" | "unknown"
        text_blocks: lista de {text: str, confidence: float}
        language: str
        confidence: float (0.0-1.0)

    Ejemplo:
        >>> info = await extract_structured(png_bytes)
        >>> info["content_type"] in ("code", "text", "ui", "unknown")
        True
    """
    try:
        import pytesseract  # type: ignore[import-not-found]
        from PIL import Image  # type: ignore[import-not-found]

        datos = await asyncio.to_thread(
            pytesseract.image_to_data,
            Image.open(io.BytesIO(image_bytes)),
            output_type=pytesseract.Output.DICT,
        )

        bloques: list[dict[str, Any]] = []
        confianzas: list[float] = []
        for i, texto in enumerate(datos["text"]):
            if not str(texto).strip():
                continue
            conf = float(datos["conf"][i])
            if conf < 0:
                continue
            bloques.append({"text": str(texto), "confidence": conf / 100.0})
            confianzas.append(conf)

        confianza_media = sum(confianzas) / len(confianzas) / 100.0 if confianzas else 0.0
        texto_plano = " ".join(b["text"] for b in bloques)

        return {
            "content_type": _inferir_tipo(texto_plano),
            "text_blocks": bloques,
            "language": "spa+eng",
            "confidence": confianza_media,
        }
    except Exception:
        return {"content_type": "unknown", "text_blocks": [], "language": "unknown", "confidence": 0.0}


# ── Helpers privados ──────────────────────────────────────────────────────────
_INDICADORES_CODIGO = {"def ", "class ", "import ", "return ", "if ", "for ", "while ", "{", "};", "=>"}


def _inferir_tipo(texto: str) -> str:
    if any(ind in texto for ind in _INDICADORES_CODIGO):
        return "code"
    if len(texto.split()) > 20:
        return "text"
    return "ui"
