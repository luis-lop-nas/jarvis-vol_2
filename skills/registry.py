"""Registro de skills de JARVIS.

Cada skill es una carpeta con:
- permissions.yaml   → manifiesto declarativo (herramientas, permisos, riesgos)
- SKILL.md           → documentación legible
- examples.yaml      → ejemplos de uso
- tools.py           → callables Python (opcional; para tools nuevas sin MCP server)
- tests/             → tests del skill

Ejemplo::
    registry = SkillRegistry()
    await registry.cargar_directorio(Path("skills/"))
    registry.registrar_en_permission_manager(permission_manager)
    tools = registry.tools_adicionales()   # callables para el agente
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml
from pydantic import BaseModel, Field

from security.permission_manager import RiskLevel, ToolPolicy
from security.permissions import Permission

log = logging.getLogger(__name__)

RUTA_SKILLS = Path(__file__).parent


# ---------------------------------------------------------------------------
# Modelos declarativos
# ---------------------------------------------------------------------------


class ToolDecl(BaseModel):
    """Declaración de una herramienta dentro de un skill (leída desde permissions.yaml)."""

    nombre: str
    descripcion: str
    nivel_riesgo: RiskLevel = RiskLevel.LOW
    requiere_confirmacion: bool = False
    requiere_biometria: bool = False
    puede_modificar_archivos: bool = False
    puede_usar_red: bool = False
    puede_leer_pantalla: bool = False
    puede_acceder_credenciales: bool = False
    permisos_requeridos: list[str] = Field(default_factory=list)
    parametros: dict[str, Any] = Field(default_factory=dict)

    def to_policy(self) -> ToolPolicy:
        """Convierte esta declaración en un ToolPolicy para el PermissionManager."""
        permisos: list[Permission] = []
        for nombre_permiso in self.permisos_requeridos:
            try:
                permisos.append(Permission[nombre_permiso])
            except KeyError:
                log.warning("Permiso desconocido en skill '%s': %s", self.nombre, nombre_permiso)
        return ToolPolicy(
            nombre=self.nombre,
            nivel_riesgo=self.nivel_riesgo,
            requiere_confirmacion=self.requiere_confirmacion,
            requiere_biometria=self.requiere_biometria,
            puede_modificar_archivos=self.puede_modificar_archivos,
            puede_usar_red=self.puede_usar_red,
            puede_leer_pantalla=self.puede_leer_pantalla,
            puede_acceder_credenciales=self.puede_acceder_credenciales,
            permisos_requeridos=permisos,
            descripcion=self.descripcion,
        )


class SkillManifest(BaseModel):
    """Manifiesto completo de un skill (leído desde permissions.yaml).

    Ejemplo::
        manifest = SkillManifest(
            nombre="browser",
            descripcion="Control del navegador Safari",
            herramientas=[ToolDecl(nombre="browser.abrir", ...)],
        )
    """

    nombre: str
    descripcion: str
    version: str = "1.0.0"
    autor: str = ""
    herramientas: list[ToolDecl] = Field(default_factory=list)
    riesgos: list[str] = Field(default_factory=list)
    enabled: bool = True


@dataclass
class Skill:
    """Skill cargado: manifiesto + ruta + examples + callables opcionales."""

    manifest: SkillManifest
    ruta: Path
    examples: list[dict[str, Any]] = field(default_factory=list)
    tools: dict[str, Callable[..., Any]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Registro principal
# ---------------------------------------------------------------------------


class SkillRegistry:
    """Carga, valida y expone todos los skills disponibles.

    Ejemplo::
        registry = SkillRegistry()
        await registry.cargar_directorio()
        print(registry.listar())
    """

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    # ── Carga ──────────────────────────────────────────────────────────────

    async def cargar_directorio(self, directorio: Path = RUTA_SKILLS) -> None:
        """Descubre y carga todos los skills en el directorio dado."""
        if not directorio.is_dir():
            log.warning("Directorio de skills no existe: %s", directorio)
            return

        for carpeta in sorted(directorio.iterdir()):
            if carpeta.is_dir() and not carpeta.name.startswith(("_", ".")):
                await self._cargar_skill(carpeta)

        log.info("Skills cargados: %d (%s)", len(self._skills), ", ".join(self._skills))

    async def _cargar_skill(self, carpeta: Path) -> None:
        perms_path = carpeta / "permissions.yaml"
        if not perms_path.exists():
            return

        try:
            data = yaml.safe_load(perms_path.read_text(encoding="utf-8"))
            manifest = SkillManifest.model_validate(data)
        except Exception:
            log.exception("Error parseando permissions.yaml en %s", carpeta)
            return

        examples: list[dict[str, Any]] = []
        examples_path = carpeta / "examples.yaml"
        if examples_path.exists():
            try:
                loaded = yaml.safe_load(examples_path.read_text(encoding="utf-8"))
                examples = loaded if isinstance(loaded, list) else []
            except Exception:
                log.warning("Error parseando examples.yaml en %s", carpeta)

        tools: dict[str, Callable[..., Any]] = {}
        tools_path = carpeta / "tools.py"
        if tools_path.exists():
            tools = self._importar_tools(tools_path, manifest.nombre)

        skill = Skill(manifest=manifest, ruta=carpeta, examples=examples, tools=tools)
        self._skills[manifest.nombre] = skill
        log.debug(
            "Skill '%s' v%s cargado — %d herramientas, %d callables",
            manifest.nombre, manifest.version, len(manifest.herramientas), len(tools),
        )

    def _importar_tools(self, ruta: Path, nombre_skill: str) -> dict[str, Callable[..., Any]]:
        """Importa tools.py de un skill y extrae el dict TOOLS."""
        try:
            spec = importlib.util.spec_from_file_location(
                f"skills.{nombre_skill}.tools", ruta
            )
            if spec is None or spec.loader is None:
                return {}
            modulo = importlib.util.module_from_spec(spec)
            sys.modules[f"skills.{nombre_skill}.tools"] = modulo
            spec.loader.exec_module(modulo)  # type: ignore[attr-defined]
            tools = getattr(modulo, "TOOLS", {})
            if not isinstance(tools, dict):
                log.warning("tools.py de '%s' tiene TOOLS con tipo incorrecto", nombre_skill)
                return {}
            return dict(tools)
        except Exception:
            log.exception("Error importando tools.py del skill '%s'", nombre_skill)
            return {}

    # ── Integración con el resto del sistema ──────────────────────────────

    def registrar_en_permission_manager(self, pm: Any) -> None:
        """Registra las políticas de todos los skills en el PermissionManager.

        Las políticas del skill sobrescriben las defaults del PermissionManager
        si declaran la misma herramienta.

        Ejemplo::
            registry.registrar_en_permission_manager(permission_manager)
        """
        for skill in self._skills.values():
            if not skill.manifest.enabled:
                continue
            for tool_decl in skill.manifest.herramientas:
                pm.registrar_politica(tool_decl.to_policy())

    def herramientas_validas(self) -> frozenset[str]:
        """Conjunto de nombres de herramientas de todos los skills activos."""
        nombres: set[str] = set()
        for skill in self._skills.values():
            if skill.manifest.enabled:
                for tool in skill.manifest.herramientas:
                    nombres.add(tool.nombre)
        return frozenset(nombres)

    def herramientas_confirmacion(self) -> frozenset[str]:
        """Herramientas de skills activos que requieren confirmación del usuario."""
        nombres: set[str] = set()
        for skill in self._skills.values():
            if skill.manifest.enabled:
                for tool in skill.manifest.herramientas:
                    if tool.requiere_confirmacion:
                        nombres.add(tool.nombre)
        return frozenset(nombres)

    def tools_adicionales(self) -> dict[str, Callable[..., Any]]:
        """Callables de todos los skills activos (para inyectar en el agente).

        Ejemplo::
            agente = Agente(..., herramientas=registry.tools_adicionales())
        """
        resultado: dict[str, Callable[..., Any]] = {}
        for skill in self._skills.values():
            if skill.manifest.enabled:
                resultado.update(skill.tools)
        return resultado

    # ── Consulta ──────────────────────────────────────────────────────────

    def listar(self) -> list[dict[str, Any]]:
        """Devuelve la información de todos los skills para el endpoint GET /skills.

        Ejemplo::
            skills = registry.listar()
        """
        return [
            {
                "nombre": s.manifest.nombre,
                "descripcion": s.manifest.descripcion,
                "version": s.manifest.version,
                "autor": s.manifest.autor,
                "enabled": s.manifest.enabled,
                "herramientas": [t.nombre for t in s.manifest.herramientas],
                "riesgos": s.manifest.riesgos,
                "ejemplos": len(s.examples),
            }
            for s in self._skills.values()
        ]

    def get(self, nombre: str) -> Skill | None:
        """Devuelve un skill por nombre, o None si no existe."""
        return self._skills.get(nombre)

    def __len__(self) -> int:
        return len(self._skills)

    def __contains__(self, nombre: str) -> bool:
        return nombre in self._skills
