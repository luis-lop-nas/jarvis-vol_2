"""Efectores: cómo JARVIS actúa sobre el sistema."""

from actions.browser import Navegador
from actions.filesystem import SistemaArchivos
from actions.keyboard_mouse import RatonTeclado
from actions.system import ControlSistema
from actions.terminal import Terminal

__all__ = [
    "ControlSistema",
    "Navegador",
    "RatonTeclado",
    "SistemaArchivos",
    "Terminal",
]
