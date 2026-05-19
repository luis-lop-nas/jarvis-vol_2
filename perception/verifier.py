"""Verificación post-acción: 4 señales independientes para detectar si la acción tuvo efecto.

Patrón clawdcursor. Compara estado antes/después mediante pixel_diff, ocr_delta,
window_state y accessibility_change. Umbral: ≥2 señales positivas → acción verificada.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class VerificationResult:
    """Resultado de la verificación post-acción.

    Ejemplo::
        r = VerificationResult(success=True, signals_passed=3, signals_total=4,
                               details={"pixel_diff": True, "ocr_delta": False,
                                        "window_state": True, "accessibility_change": True})
    """

    success: bool
    signals_passed: int
    signals_total: int
    details: dict[str, bool] = field(default_factory=dict)


class ActionVerifier:
    """Verifica que una acción tuvo efecto real comparando estado antes/después.

    Usa 4 señales independientes:
    - pixel_diff: diff de píxeles entre capturas.
    - ocr_delta: palabras nuevas detectadas por OCR.
    - window_state: cambio de app activa o título de ventana.
    - accessibility_change: cambio de elemento focalizado vía AXUIElement.

    Umbral: ≥2 señales positivas → success=True.

    Ejemplo::
        verifier = ActionVerifier()
        snap = await verifier.snapshot_before()
        # ejecutar acción…
        result = await verifier.verify_action_result("click", "botón pulsado", snap)
        if not result.success and result.signals_passed < 2:
            # reintentar
    """

    def __init__(self, pixel_diff_threshold: float = 0.01) -> None:
        self._pixel_diff_threshold = pixel_diff_threshold

    async def snapshot_before(self) -> dict[str, Any]:
        """Captura estado del sistema justo antes de ejecutar una acción.

        Ejemplo::
            snap = await verifier.snapshot_before()
        """
        snap: dict[str, Any] = {
            "screenshot": None,
            "ocr_text": "",
            "app_bundle": None,
            "window_title": None,
            "focused_role": None,
            "focused_value": None,
        }

        resultados = await asyncio.gather(
            self._capturar_pantalla(),
            self._capturar_ax(),
            return_exceptions=True,
        )

        pantalla = resultados[0] if not isinstance(resultados[0], BaseException) else None
        ax = resultados[1] if not isinstance(resultados[1], BaseException) else {}

        if pantalla is not None:
            snap["screenshot"] = pantalla
            try:
                from perception.ocr import extract_text_local

                snap["ocr_text"] = await extract_text_local(pantalla)
            except Exception as exc:
                log.debug("OCR en snapshot falló: %s", exc)

        snap.update(ax)
        return snap

    async def _capturar_pantalla(self) -> bytes | None:
        try:
            from perception.screenshot import capture_screen

            return await capture_screen()
        except Exception:
            return None

    async def _capturar_ax(self) -> dict[str, Any]:
        try:
            from perception.accessibility import (
                get_active_window,
                get_focused_element,
                get_frontmost_app,
            )

            app, win, el = await asyncio.gather(
                get_frontmost_app(),
                get_active_window(),
                get_focused_element(),
            )
            return {
                "app_bundle": app.bundle_id if app else None,
                "window_title": win.title if win else None,
                "focused_role": el.role if el else None,
                "focused_value": str(el.value or "") if el else None,
            }
        except Exception:
            return {}

    async def verify_action_result(
        self,
        action_type: str,
        expected_outcome: str,
        before: dict[str, Any],
    ) -> VerificationResult:
        """Compara estado actual con el snapshot previo usando 4 señales.

        Ejemplo::
            result = await verifier.verify_action_result("click", "formulario enviado", snap)
        """
        after = await self.snapshot_before()
        details: dict[str, bool] = {
            "pixel_diff": self._check_pixel_diff(
                before.get("screenshot"), after.get("screenshot")
            ),
            "ocr_delta": self._check_ocr_delta(
                before.get("ocr_text", ""), after.get("ocr_text", "")
            ),
            "window_state": self._check_window_state(
                before.get("app_bundle"),
                before.get("window_title"),
                after.get("app_bundle"),
                after.get("window_title"),
            ),
            "accessibility_change": self._check_accessibility(
                before.get("focused_role"),
                before.get("focused_value"),
                after.get("focused_role"),
                after.get("focused_value"),
            ),
        }
        signals_passed = sum(1 for v in details.values() if v)
        success = signals_passed >= 2
        log.debug(
            "Verificación %s (%s): %d/%d señales — %s",
            action_type,
            expected_outcome,
            signals_passed,
            len(details),
            details,
        )
        return VerificationResult(
            success=success,
            signals_passed=signals_passed,
            signals_total=len(details),
            details=details,
        )

    # ── Señales ──────────────────────────────────────────────────────────────

    def _check_pixel_diff(self, before: bytes | None, after: bytes | None) -> bool:
        """True si la fracción de píxeles distintos supera el umbral."""
        if before is None and after is None:
            return False
        if before is None or after is None:
            return True  # uno existe y el otro no → cambio definitivo
        if before == after:
            return False  # bytes idénticos → sin cambio
        try:
            import io

            from PIL import Image, ImageChops  # type: ignore[import-not-found]

            img_b = Image.open(io.BytesIO(before)).convert("RGB")
            img_a = Image.open(io.BytesIO(after)).convert("RGB")
            if img_b.size != img_a.size:
                return True
            diff = ImageChops.difference(img_b, img_a)
            pixeles_total = img_b.width * img_b.height
            if pixeles_total == 0:
                return False
            cambiados = sum(1 for p in diff.getdata() if any(c > 5 for c in p))
            return (cambiados / pixeles_total) > self._pixel_diff_threshold
        except Exception as exc:
            log.debug("pixel_diff falló: %s", exc)
            return False

    def _check_ocr_delta(self, before_text: str, after_text: str) -> bool:
        """True si hay palabras en el texto posterior que no estaban antes."""
        palabras_antes = set(before_text.split())
        palabras_despues = set(after_text.split())
        return bool(palabras_despues - palabras_antes)

    def _check_window_state(
        self,
        app_before: str | None,
        title_before: str | None,
        app_after: str | None,
        title_after: str | None,
    ) -> bool:
        """True si cambió la app activa o el título de ventana."""
        return app_before != app_after or title_before != title_after

    def _check_accessibility(
        self,
        role_before: str | None,
        value_before: str | None,
        role_after: str | None,
        value_after: str | None,
    ) -> bool:
        """True si cambió el elemento focalizado (rol o valor)."""
        return role_before != role_after or value_before != value_after
