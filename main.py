"""Punto de entrada de JARVIS.

Carga la configuración, inicializa logging con `rich`, monta el agente con
sus dependencias y arranca la API FastAPI sirviendo HTTP + WebSocket.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import signal
from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import WebSocket
from rich.console import Console
from rich.logging import RichHandler

from config import settings
from core.agent import Agente
from core.planner import Planner
from core.reflector import Reflector
from core.router import ContextoRuteo, DecisionRouter, Router
from interface.api import crear_app
from interface.websocket import GestorWebSocket
from memory.episodic import MemoriaEpisodica
from memory.short_term import MemoriaCortoPlazo
from models.base import Mensaje
from security.audit_log import AuditLog
from security.auth import AutenticadorLocal
from security.confirmation import GestorConfirmacion

console = Console()
log = logging.getLogger("jarvis")


def configurar_logging(nivel: str) -> None:
    """Inicializa el logger global con `RichHandler`."""
    logging.basicConfig(
        level=nivel,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True, markup=True)],
    )


@asynccontextmanager
async def construir_agente() -> AsyncIterator[tuple[Agente, AutenticadorLocal, GestorWebSocket]]:
    """Cablea todas las dependencias y las cierra al salir."""
    settings.asegurar_directorios()

    router = Router()
    modelo_planner = router.obtener_modelo(DecisionRouter.LOCAL)
    modelo_reflector = router.obtener_modelo(DecisionRouter.LOCAL)

    agente = Agente(
        router=router,
        planner=Planner(modelo_planner),
        reflector=Reflector(modelo_reflector),
        memoria_corto=MemoriaCortoPlazo(),
        memoria_episodica=MemoriaEpisodica(),
        confirmacion=GestorConfirmacion(),
        auditoria=AuditLog(),
    )

    autenticador = AutenticadorLocal(secreto_maestro=secrets.token_urlsafe(64))
    token_inicial = autenticador.crear_token()
    console.rule("[bold green]JARVIS iniciado")
    console.print(f"[yellow]Token de sesión:[/] [bold]{token_inicial}[/]")

    gestor_ws = GestorWebSocket(agente, autenticador)
    try:
        yield agente, autenticador, gestor_ws
    finally:
        await router.cerrar()


async def calentar(agente: Agente) -> None:
    """Pequeña llamada de calentamiento para detectar errores temprano."""
    contexto = ContextoRuteo(mensajes=[Mensaje(rol="system", contenido="ping")])
    decision = agente._router.decidir(contexto)  # noqa: SLF001
    log.info("Router operativo. Decisión inicial: %s", decision.value)


async def main() -> None:
    configurar_logging(settings.log_level)

    async with construir_agente() as (agente, autenticador, gestor_ws):
        app = crear_app(agente, autenticador)

        @app.websocket("/ws")
        async def _ws(websocket: WebSocket) -> None:
            await gestor_ws.manejar(websocket)

        await calentar(agente)

        config_uvicorn = uvicorn.Config(
            app,
            host="127.0.0.1",
            port=settings.api_port,
            log_level=settings.log_level.lower(),
            access_log=False,
        )
        servidor = uvicorn.Server(config_uvicorn)

        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(servidor.shutdown()))

        await servidor.serve()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        console.print("[yellow]Detenido por el usuario.[/]")
