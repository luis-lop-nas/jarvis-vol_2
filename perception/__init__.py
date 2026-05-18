"""Sensores: cómo JARVIS percibe el sistema (pantalla, OCR, accesibilidad, estado)."""

from perception.accessibility import (
    AppInfo,
    Bounds,
    ElementInfo,
    ElementTree,
    WindowInfo,
    get_active_window,
    get_browser_page_title,
    get_browser_url,
    get_focused_element,
    get_frontmost_app,
    get_selected_text,
    get_window_tree,
    is_app_running,
    wait_for_element,
)
from perception.ocr import extract_structured, extract_text, extract_text_local, extract_text_vision
from perception.screenshot import (
    capture_region,
    capture_screen,
    capture_to_file,
    capture_window,
    encode_for_vision,
)
from perception.system_state import (
    SystemState,
    context_summary,
    get_system_state,
    is_busy,
    watch_state,
)

__all__ = [
    # screenshot
    "capture_screen",
    "capture_region",
    "capture_window",
    "capture_to_file",
    "encode_for_vision",
    # ocr
    "extract_text",
    "extract_text_local",
    "extract_text_vision",
    "extract_structured",
    # accessibility
    "AppInfo",
    "Bounds",
    "WindowInfo",
    "ElementInfo",
    "ElementTree",
    "get_frontmost_app",
    "get_active_window",
    "get_focused_element",
    "get_window_tree",
    "get_browser_url",
    "get_browser_page_title",
    "get_selected_text",
    "is_app_running",
    "wait_for_element",
    # system_state
    "SystemState",
    "get_system_state",
    "watch_state",
    "is_busy",
    "context_summary",
]
