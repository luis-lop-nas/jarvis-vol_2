"""Cliente WebSocket async para el TUI. Conecta al backend FastAPI con reconexión exponencial."""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

log = logging.getLogger(__name__)

OnMessage = Callable[[dict[str, Any]], Awaitable[None]]
OnStatus  = Callable[[bool], Awaitable[None]]


class TUIWebSocketClient:
    """Conecta al backend JARVIS y gestiona el ciclo de vida del WS.

    Ejemplo::
        client = TUIWebSocketClient("ws://127.0.0.1:8765/ws", "abc123")
        await client.run(on_message=handler, on_status=status_handler)
    """

    def __init__(self, base_url: str, session_id: str) -> None:
        self._url = f"{base_url}?session_id={session_id}"
        self._session_id = session_id
        self._ws: Any = None
        self._send_queue: asyncio.Queue[dict] = asyncio.Queue()
        self.connected = False

    async def run(self, on_message: OnMessage, on_status: OnStatus) -> None:
        """Loop principal con backoff exponencial (1s → 30s)."""
        import websockets
        from websockets.exceptions import ConnectionClosed, InvalidHandshake, WebSocketException

        delay = 1.0
        while True:
            try:
                async with websockets.connect(
                    self._url,
                    ping_interval=20,
                    ping_timeout=10,
                    open_timeout=5,
                ) as ws:
                    self._ws = ws
                    self.connected = True
                    delay = 1.0
                    await on_status(True)

                    sender = asyncio.create_task(self._sender(ws))
                    try:
                        async for raw in ws:
                            try:
                                await on_message(json.loads(raw))
                            except json.JSONDecodeError:
                                log.debug("JSON inválido recibido: %.80s", raw)
                    except (ConnectionClosed, WebSocketException):
                        pass
                    finally:
                        sender.cancel()
                        try:
                            await sender
                        except asyncio.CancelledError:
                            pass

            except (InvalidHandshake, OSError, asyncio.TimeoutError):
                pass
            except Exception as exc:
                log.debug("WS error inesperado: %s", exc)

            self._ws = None
            self.connected = False
            await on_status(False)
            await asyncio.sleep(min(delay, 30.0))
            delay = min(delay * 2, 30.0)

    async def _sender(self, ws: Any) -> None:
        while True:
            msg = await self._send_queue.get()
            try:
                await ws.send(json.dumps(msg, ensure_ascii=False))
            except Exception:
                self._send_queue.put_nowait(msg)
                break

    # -- Mensajes salientes --

    async def send_message(self, content: str) -> None:
        await self._send_queue.put({
            "type": "message",
            "content": content,
            "session_id": self._session_id,
        })

    async def send_confirm(self, action_id: str, confirmed: bool) -> None:
        await self._send_queue.put({
            "type": "confirm",
            "action_id": action_id,
            "confirmed": confirmed,
            "session_id": self._session_id,
        })

    async def send_cancel(self) -> None:
        await self._send_queue.put({
            "type": "cancel",
            "session_id": self._session_id,
        })
