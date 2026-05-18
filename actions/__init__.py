"""Efectores: cómo JARVIS actúa sobre el sistema.

Toda acción con efecto secundario (FS, shell, UI, red) pasa por este paquete.
Los módulos de `core/` nunca importan `actions/` directamente — lo hacen
a través de los MCP servers.
"""

from actions.browser import ControlSafari, Navegador
from actions.filesystem import SistemaArchivos
from actions.keyboard_mouse import RatonTeclado
from actions.system import ControlSistema
from actions.terminal import Terminal

__all__ = [
    "ControlSafari",
    "ControlSistema",
    "Navegador",
    "RatonTeclado",
    "SistemaArchivos",
    "Terminal",
]
