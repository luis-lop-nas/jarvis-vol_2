"""Tests del sistema de skills de JARVIS.

Cubre: carga de directorio, validación de manifiestos, integración con
PermissionManager, herramientas válidas para el planner y callables adicionales.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from skills.registry import Skill, SkillManifest, SkillRegistry, ToolDecl
from security.permission_manager import RiskLevel

SKILLS_DIR = Path(__file__).parent.parent / "skills"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _manifest_minimo(nombre: str = "test") -> SkillManifest:
    return SkillManifest(
        nombre=nombre,
        descripcion=f"Skill de prueba '{nombre}'",
        herramientas=[
            ToolDecl(
                nombre=f"{nombre}.accion",
                descripcion="Acción de prueba",
                nivel_riesgo=RiskLevel.LOW,
            )
        ],
    )


@pytest.fixture
def registry() -> SkillRegistry:
    return SkillRegistry()


@pytest.fixture
def skill_simple() -> Skill:
    return Skill(
        manifest=_manifest_minimo("demo"),
        ruta=Path("/tmp/demo"),
        tools={"demo.accion": lambda: {"ok": True}},
    )


# ---------------------------------------------------------------------------
# Tests de ToolDecl
# ---------------------------------------------------------------------------


def test_tool_decl_to_policy_basico():
    decl = ToolDecl(
        nombre="foo.bar",
        descripcion="Hace algo",
        nivel_riesgo=RiskLevel.MEDIUM,
        requiere_confirmacion=True,
        puede_modificar_archivos=True,
    )
    policy = decl.to_policy()
    assert policy.nombre == "foo.bar"
    assert policy.nivel_riesgo == RiskLevel.MEDIUM
    assert policy.requiere_confirmacion is True
    assert policy.puede_modificar_archivos is True


def test_tool_decl_to_policy_permiso_desconocido(caplog):
    decl = ToolDecl(
        nombre="foo.bar",
        descripcion="Test",
        permisos_requeridos=["PERMISO_INVENTADO"],
    )
    policy = decl.to_policy()
    assert policy.permisos_requeridos == []
    assert "PERMISO_INVENTADO" in caplog.text


def test_tool_decl_to_policy_con_permiso_valido():
    decl = ToolDecl(
        nombre="foo.bar",
        descripcion="Test",
        permisos_requeridos=["SCREEN_RECORDING"],
    )
    policy = decl.to_policy()
    from security.permissions import Permission
    assert Permission.SCREEN_RECORDING in policy.permisos_requeridos


# ---------------------------------------------------------------------------
# Tests del SkillRegistry
# ---------------------------------------------------------------------------


def test_registry_vacio_inicial(registry):
    assert len(registry) == 0
    assert registry.herramientas_validas() == frozenset()
    assert registry.herramientas_confirmacion() == frozenset()
    assert registry.tools_adicionales() == {}
    assert registry.listar() == []


@pytest.mark.asyncio
async def test_cargar_directorio_real(registry):
    """Carga el directorio real de skills del proyecto."""
    await registry.cargar_directorio(SKILLS_DIR)
    assert len(registry) >= 5
    assert "browser" in registry
    assert "files" in registry
    assert "calendar" in registry
    assert "email" in registry
    assert "terminal" in registry


@pytest.mark.asyncio
async def test_herramientas_validas_incluye_todos_los_skills(registry):
    await registry.cargar_directorio(SKILLS_DIR)
    validas = registry.herramientas_validas()
    assert "browser.abrir" in validas
    assert "filesystem.leer" in validas
    assert "calendar.listar" in validas
    assert "mail.enviar" in validas
    assert "terminal.ejecutar" in validas


@pytest.mark.asyncio
async def test_herramientas_confirmacion(registry):
    await registry.cargar_directorio(SKILLS_DIR)
    confirmacion = registry.herramientas_confirmacion()
    assert "filesystem.eliminar" in confirmacion
    assert "browser.ejecutar_js" in confirmacion
    assert "mail.enviar" in confirmacion
    assert "terminal.ejecutar" in confirmacion
    assert "calendar.crear" in confirmacion
    assert "browser.abrir" not in confirmacion
    assert "filesystem.leer" not in confirmacion


@pytest.mark.asyncio
async def test_calendar_tools_adicionales(registry):
    await registry.cargar_directorio(SKILLS_DIR)
    tools = registry.tools_adicionales()
    assert "calendar.listar" in tools
    assert "calendar.crear" in tools
    assert "calendar.eliminar" in tools
    assert callable(tools["calendar.listar"])


@pytest.mark.asyncio
async def test_listar_devuelve_info_correcta(registry):
    await registry.cargar_directorio(SKILLS_DIR)
    info = registry.listar()
    nombres = {s["nombre"] for s in info}
    assert "browser" in nombres
    assert "calendar" in nombres

    browser_info = next(s for s in info if s["nombre"] == "browser")
    assert "browser.abrir" in browser_info["herramientas"]
    assert isinstance(browser_info["riesgos"], list)
    assert isinstance(browser_info["enabled"], bool)


# ---------------------------------------------------------------------------
# Tests de integración con PermissionManager
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_registrar_en_permission_manager(registry):
    await registry.cargar_directorio(SKILLS_DIR)

    pm_mock = MagicMock()
    pm_mock.registrar_politica = MagicMock()

    registry.registrar_en_permission_manager(pm_mock)

    nombres_registrados = {
        call.args[0].nombre
        for call in pm_mock.registrar_politica.call_args_list
    }
    assert "browser.abrir" in nombres_registrados
    assert "filesystem.eliminar" in nombres_registrados
    assert "calendar.listar" in nombres_registrados
    assert "terminal.ejecutar" in nombres_registrados


@pytest.mark.asyncio
async def test_politicas_registradas_coherentes(registry):
    await registry.cargar_directorio(SKILLS_DIR)

    from security.permission_manager import PermissionManager
    pm = PermissionManager()
    registry.registrar_en_permission_manager(pm)

    politica_eliminar = pm.politica("filesystem.eliminar")
    assert politica_eliminar is not None
    assert politica_eliminar.nivel_riesgo == RiskLevel.HIGH
    assert politica_eliminar.requiere_confirmacion is True

    politica_leer = pm.politica("filesystem.leer")
    assert politica_leer is not None
    assert politica_leer.nivel_riesgo == RiskLevel.LOW


# ---------------------------------------------------------------------------
# Tests de carga robusta (errores)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cargar_directorio_inexistente(registry):
    """No lanza excepción si el directorio no existe."""
    await registry.cargar_directorio(Path("/tmp/directorio_que_no_existe_xyz"))
    assert len(registry) == 0


@pytest.mark.asyncio
async def test_cargar_skill_sin_permissions_yaml(registry, tmp_path):
    """Carpetas sin permissions.yaml son ignoradas silenciosamente."""
    (tmp_path / "skill_roto").mkdir()
    await registry.cargar_directorio(tmp_path)
    assert len(registry) == 0


@pytest.mark.asyncio
async def test_cargar_skill_yaml_invalido(registry, tmp_path, caplog):
    """YAML inválido no rompe el registro completo."""
    skill_dir = tmp_path / "roto"
    skill_dir.mkdir()
    (skill_dir / "permissions.yaml").write_text("{ invalid: yaml: [")

    await registry.cargar_directorio(tmp_path)
    assert len(registry) == 0


@pytest.mark.asyncio
async def test_cargar_skill_enabled_false(registry, tmp_path):
    """Skills con enabled: false no aportan herramientas."""
    skill_dir = tmp_path / "desactivado"
    skill_dir.mkdir()
    (skill_dir / "permissions.yaml").write_text(yaml.dump({
        "nombre": "desactivado",
        "descripcion": "Test",
        "enabled": False,
        "herramientas": [{"nombre": "x.y", "descripcion": "test"}],
    }))

    await registry.cargar_directorio(tmp_path)
    assert "x.y" not in registry.herramientas_validas()


@pytest.mark.asyncio
async def test_cargar_skill_con_tools_py(registry, tmp_path):
    """Skills con tools.py válido exponen sus callables."""
    skill_dir = tmp_path / "miSkill"
    skill_dir.mkdir()
    (skill_dir / "permissions.yaml").write_text(yaml.dump({
        "nombre": "miSkill",
        "descripcion": "Skill con tools",
        "herramientas": [{"nombre": "miSkill.accion", "descripcion": "test"}],
    }))
    (skill_dir / "tools.py").write_text(
        "async def mi_funcion(): return {'ok': True}\n"
        "TOOLS = {'miSkill.accion': mi_funcion}\n"
    )

    await registry.cargar_directorio(tmp_path)
    assert "miSkill.accion" in registry.tools_adicionales()


@pytest.mark.asyncio
async def test_cargar_skill_tools_py_sin_tools_dict(registry, tmp_path, caplog):
    """tools.py sin TOOLS es aceptado, sin callables."""
    skill_dir = tmp_path / "sinTools"
    skill_dir.mkdir()
    (skill_dir / "permissions.yaml").write_text(yaml.dump({
        "nombre": "sinTools",
        "descripcion": "Sin TOOLS",
        "herramientas": [],
    }))
    (skill_dir / "tools.py").write_text("# sin TOOLS definido\n")

    await registry.cargar_directorio(tmp_path)
    assert registry.tools_adicionales() == {}


# ---------------------------------------------------------------------------
# Tests de integración con el planner
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_planner_acepta_herramientas_del_registry(registry):
    """El Planner valida tools de skills como herramientas conocidas."""
    await registry.cargar_directorio(SKILLS_DIR)

    from unittest.mock import MagicMock
    from core.planner import Planner, PlanEjecucion, PasoAccion

    modelo_mock = MagicMock()
    planner = Planner(modelo=modelo_mock, skill_registry=registry)

    plan = PlanEjecucion(
        tarea="Test",
        pasos=[
            PasoAccion(
                id="p1",
                descripcion="Lista eventos",
                herramienta="calendar.listar",
                parametros={"dias": 7},
            )
        ],
    )
    errores = planner.validate_plan(plan)
    assert not any("calendar.listar" in e for e in errores)


@pytest.mark.asyncio
async def test_planner_rechaza_herramienta_no_registrada():
    from unittest.mock import MagicMock
    from core.planner import Planner, PlanEjecucion, PasoAccion

    modelo_mock = MagicMock()
    planner = Planner(modelo=modelo_mock)

    plan = PlanEjecucion(
        tarea="Test",
        pasos=[
            PasoAccion(
                id="p1",
                descripcion="Herramienta inventada",
                herramienta="skill_falso.accion",
                parametros={},
            )
        ],
    )
    errores = planner.validate_plan(plan)
    assert any("skill_falso.accion" in e for e in errores)
