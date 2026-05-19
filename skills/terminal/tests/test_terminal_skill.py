"""Tests del skill terminal."""

from pathlib import Path

import yaml

SKILL_DIR = Path(__file__).parent.parent


def test_permissions_yaml_valido():
    data = yaml.safe_load((SKILL_DIR / "permissions.yaml").read_text())
    assert data["nombre"] == "terminal"
    assert isinstance(data["herramientas"], list)


def test_herramientas_declaradas():
    data = yaml.safe_load((SKILL_DIR / "permissions.yaml").read_text())
    nombres = {t["nombre"] for t in data["herramientas"]}
    assert nombres == {"terminal.ejecutar", "terminal.python", "terminal.transmitir"}


def test_todas_high_y_confirmacion():
    data = yaml.safe_load((SKILL_DIR / "permissions.yaml").read_text())
    for tool in data["herramientas"]:
        assert tool["nivel_riesgo"] == "high", f"{tool['nombre']} debería ser high"
        assert tool["requiere_confirmacion"] is True


def test_tools_py_importable():
    from skills.terminal.tools import TOOLS
    assert isinstance(TOOLS, dict)
