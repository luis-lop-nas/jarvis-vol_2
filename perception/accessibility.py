"""Accessibility API de macOS: información exacta de cualquier app sin visión.

Esta es la pieza más valiosa del módulo de percepción: da datos estructurados
(roles, valores, URLs, texto seleccionado) sin necesidad de OCR ni capturas.

IMPORTANTE: requiere permiso en Sistema → Privacidad → Accesibilidad.
Si no está concedido, todas las funciones devuelven None en lugar de lanzar.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any


# ── Modelos de datos ──────────────────────────────────────────────────────────
@dataclass(slots=True)
class AppInfo:
    """Información de una aplicación en ejecución."""

    bundle_id: str
    name: str
    pid: int

    def __str__(self) -> str:
        return f"{self.name} ({self.bundle_id}, pid={self.pid})"


@dataclass(slots=True)
class Bounds:
    """Rectángulo en coordenadas de pantalla (puntos, no píxeles físicos)."""

    x: float
    y: float
    width: float
    height: float

    def __str__(self) -> str:
        return f"({self.x:.0f}, {self.y:.0f}, {self.width:.0f}×{self.height:.0f})"


@dataclass(slots=True)
class WindowInfo:
    """Información de una ventana."""

    title: str | None
    bounds: Bounds | None
    is_fullscreen: bool

    def __str__(self) -> str:
        return f"'{self.title}' {self.bounds}"


@dataclass(slots=True)
class ElementInfo:
    """Elemento de la interfaz (botón, campo de texto, menú…)."""

    role: str
    value: str | None
    placeholder: str | None
    bounds: Bounds | None

    def __str__(self) -> str:
        return f"{self.role}: '{self.value}'"


@dataclass
class ElementTree:
    """Árbol de elementos AX con profundidad máxima configurable."""

    element: ElementInfo
    children: list[ElementTree] = field(default_factory=list)


# ── Permiso de accesibilidad ──────────────────────────────────────────────────
def verificar_permiso_accesibilidad() -> bool:
    """Comprueba si el proceso tiene permiso de accesibilidad sin mostrar diálogo."""
    try:
        from ApplicationServices import (  # type: ignore[import-not-found]
            AXIsProcessTrustedWithOptions,
        )

        return bool(AXIsProcessTrustedWithOptions({"AXTrustedCheckOptionPrompt": False}))
    except Exception:
        return False


def solicitar_permiso_accesibilidad() -> None:
    """Muestra el diálogo del sistema para conceder permiso de accesibilidad."""
    try:
        from ApplicationServices import (  # type: ignore[import-not-found]
            AXIsProcessTrustedWithOptions,
        )

        AXIsProcessTrustedWithOptions({"AXTrustedCheckOptionPrompt": True})
    except Exception:
        pass


# ── Helpers AX privados ───────────────────────────────────────────────────────
def _ax_attr(elemento: Any, nombre: str) -> Any:
    """Lee un atributo AX devolviendo None en cualquier error."""
    try:
        from ApplicationServices import (  # type: ignore[import-not-found]
            AXUIElementCopyAttributeValue,
        )

        err, valor = AXUIElementCopyAttributeValue(elemento, nombre, None)
        return valor if err == 0 else None
    except Exception:
        return None


def _ax_bounds(elemento: Any) -> Bounds | None:
    """Extrae posición y tamaño de un AXUIElement."""
    try:
        from ApplicationServices import (  # type: ignore[import-not-found]
            AXUIElementCopyAttributeValue,
        )

        _, pos = AXUIElementCopyAttributeValue(elemento, "AXPosition", None)
        _, sz = AXUIElementCopyAttributeValue(elemento, "AXSize", None)
        if pos is None or sz is None:
            return None
        p = pos.pointValue() if hasattr(pos, "pointValue") else None
        s = sz.sizeValue() if hasattr(sz, "sizeValue") else None
        if p is None or s is None:
            return None
        return Bounds(x=float(p.x), y=float(p.y), width=float(s.width), height=float(s.height))
    except Exception:
        return None


def _elemento_a_info(elemento: Any) -> ElementInfo:
    return ElementInfo(
        role=str(_ax_attr(elemento, "AXRole") or ""),
        value=_ax_attr(elemento, "AXValue"),
        placeholder=_ax_attr(elemento, "AXPlaceholderValue"),
        bounds=_ax_bounds(elemento),
    )


def _elemento_a_arbol(elemento: Any, profundidad: int = 0, max_prof: int = 8) -> ElementTree:
    arbol = ElementTree(element=_elemento_a_info(elemento))
    if profundidad < max_prof:
        hijos = _ax_attr(elemento, "AXChildren") or []
        for hijo in hijos:
            arbol.children.append(_elemento_a_arbol(hijo, profundidad + 1, max_prof))
    return arbol


# ── Funciones síncronas (se ejecutan en thread pool) ─────────────────────────
def _get_frontmost_app_sync() -> AppInfo | None:
    try:
        from AppKit import NSWorkspace  # type: ignore[import-not-found]

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        return AppInfo(
            bundle_id=str(app.bundleIdentifier() or ""),
            name=str(app.localizedName() or ""),
            pid=int(app.processIdentifier()),
        )
    except Exception:
        return None


def _get_active_window_sync(pid: int) -> WindowInfo | None:
    try:
        from ApplicationServices import (  # type: ignore[import-not-found]
            AXUIElementCopyAttributeValue,
            AXUIElementCreateApplication,
        )

        ax_app = AXUIElementCreateApplication(pid)
        _, window = AXUIElementCopyAttributeValue(ax_app, "AXFocusedWindow", None)
        if window is None:
            return None
        title = _ax_attr(window, "AXTitle")
        fullscreen = bool(_ax_attr(window, "AXFullScreen") or False)
        return WindowInfo(title=str(title) if title else None, bounds=_ax_bounds(window), is_fullscreen=fullscreen)
    except Exception:
        return None


def _get_focused_element_sync() -> ElementInfo | None:
    try:
        from ApplicationServices import (  # type: ignore[import-not-found]
            AXUIElementCopyAttributeValue,
            AXUIElementCreateSystemWide,
        )

        system = AXUIElementCreateSystemWide()
        _, elemento = AXUIElementCopyAttributeValue(system, "AXFocusedUIElement", None)
        if elemento is None:
            return None
        return _elemento_a_info(elemento)
    except Exception:
        return None


def _get_window_tree_sync(pid: int) -> ElementTree | None:
    try:
        from ApplicationServices import (  # type: ignore[import-not-found]
            AXUIElementCreateApplication,
        )

        return _elemento_a_arbol(AXUIElementCreateApplication(pid))
    except Exception:
        return None


def _get_browser_url_sync() -> str | None:
    """Obtiene la URL activa en Safari o Chrome via AX."""
    try:
        from AppKit import NSWorkspace  # type: ignore[import-not-found]
        from ApplicationServices import (  # type: ignore[import-not-found]
            AXUIElementCopyAttributeValue,
            AXUIElementCreateApplication,
        )

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        bundle = str(app.bundleIdentifier() or "").lower()
        navegadores = {"com.apple.safari", "com.google.chrome", "org.mozilla.firefox", "com.brave.browser"}
        if not any(nav in bundle for nav in navegadores):
            return None

        ax_app = AXUIElementCreateApplication(app.processIdentifier())
        _, windows = AXUIElementCopyAttributeValue(ax_app, "AXWindows", None)
        if not windows:
            return None

        window = windows[0]
        _, url = AXUIElementCopyAttributeValue(window, "AXURL", None)
        if url is not None:
            return str(url)

        # Fallback: buscar el AXTextField de la barra de dirección
        arbol = _elemento_a_arbol(window, max_prof=4)
        return _buscar_url_en_arbol(arbol)
    except Exception:
        return None


def _buscar_url_en_arbol(arbol: ElementTree) -> str | None:
    """Busca recursivamente un AXTextField que contenga una URL."""
    info = arbol.element
    if info.role in ("AXTextField", "AXComboBox") and info.value:
        val = str(info.value)
        if val.startswith(("http://", "https://", "file://")):
            return val
    for hijo in arbol.children:
        resultado = _buscar_url_en_arbol(hijo)
        if resultado:
            return resultado
    return None


def _get_browser_page_title_sync() -> str | None:
    try:
        from AppKit import NSWorkspace  # type: ignore[import-not-found]
        from ApplicationServices import (  # type: ignore[import-not-found]
            AXUIElementCopyAttributeValue,
            AXUIElementCreateApplication,
        )

        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        bundle = str(app.bundleIdentifier() or "").lower()
        if not any(nav in bundle for nav in ("safari", "chrome", "firefox", "brave")):
            return None

        ax_app = AXUIElementCreateApplication(app.processIdentifier())
        _, windows = AXUIElementCopyAttributeValue(ax_app, "AXWindows", None)
        if not windows:
            return None
        title = _ax_attr(windows[0], "AXTitle")
        return str(title) if title else None
    except Exception:
        return None


def _get_selected_text_sync() -> str | None:
    try:
        from ApplicationServices import (  # type: ignore[import-not-found]
            AXUIElementCopyAttributeValue,
            AXUIElementCreateSystemWide,
        )

        system = AXUIElementCreateSystemWide()
        _, elemento = AXUIElementCopyAttributeValue(system, "AXFocusedUIElement", None)
        if elemento is None:
            return None
        _, texto = AXUIElementCopyAttributeValue(elemento, "AXSelectedText", None)
        return str(texto) if texto else None
    except Exception:
        return None


def _is_app_running_sync(bundle_id: str) -> bool:
    try:
        from AppKit import NSWorkspace  # type: ignore[import-not-found]

        for app in NSWorkspace.sharedWorkspace().runningApplications():
            if str(app.bundleIdentifier() or "") == bundle_id:
                return True
        return False
    except Exception:
        return False


# ── API pública async ─────────────────────────────────────────────────────────
async def get_frontmost_app() -> AppInfo | None:
    """Devuelve la app en primer plano. None si no hay permiso de accesibilidad.

    Ejemplo:
        >>> app = await get_frontmost_app()
        >>> app.name if app else "sin permiso"
    """
    if not verificar_permiso_accesibilidad():
        return None
    return await asyncio.to_thread(_get_frontmost_app_sync)


async def get_active_window() -> WindowInfo | None:
    """Devuelve la ventana activa de la app en primer plano.

    Ejemplo:
        >>> win = await get_active_window()
        >>> win.title if win else None
    """
    if not verificar_permiso_accesibilidad():
        return None
    app = await asyncio.to_thread(_get_frontmost_app_sync)
    if app is None:
        return None
    return await asyncio.to_thread(_get_active_window_sync, app.pid)


async def get_focused_element() -> ElementInfo | None:
    """Devuelve el elemento con foco del sistema (campo de texto activo, botón, etc.).

    Ejemplo:
        >>> el = await get_focused_element()
        >>> el.role if el else None
    """
    if not verificar_permiso_accesibilidad():
        return None
    return await asyncio.to_thread(_get_focused_element_sync)


async def get_window_tree(pid: int) -> ElementTree | None:
    """Devuelve el árbol AX completo (hasta 8 niveles) de la app con PID dado.

    Ejemplo:
        >>> import os; tree = await get_window_tree(os.getpid())
    """
    if not verificar_permiso_accesibilidad():
        return None
    return await asyncio.to_thread(_get_window_tree_sync, pid)


async def get_browser_url() -> str | None:
    """Devuelve la URL activa en Safari, Chrome, Firefox o Brave. None en otras apps.

    Ejemplo:
        >>> url = await get_browser_url()
        >>> url  # "https://example.com" o None
    """
    if not verificar_permiso_accesibilidad():
        return None
    return await asyncio.to_thread(_get_browser_url_sync)


async def get_browser_page_title() -> str | None:
    """Devuelve el título de la página activa en el navegador en primer plano.

    Ejemplo:
        >>> titulo = await get_browser_page_title()
    """
    if not verificar_permiso_accesibilidad():
        return None
    return await asyncio.to_thread(_get_browser_page_title_sync)


async def get_selected_text() -> str | None:
    """Devuelve el texto seleccionado actualmente en cualquier app.

    Ejemplo:
        >>> texto = await get_selected_text()
    """
    if not verificar_permiso_accesibilidad():
        return None
    return await asyncio.to_thread(_get_selected_text_sync)


async def get_text_field_value(element: ElementInfo) -> str:
    """Devuelve el valor de texto de un ElementInfo (campo de texto, área, etc.).

    Ejemplo:
        >>> el = await get_focused_element()
        >>> valor = await get_text_field_value(el) if el else ""
    """
    return str(element.value or "")


async def is_app_running(bundle_id: str) -> bool:
    """Comprueba si una app está ejecutándose por su bundle ID.

    Ejemplo:
        >>> await is_app_running("com.apple.Safari")
        True
    """
    return await asyncio.to_thread(_is_app_running_sync, bundle_id)


async def wait_for_element(
    role: str,
    timeout: float = 5.0,
    interval: float = 0.2,
) -> ElementInfo | None:
    """Espera hasta que aparezca un elemento con el rol AX dado. None si timeout.

    Útil para esperar que cargue un diálogo o un campo específico.

    Ejemplo:
        >>> el = await wait_for_element("AXSheet", timeout=3.0)
    """
    limite = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < limite:
        elemento = await get_focused_element()
        if elemento and elemento.role == role:
            return elemento
        await asyncio.sleep(interval)
    return None
