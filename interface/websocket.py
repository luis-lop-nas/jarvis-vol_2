"""Canal WebSocket bidireccional — overlay SwiftUI ↔ JARVIS."""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from typing import Any

import orjson
from fastapi import WebSocket

log = logging.getLogger(__name__)

BUFFER_SIZE = 50


class ConnectionManager:
    """Gestiona conexiones WebSocket por sesión con buffer de reconexión.

    Al reconectar, el cliente recibe automáticamente los últimos mensajes
    perdidos almacenados en el buffer circular por sesión.

    Ejemplo::
        manager = ConnectionManager()
        await manager.connect(ws, session_id)
        await manager.send(session_id, {"type": "thinking", "message": "..."})
    """

    def __init__(self) -> None:
        self._sockets: dict[str, WebSocket] = {}
        self._buffers: dict[str, deque[dict[str, Any]]] = defaultdict(
            lambda: deque(maxlen=BUFFER_SIZE)
        )

    async def connect(self, websocket: WebSocket, session_id: str) -> None:
        """Acepta la conexión WS y envía mensajes pendientes del buffer."""
        await websocket.accept()
        self._sockets[session_id] = websocket
        for msg in list(self._buffers[session_id]):
            try:
                await websocket.send_text(orjson.dumps(msg).decode())
            except Exception:
                break
        log.info("WS sesión=%s conectada", session_id)

    def disconnect(self, session_id: str) -> None:
        self._sockets.pop(session_id, None)
        log.info("WS sesión=%s desconectada", session_id)

    async def send(self, session_id: str, message: dict[str, Any]) -> None:
        """Envía un mensaje a la sesión y lo añade al buffer de reconexión."""
        self._buffers[session_id].append(message)
        ws = self._sockets.get(session_id)
        if ws is None:
            return
        try:
            await ws.send_text(orjson.dumps(message).decode())
        except Exception:
            self._sockets.pop(session_id, None)

    async def broadcast(self, message: dict[str, Any]) -> None:
        """Envía un mensaje a todas las sesiones activas."""
        payload = orjson.dumps(message).decode()
        dead: list[str] = []
        for sid, ws in list(self._sockets.items()):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(sid)
        for sid in dead:
            self._sockets.pop(sid, None)

    def get_active_sessions(self) -> list[str]:
        return list(self._sockets.keys())
