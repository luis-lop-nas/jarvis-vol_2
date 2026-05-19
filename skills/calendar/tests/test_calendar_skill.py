"""Tests del skill calendar."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml

SKILL_DIR = Path(__file__).parent.parent


def test_permissions_yaml_valido():
    data = yaml.safe_load((SKILL_DIR / "permissions.yaml").read_text())
    assert data["nombre"] == "calendar"
    assert isinstance(data["herramientas"], list)


def test_herramientas_declaradas():
    data = yaml.safe_load((SKILL_DIR / "permissions.yaml").read_text())
    nombres = {t["nombre"] for t in data["herramientas"]}
    assert nombres == {"calendar.listar", "calendar.crear", "calendar.eliminar"}


def test_crear_requiere_confirmacion():
    data = yaml.safe_load((SKILL_DIR / "permissions.yaml").read_text())
    crear = next(t for t in data["herramientas"] if t["nombre"] == "calendar.crear")
    assert crear["requiere_confirmacion"] is True


def test_eliminar_es_high():
    data = yaml.safe_load((SKILL_DIR / "permissions.yaml").read_text())
    elim = next(t for t in data["herramientas"] if t["nombre"] == "calendar.eliminar")
    assert elim["nivel_riesgo"] == "high"
    assert elim["requiere_confirmacion"] is True


def test_tools_importables():
    from skills.calendar.tools import TOOLS
    assert "calendar.listar" in TOOLS
    assert "calendar.crear" in TOOLS
    assert "calendar.eliminar" in TOOLS


@pytest.mark.asyncio
async def test_listar_sin_macos():
    """En sistemas no-macOS, listar devuelve error en lugar de fallar."""
    from skills.calendar.tools import calendar_listar
    with patch("skills.calendar.tools._IS_MACOS", False):
        resultado = await calendar_listar(dias=7)
    assert "error" in resultado
    assert resultado["eventos"] == []


@pytest.mark.asyncio
async def test_listar_osascript_ok():
    salida_mock = "uid1|Reunión|2026-05-20 10:00|2026-05-20 11:00|Trabajo"
    proc_mock = AsyncMock()
    proc_mock.returncode = 0
    proc_mock.communicate = AsyncMock(return_value=(salida_mock.encode(), b""))

    with patch("skills.calendar.tools._IS_MACOS", True), \
         patch("asyncio.create_subprocess_exec", return_value=proc_mock):
        resultado = await __import__(
            "skills.calendar.tools", fromlist=["calendar_listar"]
        ).calendar_listar(dias=7)

    assert resultado["total"] == 1
    assert resultado["eventos"][0]["titulo"] == "Reunión"


@pytest.mark.asyncio
async def test_crear_osascript_ok():
    proc_mock = AsyncMock()
    proc_mock.returncode = 0
    proc_mock.communicate = AsyncMock(return_value=(b"nuevo-uid-123", b""))

    with patch("skills.calendar.tools._IS_MACOS", True), \
         patch("asyncio.create_subprocess_exec", return_value=proc_mock):
        from skills.calendar.tools import calendar_crear
        resultado = await calendar_crear(
            titulo="Test", fecha="2026-05-20",
            hora_inicio="10:00", hora_fin="11:00",
        )

    assert resultado["creado"] is True
    assert resultado["evento_id"] == "nuevo-uid-123"


@pytest.mark.asyncio
async def test_eliminar_no_encontrado():
    proc_mock = AsyncMock()
    proc_mock.returncode = 0
    proc_mock.communicate = AsyncMock(return_value=(b"no_encontrado", b""))

    with patch("skills.calendar.tools._IS_MACOS", True), \
         patch("asyncio.create_subprocess_exec", return_value=proc_mock):
        from skills.calendar.tools import calendar_eliminar
        resultado = await calendar_eliminar(evento_id="xyz")

    assert resultado["eliminado"] is False
