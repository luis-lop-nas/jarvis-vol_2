"""Control programático de teclado y ratón con seguridad por rate-limit.

Usa Quartz CGEvent como primera opción (más fiable en M3).
Fallback a pyautogui si Quartz no está disponible.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Callable

log = logging.getLogger(__name__)

# Coordenada de esquina de emergencia (pyautogui.FAILSAFE la maneja en (0,0))
_ESQUINA_EMERGENCIA = (0, 0)
_MAX_ACCIONES_POR_SEGUNDO = 10
_MAX_SECUENCIA_SIN_CONFIRMACION = 20

CallbackConfirmacion = Callable[[str], "asyncio.Future[bool]"]


async def _aprobar_siempre(_: str) -> bool:
    return True


async def _denegar(_: str) -> bool:
    return False


# ---------------------------------------------------------------------------
# RatonTeclado
# ---------------------------------------------------------------------------


class RatonTeclado:
    """Control de input con rate limit y parada de emergencia.

    Ejemplo::
        rt = RatonTeclado()
        await rt.mover_a(500, 300)
        await rt.click(500, 300)
    """

    def __init__(
        self,
        *,
        callback_confirmacion: CallbackConfirmacion | None = None,
        audit_log: "AuditLog | None" = None,
    ) -> None:
        self._confirmar = callback_confirmacion or _denegar
        self._audit = audit_log
        self._lock_rate = asyncio.Lock()
        self._acciones_en_segundo: list[float] = []
        self._contador_secuencia: int = 0
        self._emergencia_activa: bool = False

        # Intentar Quartz; fallback pyautogui
        self._quartz_disponible = self._inicializar_quartz()
        if not self._quartz_disponible:
            self._inicializar_pyautogui()

    def _inicializar_quartz(self) -> bool:
        try:
            from Quartz import CGEventCreateMouseEvent, CGEventPost  # noqa: F401
            return True
        except ImportError:
            return False

    def _inicializar_pyautogui(self) -> None:
        try:
            import pyautogui
            pyautogui.PAUSE = 0.0
            pyautogui.FAILSAFE = True  # movimiento a (0,0) lanza FailSafeException
            self._pyag = pyautogui
        except ImportError:
            self._pyag = None  # type: ignore[assignment]

    # ------------------------------------------------------------------
    # Información de pantalla
    # ------------------------------------------------------------------

    async def tamaño_pantalla(self) -> tuple[int, int]:
        """Devuelve (ancho, alto) de la pantalla principal.

        Ejemplo::
            w, h = await rt.tamaño_pantalla()
        """
        if self._quartz_disponible:
            return await asyncio.to_thread(self._tamaño_quartz)
        try:
            import pyautogui
            sz = pyautogui.size()
            return (sz.width, sz.height)
        except Exception:
            return (1440, 900)

    def _tamaño_quartz(self) -> tuple[int, int]:
        try:
            from Quartz import CGDisplayBounds, CGMainDisplayID
            bounds = CGDisplayBounds(CGMainDisplayID())
            return (int(bounds.size.width), int(bounds.size.height))
        except Exception:
            return (1440, 900)

    async def factor_escala(self) -> float:
        """Devuelve el factor de escala retina (1.0 o 2.0).

        Ejemplo::
            escala = await rt.factor_escala()
        """
        try:
            import objc
            from AppKit import NSScreen
            screen = NSScreen.mainScreen()
            if screen is not None:
                return float(screen.backingScaleFactor())
        except Exception:
            pass
        return 2.0  # M3 es retina por defecto

    async def posicion(self) -> tuple[int, int]:
        """Devuelve la posición actual del cursor.

        Ejemplo::
            x, y = await rt.posicion()
        """
        if self._quartz_disponible:
            return await asyncio.to_thread(self._posicion_quartz)
        try:
            import pyautogui
            pos = pyautogui.position()
            return (pos.x, pos.y)
        except Exception:
            return (0, 0)

    def _posicion_quartz(self) -> tuple[int, int]:
        try:
            from Quartz import CGEventCreate, CGEventGetLocation, kCGEventNull
            evento = CGEventCreate(None)
            loc = CGEventGetLocation(evento)
            return (int(loc.x), int(loc.y))
        except Exception:
            return (0, 0)

    # ------------------------------------------------------------------
    # Ratón
    # ------------------------------------------------------------------

    async def mover_a(self, x: int, y: int, *, duracion: float = 0.2) -> bool:
        """Mueve el cursor a (x, y).

        Ejemplo::
            await rt.mover_a(500, 300)
        """
        if not await self._verificar_coordenadas(x, y):
            return False
        await self._limitar_tasa()
        if self._quartz_disponible:
            ok = await asyncio.to_thread(self._mover_quartz, x, y)
        else:
            try:
                await asyncio.to_thread(self._pyag.moveTo, x, y, duracion)
                ok = True
            except Exception:
                ok = False
        await self._audit_log("mover", {"x": x, "y": y})
        return ok

    def _mover_quartz(self, x: int, y: int) -> bool:
        try:
            from Quartz import (
                CGEventCreateMouseEvent,
                CGEventPost,
                kCGEventMouseMoved,
                kCGHIDEventTap,
                kCGMouseButtonLeft,
            )
            import CoreGraphics
            punto = CoreGraphics.CGPoint(x, y)
            evento = CGEventCreateMouseEvent(None, kCGEventMouseMoved, punto, kCGMouseButtonLeft)
            CGEventPost(kCGHIDEventTap, evento)
            return True
        except Exception as e:
            log.debug("Quartz mover falló: %s", e)
            return False

    async def click(self, x: int, y: int, *, boton: str = "left") -> bool:
        """Hace click en (x, y).

        Ejemplo::
            await rt.click(500, 300)
        """
        if not await self._verificar_coordenadas(x, y):
            return False
        await self._limitar_tasa()
        if self._quartz_disponible:
            ok = await asyncio.to_thread(self._click_quartz, x, y, boton)
        else:
            try:
                await asyncio.to_thread(self._pyag.click, x, y, button=boton)
                ok = True
            except Exception:
                ok = False
        await self._audit_log("click", {"x": x, "y": y, "boton": boton})
        return ok

    def _click_quartz(self, x: int, y: int, boton: str) -> bool:
        try:
            from Quartz import (
                CGEventCreateMouseEvent,
                CGEventPost,
                kCGEventLeftMouseDown,
                kCGEventLeftMouseUp,
                kCGEventRightMouseDown,
                kCGEventRightMouseUp,
                kCGHIDEventTap,
                kCGMouseButtonLeft,
                kCGMouseButtonRight,
            )
            import CoreGraphics
            punto = CoreGraphics.CGPoint(x, y)
            if boton == "right":
                tipo_down, tipo_up, btn = kCGEventRightMouseDown, kCGEventRightMouseUp, kCGMouseButtonRight
            else:
                tipo_down, tipo_up, btn = kCGEventLeftMouseDown, kCGEventLeftMouseUp, kCGMouseButtonLeft

            ev_down = CGEventCreateMouseEvent(None, tipo_down, punto, btn)
            ev_up = CGEventCreateMouseEvent(None, tipo_up, punto, btn)
            CGEventPost(kCGHIDEventTap, ev_down)
            CGEventPost(kCGHIDEventTap, ev_up)
            return True
        except Exception as e:
            log.debug("Quartz click falló: %s", e)
            return False

    async def doble_click(self, x: int, y: int) -> bool:
        """Doble-click en (x, y).

        Ejemplo::
            await rt.doble_click(300, 200)
        """
        await self.click(x, y)
        return await self.click(x, y)

    async def click_derecho(self, x: int, y: int) -> bool:
        """Click derecho en (x, y).

        Ejemplo::
            await rt.click_derecho(300, 200)
        """
        return await self.click(x, y, boton="right")

    async def arrastrar(
        self,
        origen: tuple[int, int],
        destino: tuple[int, int],
        *,
        duracion: float = 0.5,
    ) -> bool:
        """Arrastra desde origen hasta destino.

        Ejemplo::
            await rt.arrastrar((100, 200), (400, 200))
        """
        await self._limitar_tasa()
        try:
            await asyncio.to_thread(self._pyag.moveTo, *origen)
            await asyncio.to_thread(self._pyag.dragTo, destino[0], destino[1], duration=duracion)
            await self._audit_log("arrastrar", {"desde": origen, "hasta": destino})
            return True
        except Exception:
            return False

    async def scroll(self, x: int, y: int, cantidad: int, *, direccion: str = "down") -> bool:
        """Scroll en (x, y).

        Ejemplo::
            await rt.scroll(500, 400, 3, direccion="down")
        """
        await self._limitar_tasa()
        clicks = -cantidad if direccion == "down" else cantidad
        try:
            await asyncio.to_thread(self._pyag.scroll, clicks, x=x, y=y)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Teclado
    # ------------------------------------------------------------------

    async def escribir_texto(self, texto: str, *, intervalo: float = 0.02) -> bool:
        """Escribe texto carácter a carácter.

        Ejemplo::
            await rt.escribir_texto("hola mundo")
        """
        await self._limitar_tasa()
        try:
            await asyncio.to_thread(self._pyag.typewrite, texto, interval=intervalo)
            await self._audit_log("escribir_texto", {"longitud": len(texto)})
            return True
        except Exception:
            return False

    async def pulsar_tecla(self, tecla: str) -> bool:
        """Pulsa una tecla por nombre.

        Ejemplo::
            await rt.pulsar_tecla("enter")
        """
        await self._limitar_tasa()
        try:
            await asyncio.to_thread(self._pyag.press, tecla)
            return True
        except Exception:
            return False

    async def atajo(self, *teclas: str) -> bool:
        """Pulsa una combinación de teclas simultáneamente.

        Ejemplo::
            await rt.atajo("cmd", "c")  # copiar
            await rt.atajo("cmd", "shift", "4")  # screenshot
        """
        await self._limitar_tasa()
        try:
            await asyncio.to_thread(self._pyag.hotkey, *teclas)
            await self._audit_log("atajo", {"teclas": list(teclas)})
            return True
        except Exception:
            return False

    async def tecla_abajo(self, tecla: str) -> bool:
        """Mantiene una tecla pulsada.

        Ejemplo::
            await rt.tecla_abajo("shift")
        """
        try:
            await asyncio.to_thread(self._pyag.keyDown, tecla)
            return True
        except Exception:
            return False

    async def tecla_arriba(self, tecla: str) -> bool:
        """Suelta una tecla.

        Ejemplo::
            await rt.tecla_arriba("shift")
        """
        try:
            await asyncio.to_thread(self._pyag.keyUp, tecla)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Seguridad
    # ------------------------------------------------------------------

    async def ejecutar_secuencia(
        self,
        acciones: list[dict],
    ) -> bool:
        """Ejecuta una lista de acciones. Pide confirmación si supera el límite.

        Ejemplo::
            acciones = [{"tipo": "click", "x": 100, "y": 200}, ...]
            await rt.ejecutar_secuencia(acciones)
        """
        if len(acciones) > _MAX_SECUENCIA_SIN_CONFIRMACION:
            aprobado = await self._confirmar(
                f"Ejecutar secuencia de {len(acciones)} acciones de input"
            )
            if not aprobado:
                return False

        for accion in acciones:
            if self._emergencia_activa:
                return False
            tipo = accion.get("tipo", "")
            if tipo == "click":
                await self.click(accion["x"], accion["y"])
            elif tipo == "mover":
                await self.mover_a(accion["x"], accion["y"])
            elif tipo == "escribir":
                await self.escribir_texto(accion["texto"])
            elif tipo == "atajo":
                await self.atajo(*accion["teclas"])
        return True

    async def _verificar_coordenadas(self, x: int, y: int) -> bool:
        """Verifica que las coordenadas sean válidas y no activen la emergencia."""
        if (x, y) == _ESQUINA_EMERGENCIA:
            log.warning("Parada de emergencia: click en esquina (0,0)")
            self._emergencia_activa = True
            return False

        w, h = await self.tamaño_pantalla()
        if not (0 <= x <= w and 0 <= y <= h):
            log.warning("Coordenadas fuera de pantalla: (%d, %d)", x, y)
            return False

        return True

    async def _limitar_tasa(self) -> None:
        """Aplica el rate limit de 10 acciones/segundo."""
        ahora = time.monotonic()
        async with self._lock_rate:
            # Eliminar acciones de más de 1 segundo
            self._acciones_en_segundo = [t for t in self._acciones_en_segundo if ahora - t < 1.0]

            if len(self._acciones_en_segundo) >= _MAX_ACCIONES_POR_SEGUNDO:
                # Esperar hasta que haya hueco
                tiempo_espera = 1.0 - (ahora - self._acciones_en_segundo[0])
                if tiempo_espera > 0:
                    await asyncio.sleep(tiempo_espera)

            self._acciones_en_segundo.append(time.monotonic())

    async def _audit_log(self, evento: str, datos: dict) -> None:
        if self._audit is not None:
            await self._audit.registrar(f"input.{evento}", datos)


# Importación diferida
try:
    from security.audit_log import AuditLog  # noqa: F401
except ImportError:
    AuditLog = None  # type: ignore[assignment,misc]
