"""Tests del skill browser."""

from pathlib import Path

import pytest
import yaml

SKILL_DIR = Path(__file__).parent.parent


def test_permissions_yaml_valido():
    data = yaml.safe_load((SKILL_DIR / "permissions.yaml").read_text())
    assert data["nombre"] == "browser"
    assert isinstance(data["herramientas"], list)
    assert len(data["herramientas"]) >= 1


def test_herramientas_declaradas():
    data = yaml.safe_load((SKILL_DIR / "permissions.yaml").read_text())
    nombres = {t["nombre"] for t in data["herramientas"]}
    esperadas = {"browser.abrir", "browser.leer", "browser.click",
                 "browser.fill", "browser.screenshot", "browser.ejecutar_js"}
    assert esperadas == nombres


def test_ejecutar_js_requiere_confirmacion():
    data = yaml.safe_load((SKILL_DIR / "permissions.yaml").read_text())
    js_tool = next(t for t in data["herramientas"] if t["nombre"] == "browser.ejecutar_js")
    assert js_tool["requiere_confirmacion"] is True
    assert js_tool["nivel_riesgo"] == "high"


def test_screenshot_requiere_screen_recording():
    data = yaml.safe_load((SKILL_DIR / "permissions.yaml").read_text())
    sc_tool = next(t for t in data["herramientas"] if t["nombre"] == "browser.screenshot")
    assert "SCREEN_RECORDING" in sc_tool.get("permisos_requeridos", [])


def test_examples_yaml_valido():
    data = yaml.safe_load((SKILL_DIR / "examples.yaml").read_text())
    assert isinstance(data, list)
    assert len(data) >= 1
    for ex in data:
        assert "herramienta" in ex
        assert "parametros" in ex


def test_tools_py_importable():
    from skills.browser.tools import TOOLS
    assert isinstance(TOOLS, dict)


def test_skill_md_existe():
    assert (SKILL_DIR / "SKILL.md").exists()
