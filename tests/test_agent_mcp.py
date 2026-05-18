"""Flujo end-to-end del agente ejecutando herramientas vía MCPBus."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.agent import Agente
from core.mcp_bus import MCPBus
from core.planner import Planner
from core.reflector import DecisionReflexion, Reflector
from mcp_servers.server_filesystem import ServidorFilesystem
from models.base import ModelResponse


def _modelo_mock(plan_json: str) -> MagicMock:
    """Crea un modelo mock que devuelve un plan JSON."""
    modelo = MagicMock()
    modelo.complete = AsyncMock(return_value=ModelResponse(content=plan_json, model="mock"))
    return modelo


def _memoria_mock() -> MagicMock:
    """Crea MemorySystem mockeado para no tocar ChromaDB."""
    memoria = MagicMock()
    memoria.store_interaction = AsyncMock()
    memoria.get_context = AsyncMock(return_value="")
    memoria.find_workflow = AsyncMock(return_value=None)
    memoria.record_episode = AsyncMock(return_value="ep1")
    return memoria


@pytest.mark.asyncio
async def test_agent_executes_step_through_mcp(tmp_path: Path) -> None:
    """Agente planifica, llama al bus MCP, lee archivo y termina."""
    archivo = tmp_path / "README.md"
    archivo.write_text("contenido MCP", encoding="utf-8")
    plan_json = f"""
    {{
      "objetivo": "leer readme",
      "pasos": [{{
        "id": "p1",
        "descripcion": "Lee README",
        "herramienta": "filesystem.leer",
        "parametros": {{"ruta": "{archivo}"}},
        "requiere_confirmacion": false,
        "depende_de": [],
        "duracion_estimada_ms": 100,
        "puede_fallar": false
      }}]
    }}
    """
    modelo = _modelo_mock(plan_json)
    planner = Planner(modelo)
    reflector = Reflector(modelo)
    reflector.reflect = AsyncMock(return_value=DecisionReflexion.CONTINUAR)  # type: ignore[method-assign]
    reflector.evaluate_task_completion = MagicMock(side_effect=[False, True])  # type: ignore[method-assign]
    reflector.generate_summary = AsyncMock(return_value="Leído vía MCP.")  # type: ignore[method-assign]

    auditoria = MagicMock()
    auditoria.registrar = AsyncMock()
    bus = MCPBus([ServidorFilesystem(raiz=tmp_path)], audit_log=auditoria)
    agente = Agente(
        planner=planner,
        reflector=reflector,
        memoria_corto=MagicMock(),
        memoria_episodica=MagicMock(),
        auditoria=auditoria,
        memoria=_memoria_mock(),
        mcp_bus=bus,
    )

    actualizaciones = []
    async for update in agente.run("lee README"):
        actualizaciones.append(update)

    assert actualizaciones[-1].tipo == "listo"
    assert actualizaciones[-1].mensaje == "Leído vía MCP."
    assert any(u.resultado is None for u in actualizaciones if u.tipo == "actuando")
