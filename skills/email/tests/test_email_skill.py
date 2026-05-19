"""Tests del skill email."""

from pathlib import Path

import yaml

SKILL_DIR = Path(__file__).parent.parent


def test_permissions_yaml_valido():
    data = yaml.safe_load((SKILL_DIR / "permissions.yaml").read_text())
    assert data["nombre"] == "email"
    assert isinstance(data["herramientas"], list)


def test_herramientas_declaradas():
    data = yaml.safe_load((SKILL_DIR / "permissions.yaml").read_text())
    nombres = {t["nombre"] for t in data["herramientas"]}
    assert nombres == {"mail.leer", "mail.enviar", "mail.eliminar"}


def test_enviar_requiere_confirmacion():
    data = yaml.safe_load((SKILL_DIR / "permissions.yaml").read_text())
    enviar = next(t for t in data["herramientas"] if t["nombre"] == "mail.enviar")
    assert enviar["requiere_confirmacion"] is True
    assert enviar["nivel_riesgo"] == "high"


def test_automation_permiso_requerido():
    data = yaml.safe_load((SKILL_DIR / "permissions.yaml").read_text())
    for tool in data["herramientas"]:
        assert "AUTOMATION" in tool.get("permisos_requeridos", [])


def test_tools_py_importable():
    from skills.email.tools import TOOLS
    assert isinstance(TOOLS, dict)
