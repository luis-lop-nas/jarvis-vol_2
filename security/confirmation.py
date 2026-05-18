"""Sistema de confirmación de acciones — integrado con WebSocket.

El agente queda pausado hasta que el usuario confirme o expire el timeout.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from security.auth import AuthManager

log = logging.getLogger(__name__)

_CONFIRMATION_TIMEOUT = 60.0
WsSender = Callable[[dict], Awaitable[None]]


class ConfirmationRequest(BaseModel):
    """Solicitud de confirmación pendiente de respuesta del usuario."""

    id: str
    action_description: str
    command: str | None = None
    risk_level: str  # "moderate" | "dangerous"
    requires_auth: bool
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC) + timedelta(seconds=60)
    )


class ConfirmationResult(BaseModel):
    """Resultado de una solicitud de confirmación."""

    request_id: str
    confirmed: bool
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    authenticated: bool = False


class ConfirmationError(Exception):
    """Lanzado por require_confirmation_for() si el usuario no confirma.

    Ejemplo::
        try:
            await cm.require_confirmation_for("borrar config.json")
        except ConfirmationError:
            print("Acción denegada")
    """


# Acciones que SIEMPRE requieren Face ID además de confirmación
_ALWAYS_REQUIRES_AUTH: frozenset[str] = frozenset({
    "delete_permanent",
    "send_email",
    "send_imessage",
    "sudo",
    "vault_access",
    "git_push",
    "payment",
})


class ConfirmationManager:
    """Gestiona confirmaciones humanas para acciones sensibles.

    Se integra con el WebSocket para pedir OK al usuario en el overlay.
    El agente queda suspendido hasta recibir respuesta o expirar el timeout.

    Ejemplo::
        cm = ConfirmationManager(ws_sender=manager.broadcast)
        result = await cm.request_confirmation("Eliminar archivo.pdf", risk_level="dangerous")
        if result.confirmed:
            print("Usuario aprobó")
    """

    def __init__(
        self,
        ws_sender: WsSender | None = None,
        auth_manager: AuthManager | None = None,
    ) -> None:
        self._ws_sender = ws_sender
        self._auth = auth_manager
        self._pending: dict[str, tuple[ConfirmationRequest, asyncio.Event, dict[str, object]]] = {}

    async def request_confirmation(
        self,
        action_description: str,
        command: str | None = None,
        risk_level: str = "moderate",
        requires_auth: bool = False,
    ) -> ConfirmationResult:
        """Pausa el agente y espera confirmación del usuario (máx. 60 segundos).

        1. Crea ConfirmationRequest con UUID
        2. Envía al overlay via WebSocket: type="waiting"
        3. Pausa el agente con asyncio.Event
        4. Espera respuesta máximo 60 segundos
        5. Si requires_auth=True → llama auth.authenticate()

        Ejemplo::
            result = await cm.request_confirmation("Eliminar brief.pdf", risk_level="dangerous")
        """
        req_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        request = ConfirmationRequest(
            id=req_id,
            action_description=action_description,
            command=command,
            risk_level=risk_level,
            requires_auth=requires_auth,
            created_at=now,
            expires_at=now + timedelta(seconds=_CONFIRMATION_TIMEOUT),
        )

        event = asyncio.Event()
        result_box: dict[str, object] = {}
        self._pending[req_id] = (request, event, result_box)

        if self._ws_sender is not None:
            try:
                await self._ws_sender({
                    "type": "waiting",
                    "data": {
                        "confirmation_id": req_id,
                        "action": action_description,
                        "command": command,
                        "risk_level": risk_level,
                        "requires_auth": requires_auth,
                        "expires_in": int(_CONFIRMATION_TIMEOUT),
                    },
                })
            except Exception:
                log.exception("Error enviando confirmación al WebSocket")

        try:
            await asyncio.wait_for(event.wait(), timeout=_CONFIRMATION_TIMEOUT)
        except TimeoutError:
            self._pending.pop(req_id, None)
            log.warning("Confirmación %s expiró por timeout", req_id)
            return ConfirmationResult(request_id=req_id, confirmed=False)

        self._pending.pop(req_id, None)
        confirmed = bool(result_box.get("confirmed", False))

        authenticated = False
        if confirmed and requires_auth and self._auth is not None:
            try:
                await self._auth.require_auth(f"Autorizar: {action_description}")
                authenticated = True
            except Exception:
                confirmed = False
                log.warning("Face ID falló para confirmación %s", req_id)

        return ConfirmationResult(
            request_id=req_id,
            confirmed=confirmed,
            authenticated=authenticated,
        )

    def resolve(self, request_id: str, confirmed: bool) -> None:
        """Desbloquea el agente con el resultado del usuario.

        Llamado desde POST /confirm del API.
        Idempotente: llamadas repetidas no alteran el resultado ya resuelto.

        Ejemplo::
            cm.resolve("abc-123", confirmed=True)
        """
        entry = self._pending.get(request_id)
        if entry is None:
            log.warning("resolve() para request_id desconocido: %s", request_id)
            return
        req, event, result_box = entry
        # Verificar que la solicitud no haya expirado
        if datetime.now(UTC) > req.expires_at:
            log.warning("resolve() para request_id expirado: %s", request_id)
            return
        # Solo resolver la primera vez (idempotente)
        if not event.is_set():
            result_box["confirmed"] = confirmed
            event.set()

    def get_pending(self) -> list[ConfirmationRequest]:
        """Devuelve confirmaciones pendientes de respuesta.

        Ejemplo::
            pending = cm.get_pending()
            print(len(pending), "confirmaciones pendientes")
        """
        return [req for req, _, _ in self._pending.values()]

    async def require_confirmation_for(self, action: str, command: str | None = None) -> None:
        """Shorthand que lanza ConfirmationError si no confirmado.

        Ejemplo::
            await cm.require_confirmation_for("mover archivos a Papelera")
        """
        result = await self.request_confirmation(
            action_description=action,
            command=command,
            risk_level="moderate",
        )
        if not result.confirmed:
            raise ConfirmationError(f"Acción no confirmada: {action}")
