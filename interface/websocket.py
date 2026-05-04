"""Servidor WebSocket para diálogo bidireccional con la UI/overlay."""

from __future__ import annotations

import logging
from typing import Any

import orjson
from fastapi import WebSocket, WebSocketDisconnect

from core.agent import Agente
from security.auth import AutenticadorLocal

log = logging.getLogger(__name__)


class GestorWebSocket:
    """Mantiene una sesión WebSocket viva con un cliente autenticado."""

    def __init__(self, agente: Agente, autenticador: AutenticadorLocal) -> None:
        self._agente = agente
        self._auth = autenticador
        self._activos: set[WebSocket] = set()

    async def manejar(self, websocket: WebSocket) -> None:
        """Punto de entrada para FastAPI: `app.websocket('/ws')(handler)`."""
        await websocket.accept()
        token = websocket.query_params.get("token", "")
        if not self._auth.validar(token):
            await websocket.close(code=4401)
            return

        self._activos.add(websocket)
        try:
            await self._bucle(websocket)
        except WebSocketDisconnect:
            log.info("Cliente desconectado")
        finally:
            self._activos.discard(websocket)

    async def difundir(self, evento: str, datos: dict[str, Any]) -> None:
        """Envía un mensaje a todos los clientes conectados."""
        payload = orjson.dumps({"evento": evento, "datos": datos}).decode()
        for ws in list(self._activos):
            try:
                await ws.send_text(payload)
            except Exception:  # noqa: BLE001
                self._activos.discard(ws)

    async def _bucle(self, websocket: WebSocket) -> None:
        while True:
            mensaje = await websocket.receive_text()
            try:
                payload = orjson.loads(mensaje)
            except orjson.JSONDecodeError:
                await websocket.send_text(
                    orjson.dumps({"evento": "error", "datos": "JSON inválido"}).decode()
                )
                continue

            tipo = payload.get("tipo")
            if tipo == "chat":
                async for trozo in self._agente.stream(payload["texto"]):
                    await websocket.send_text(
                        orjson.dumps({"evento": "token", "datos": trozo}).decode()
                    )
                await websocket.send_text(
                    orjson.dumps({"evento": "fin", "datos": ""}).decode()
                )
            else:
                await websocket.send_text(
                    orjson.dumps({"evento": "error", "datos": f"tipo desconocido: {tipo}"}).decode()
                )
