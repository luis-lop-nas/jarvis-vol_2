"""Punto de entrada de JARVIS — arranque completo del sistema.

Secuencia:
1. Logging con rich
2. Verificar permisos macOS (Accessibility, Screen Recording)
3. Verificar Ollama y ChromaDB en paralelo
4. Inicializar MemorySystem + MCPBus + modelos + Agente
5. Arrancar FastAPI + WebSocket en puerto 8765 con uvicorn
"""

from __future__ import annotations

import asyncio
import logging
import signal
import subprocess
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
import psutil
import uvicorn
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table

from config import settings
from core.agent import Agente
from core.mcp_bus import MCPBus
from core.planner import Planner
from core.reflector import Reflector
from interface.api import crear_servidor
from interface.websocket import ConnectionManager
from memory import MemorySystem
from memory.episodic import MemoriaEpisodica
from memory.short_term import MemoriaCortoPlazo
from mcp_servers import crear_bus_mcp
from models.ollama_client import OllamaModel
from security.audit_log import AuditLog

console = Console()
log = logging.getLogger("jarvis")


def configurar_logging(nivel: str) -> None:
    logging.basicConfig(
        level=nivel,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True, markup=True)],
    )


# ---------------------------------------------------------------------------
# Checks de arranque
# ---------------------------------------------------------------------------


def _check_permisos_macos() -> dict[str, bool]:
    permisos: dict[str, bool] = {}
    try:
        from perception.accessibility import verificar_permiso_accesibilidad
        permisos["accessibility"] = verificar_permiso_accesibilidad()
    except Exception:
        permisos["accessibility"] = False
    try:
        res = subprocess.run(
            ["screencapture", "-x", "-t", "png", "/dev/null"],
            capture_output=True,
            timeout=3,
        )
        permisos["screen_recording"] = res.returncode == 0
    except Exception:
        permisos["screen_recording"] = False
    return permisos


async def _verificar_ollama() -> bool:
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{settings.ollama_base_url}/api/tags")
            return r.status_code == 200
    except Exception:
        return False


async def _verificar_chroma() -> bool:
    url = f"http://{settings.chroma_host}:{settings.chroma_port}/api/v1/heartbeat"
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(url)
            return r.status_code == 200
    except Exception:
        return False


def _log_estado_arranque(
    permisos: dict[str, bool],
    ollama_ok: bool,
    chroma_ok: bool,
) -> None:
    t = Table(show_header=False, box=None, padding=(0, 2))
    t.add_column("Componente", style="bold")
    t.add_column("Estado")

    def _s(ok: bool) -> str:
        return "[green]OK[/]" if ok else "[yellow]no disponible[/]"

    t.add_row("Ollama", _s(ollama_ok))
    t.add_row("ChromaDB", _s(chroma_ok))
    t.add_row("Accessibility", _s(permisos.get("accessibility", False)))
    t.add_row("Screen Recording", _s(permisos.get("screen_recording", False)))
    t.add_row("RAM libre", f"{psutil.virtual_memory().available / (1024**3):.1f} GB")

    if not ollama_ok:
        console.print("[yellow]Ollama no corre → ejecuta: ollama serve[/]")
    if not chroma_ok:
        console.print("[yellow]ChromaDB no disponible → ejecuta: docker-compose up -d[/]")

    console.print(Panel(t, title="[bold cyan]JARVIS — estado de arranque[/]", expand=False))


# ---------------------------------------------------------------------------
# Stack principal
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _construir_stack() -> AsyncIterator[tuple[Agente, ConnectionManager]]:
    settings.asegurar_directorios()

    permisos, ollama_ok, chroma_ok = await asyncio.gather(
        asyncio.to_thread(_check_permisos_macos),
        _verificar_ollama(),
        _verificar_chroma(),
    )
    _log_estado_arranque(permisos, ollama_ok, chroma_ok)

    memoria = MemorySystem()
    mcp_bus: MCPBus = crear_bus_mcp()
    modelo = OllamaModel()

    agente = Agente(
        planner=Planner(modelo),
        reflector=Reflector(modelo),
        memoria_corto=MemoriaCortoPlazo(),
        memoria_episodica=MemoriaEpisodica(),
        auditoria=AuditLog(),
        memoria=memoria,
        mcp_bus=mcp_bus,
    )
    manager = ConnectionManager()

    try:
        yield agente, manager
    finally:
        log.info("Cerrando JARVIS…")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    configurar_logging(settings.log_level)

    async with _construir_stack() as (agente, manager):
        app = crear_servidor(agente, manager)

        config = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=settings.api_port,
            log_level=settings.log_level.lower(),
            access_log=False,
        )
        servidor = uvicorn.Server(config)

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(
                sig, lambda: asyncio.create_task(servidor.shutdown())
            )

        console.print(
            f"\n[bold green]JARVIS listo en "
            f"http://127.0.0.1:{settings.api_port}[/]\n"
        )
        await servidor.serve()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("[yellow]Detenido.[/]")
