"""Tests del skill files."""

from pathlib import Path

import pytest
import yaml

SKILL_DIR = Path(__file__).parent.parent


def test_permissions_yaml_valido():
    data = yaml.safe_load((SKILL_DIR / "permissions.yaml").read_text())
    assert data["nombre"] == "files"
    assert isinstance(data["herramientas"], list)


def test_herramientas_declaradas():
    data = yaml.safe_load((SKILL_DIR / "permissions.yaml").read_text())
    nombres = {t["nombre"] for t in data["herramientas"]}
    esperadas = {
        "filesystem.leer", "filesystem.listar", "filesystem.buscar",
        "filesystem.escribir", "filesystem.mover",
        "filesystem.copiar", "filesystem.eliminar",
    }
    assert esperadas == nombres


def test_eliminar_es_high_y_confirmacion():
    data = yaml.safe_load((SKILL_DIR / "permissions.yaml").read_text())
    eliminar = next(t for t in data["herramientas"] if t["nombre"] == "filesystem.eliminar")
    assert eliminar["nivel_riesgo"] == "high"
    assert eliminar["requiere_confirmacion"] is True
    assert eliminar["puede_modificar_archivos"] is True


def test_leer_es_low():
    data = yaml.safe_load((SKILL_DIR / "permissions.yaml").read_text())
    leer = next(t for t in data["herramientas"] if t["nombre"] == "filesystem.leer")
    assert leer["nivel_riesgo"] == "low"
    assert leer.get("requiere_confirmacion", False) is False


def test_tools_py_importable():
    from skills.files.tools import TOOLS
    assert isinstance(TOOLS, dict)


def test_skill_md_existe():
    assert (SKILL_DIR / "SKILL.md").exists()
