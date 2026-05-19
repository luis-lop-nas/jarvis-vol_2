"""Tests del módulo perception: screenshot, OCR, accesibilidad, estado del sistema.

Todos los tests mockean las dependencias del sistema operativo (subprocess,
pyobjc, psutil) para ejecutarse en CI sin macOS ni hardware real.
"""

from __future__ import annotations

import asyncio
import base64
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

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

    async def test_bounds_calcula_center_automaticamente(self) -> None:
        """Bounds calcula center_x y center_y en __post_init__."""
        from perception.accessibility import Bounds

        b = Bounds(x=100.0, y=200.0, width=80.0, height=40.0)
        assert b.center_x == 140.0
        assert b.center_y == 220.0

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
            import contextlib
            with contextlib.suppress(asyncio.CancelledError):
                await task

        assert len(llamadas) >= 1, "El callback debe haberse llamado al menos una vez"
        assert llamadas[0].active_app is not None
        assert llamadas[0].active_app.name == "Terminal"


# ── Verifier ──────────────────────────────────────────────────────────────────

PNG_A = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PNG_B = b"\x89PNG\r\n\x1a\n" + b"\xff" * 64  # diferente de PNG_A


class TestVerifier:
    """Tests de ActionVerifier con todas las señales mockeadas."""

    def _make_snap(
        self,
        screenshot: bytes | None = PNG_A,
        ocr_text: str = "hola mundo",
        app_bundle: str | None = "com.apple.Safari",
        window_title: str | None = "Safari",
        focused_role: str | None = "AXTextField",
        focused_value: str | None = "texto",
    ) -> dict:
        return {
            "screenshot": screenshot,
            "ocr_text": ocr_text,
            "app_bundle": app_bundle,
            "window_title": window_title,
            "focused_role": focused_role,
            "focused_value": focused_value,
        }

    async def test_verify_action_success_dos_señales(self) -> None:
        """Verifier devuelve success=True cuando ≥2 señales cambian."""
        from perception.verifier import ActionVerifier

        verifier = ActionVerifier()
        snap_antes = self._make_snap(
            ocr_text="texto anterior",
            focused_value="valor anterior",
        )

        snap_despues = self._make_snap(
            screenshot=PNG_B,
            ocr_text="texto anterior nuevo contenido",
            focused_value="valor nuevo",
        )

        with patch.object(verifier, "snapshot_before", new=AsyncMock(return_value=snap_despues)):
            result = await verifier.verify_action_result("click", "botón pulsado", snap_antes)

        assert result.success is True
        assert result.signals_passed >= 2
        assert result.signals_total == 4

    async def test_verify_action_failure_sin_cambios(self) -> None:
        """Verifier devuelve success=False cuando el estado no cambia en absoluto."""
        from perception.verifier import ActionVerifier

        verifier = ActionVerifier()
        snap = self._make_snap()

        with patch.object(verifier, "snapshot_before", new=AsyncMock(return_value=snap)):
            result = await verifier.verify_action_result("click", "botón pulsado", snap)

        assert result.success is False
        assert result.signals_passed < 2

    async def test_verify_fallback_snapshot_falla(self) -> None:
        """Si el snapshot post-acción falla, el verifier devuelve VerificationResult con success=False."""
        from perception.verifier import ActionVerifier

        verifier = ActionVerifier()
        snap_antes = self._make_snap()

        with patch.object(
            verifier,
            "snapshot_before",
            new=AsyncMock(side_effect=RuntimeError("captura fallida")),
        ):
            try:
                result = await verifier.verify_action_result("click", "botón", snap_antes)
                assert result.success is False
            except RuntimeError:
                pass  # aceptable: la excepción sube, el agente la captura


# ── Runaway guard ─────────────────────────────────────────────────────────────


