"""Tests del módulo perception: screenshot, OCR, accesibilidad, estado del sistema.

Todos los tests mockean las dependencias del sistema operativo (subprocess,
pyobjc, psutil) para ejecutarse en CI sin macOS ni hardware real.
"""

from __future__ import annotations

import asyncio
import base64
import time
from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Screenshot ────────────────────────────────────────────────────────────────
PNG_FAKE = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64  # cabecera PNG válida


class TestScreenshot:
    async def test_capture_screen_devuelve_png(self) -> None:
        """capture_screen() con subprocess mockeado devuelve bytes con cabecera PNG."""
        with (
            patch("perception.screenshot._run_screencapture", return_value=PNG_FAKE),
            patch("perception.screenshot._normalizar_a_1x", return_value=PNG_FAKE),
            patch("perception.screenshot._throttle", new=AsyncMock()),
        ):
            from perception.screenshot import capture_screen

            resultado = await capture_screen()

        assert resultado[:4] == b"\x89PNG", "La respuesta debe empezar con la cabecera PNG"

    async def test_encode_for_vision_es_base64_valido(self) -> None:
        """encode_for_vision() devuelve un string base64 que decodifica exactamente los bytes originales."""
        from perception.screenshot import encode_for_vision

        datos = b"\x89PNG\r\n\x1a\n\xde\xad\xbe\xef"
        b64 = encode_for_vision(datos)

        assert isinstance(b64, str)
        assert base64.b64decode(b64) == datos


# ── OCR ───────────────────────────────────────────────────────────────────────
class TestOCR:
    async def test_ocr_cache_segunda_llamada_no_llama_tesseract(
        self, mocker: Any
    ) -> None:
        """La misma imagen procesada dos veces en <30 s devuelve el resultado cacheado sin rellamar a Tesseract."""
        import perception.ocr as ocr_mod

        # Limpiamos la caché antes del test para garantizar aislamiento
        ocr_mod._CACHE.clear()

        mock_tess = mocker.patch(
            "perception.ocr._tesseract_texto_sync", return_value="Hola mundo"
        )

        texto1 = await ocr_mod.extract_text_local(PNG_FAKE)
        texto2 = await ocr_mod.extract_text_local(PNG_FAKE)

        assert texto1 == texto2 == "Hola mundo"
        assert mock_tess.call_count == 1, "Tesseract debe llamarse solo una vez; la segunda es de caché"

        ocr_mod._CACHE.clear()  # limpieza post-test


# ── Accesibilidad ─────────────────────────────────────────────────────────────
class TestAccesibilidad:
    async def test_sin_permiso_get_frontmost_app_devuelve_none(self) -> None:
        """Sin permiso de accesibilidad, get_frontmost_app() devuelve None sin lanzar excepción."""
        with patch("perception.accessibility.verificar_permiso_accesibilidad", return_value=False):
            from perception.accessibility import get_frontmost_app

            resultado = await get_frontmost_app()

        assert resultado is None

    async def test_con_permiso_get_frontmost_app_devuelve_app_info(self) -> None:
        """Con permiso concedido, get_frontmost_app() devuelve el AppInfo que construye _get_frontmost_app_sync."""
        from perception.accessibility import AppInfo, get_frontmost_app

        expected = AppInfo(bundle_id="com.apple.Safari", name="Safari", pid=999)

        with (
            patch("perception.accessibility.verificar_permiso_accesibilidad", return_value=True),
            patch("perception.accessibility._get_frontmost_app_sync", return_value=expected),
        ):
            resultado = await get_frontmost_app()

        assert isinstance(resultado, AppInfo)
        assert resultado.bundle_id == "com.apple.Safari"
        assert resultado.name == "Safari"
        assert resultado.pid == 999


# ── Estado del sistema ────────────────────────────────────────────────────────
class TestSystemState:
    def _make_estado(self, app_name: str, bundle_id: str = "com.test.App") -> Any:
        from perception.accessibility import AppInfo, WindowInfo
        from perception.system_state import SystemState

        return SystemState(
            active_app=AppInfo(bundle_id=bundle_id, name=app_name, pid=1),
            active_window=WindowInfo(title="main.py", bounds=None, is_fullscreen=False),
            cpu_percent=10.0,
            ram_used_gb=3.8,
            ram_available_gb=4.2,
            battery_percent=80,
            is_charging=True,
            wifi_connected=True,
            wifi_ssid="CasaRed",
            screen_locked=False,
            do_not_disturb=False,
            current_space=1,
            running_apps=[bundle_id],
        )

    async def test_context_summary_contiene_app_y_ram(self) -> None:
        """context_summary() incluye el nombre de la app activa y la RAM disponible."""
        estado = self._make_estado("VS Code")
        resumen = estado.context_summary()

        assert "VS Code" in resumen
        assert "4.2" in resumen  # RAM disponible
        assert "WiFi" in resumen

    async def test_watch_state_llama_callback_al_cambiar_app(self) -> None:
        """watch_state() llama al callback cuando la app activa cambia entre polls."""
        import perception.system_state as ss_mod

        estado_inicial = self._make_estado("Safari", "com.apple.Safari")
        estado_cambiado = self._make_estado("Terminal", "com.apple.Terminal")

        llamadas: list[Any] = []

        # Proveer suficientes estados para cubrir todos los polls del loop (interval=0.01, sleep=0.08 → ~8 iters)
        estados = [estado_inicial, estado_cambiado] + [estado_cambiado] * 20

        with patch(
            "perception.system_state.get_system_state",
            new=AsyncMock(side_effect=estados),
        ):
            task = await ss_mod.watch_state(lambda e: llamadas.append(e), interval=0.01)
            await asyncio.sleep(0.08)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert len(llamadas) >= 1, "El callback debe haberse llamado al menos una vez"
        assert llamadas[0].active_app is not None
        assert llamadas[0].active_app.name == "Terminal"