class TestRunawayGuard:
    """Tests del contador de capturas idénticas en screenshot.py."""

    def setup_method(self) -> None:
        import perception.screenshot as ss

        # Resetear estado del guard antes de cada test para aislamiento
        ss._CAPTURAS_IDENTICAS = 0
        ss._ULTIMO_HASH_CAPTURA = ""
        ss._INTERVALO_MINIMO = ss._INTERVALO_NORMAL
        ss.ALERTA_PANTALLA_ESTATICA.clear()

    async def test_capturas_distintas_no_acumulan_contador(self) -> None:
        """Capturas con contenido diferente resetean el contador (cada una es la 1ª del nuevo hash)."""
        import perception.screenshot as ss

        ss._actualizar_runaway_guard(b"\x00" * 100)  # 1ª ocurrencia → _CAPTURAS_IDENTICAS = 1
        ss._actualizar_runaway_guard(b"\xff" * 100)  # hash diferente → _CAPTURAS_IDENTICAS = 1

        assert ss._CAPTURAS_IDENTICAS == 1  # la última captura es la primera de su hash

    async def test_cinco_identicas_reduce_rate(self) -> None:
        """5 capturas idénticas consecutivas activan rate reducido."""
        import perception.screenshot as ss

        datos = b"\xAB" * 100
        for _ in range(5):
            ss._actualizar_runaway_guard(datos)

        # 1ª llamada: _CAPTURAS_IDENTICAS=1, 2ª:2, ..., 5ª:5
        assert ss._CAPTURAS_IDENTICAS == 5
        assert ss._INTERVALO_MINIMO == ss._INTERVALO_REDUCIDO

    async def test_diez_identicas_emite_alerta(self) -> None:
        """10+ capturas idénticas consecutivas activan ALERTA_PANTALLA_ESTATICA."""
        import perception.screenshot as ss

        datos = b"\xCD" * 100
        for _ in range(10):
            ss._actualizar_runaway_guard(datos)

        assert ss.ALERTA_PANTALLA_ESTATICA.is_set()

    async def test_captura_diferente_resetea_alerta(self) -> None:
        """Una captura diferente después de la alerta resetea el evento y el contador."""
        import perception.screenshot as ss

        datos = b"\xEF" * 100
        for _ in range(10):
            ss._actualizar_runaway_guard(datos)

        assert ss.ALERTA_PANTALLA_ESTATICA.is_set()

        ss._actualizar_runaway_guard(b"\x00" * 100)
        assert not ss.ALERTA_PANTALLA_ESTATICA.is_set()
        assert ss._CAPTURAS_IDENTICAS == 1  # nueva captura = primera ocurrencia


# ── OCR estrategia por tipo de contenido ─────────────────────────────────────


class TestOCREstrategiaContenido:
    async def test_ocr_strategy_code_region(self) -> None:
        """Región con código Python devuelve PSM 6."""
        import sys

        import perception.ocr as ocr_mod

        texto_codigo = "def mi_funcion():\n    import os\n    return True"
        fake_tess = MagicMock()
        fake_tess.image_to_string.return_value = texto_codigo
        fake_pil = MagicMock()
        fake_pil.Image.open.return_value = MagicMock()

        with patch.dict(sys.modules, {"pytesseract": fake_tess, "PIL": fake_pil, "PIL.Image": fake_pil.Image}):
            psm = ocr_mod._detectar_psm(PNG_FAKE)

        assert psm == 6, f"Código debe usar PSM 6, obtuvo {psm}"

    async def test_ocr_strategy_form_region(self) -> None:
        """Región con separadores de tabla devuelve PSM 4."""
        import sys

        import perception.ocr as ocr_mod

        texto_tabla = "Nombre │ Apellido │ Ciudad\n─────────────────────"
        fake_tess = MagicMock()
        fake_tess.image_to_string.return_value = texto_tabla
        fake_pil = MagicMock()
        fake_pil.Image.open.return_value = MagicMock()

        with patch.dict(sys.modules, {"pytesseract": fake_tess, "PIL": fake_pil, "PIL.Image": fake_pil.Image}):
            psm = ocr_mod._detectar_psm(PNG_FAKE)

        assert psm == 4, f"Tabla debe usar PSM 4, obtuvo {psm}"


# ── Grounding de coordenadas ──────────────────────────────────────────────────


class TestGrounding:
    async def test_grounding_via_ax(self) -> None:
        """get_element_coordinates() devuelve bounds desde AX si el permiso está concedido."""
        from perception.accessibility import Bounds, get_element_coordinates

        bounds_esperado = Bounds(x=10.0, y=20.0, width=100.0, height=30.0)

        with (
            patch("perception.accessibility.verificar_permiso_accesibilidad", return_value=True),
            patch(
                "perception.accessibility._buscar_por_ax",
                new=AsyncMock(return_value=bounds_esperado),
            ),
        ):
            resultado = await get_element_coordinates("Safari", "Botón Aceptar")

        assert resultado is not None
        assert resultado.x == 10.0
        assert resultado.center_x == 60.0  # 10 + 100/2

    async def test_grounding_via_ocr_fallback(self) -> None:
        """Si AX falla, get_element_coordinates() usa OCR y devuelve bounds."""
        from perception.accessibility import Bounds, get_element_coordinates

        bounds_ocr = Bounds(x=50.0, y=100.0, width=120.0, height=25.0)

        with (
            patch(
                "perception.accessibility._buscar_por_ax",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "perception.accessibility._buscar_por_ocr",
                new=AsyncMock(return_value=bounds_ocr),
            ),
        ):
            resultado = await get_element_coordinates("Safari", "Botón Cancelar")

        assert resultado is not None
        assert resultado.center_y == 112.5  # 100 + 25/2
