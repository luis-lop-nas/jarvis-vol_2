"""Sistema de confirmación de acciones — integrado con WebSocket.

El agente queda pausado hasta que el usuario confirme o expire el timeout.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from security.audit_log import AuditLog
    from security.auth import AuthManager

log = logging.getLogger(__name__)

_CONFIRMATION_TIMEOUT = 60.0
_RATE_LIMIT_MAX = 10
_RATE_LIMIT_WINDOW = 60.0

WsSender = Callable[[dict], Awaitable[None]]


class SecurityError(Exception):
    """Lanzado cuando se detecta una violación del modelo de seguridad.

    Ejemplo::
        try:
            cm.resolve(request_id, True, session_id="otra-sesion")
        except SecurityError:
            print("Violación de seguridad detectada")
    """


class ConfirmationRequest(BaseModel):
    """Solicitud de confirmación pendiente de respuesta del usuario."""

    id: str
    session_id: str = ""  # sesión propietaria; "" = sin scoping (compatibilidad)
    action_description: str
    command: str | None = None
    action_type: str = ""  # ej: "eliminar", "enviar_email" — para UI adaptativa
    risk_level: str  # "moderate" | "dangerous"
    requires_auth: bool
    affected_items: list[str] | None = None  # lista de paths/nombres afectados
    affected_count: int = 0                  # total cuando affected_items está truncado
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
    Incluye rate limiting (máx 10 confirmaciones por sesión en 60s) y scoping
    por session_id para evitar que una sesión resuelva confirmaciones de otra.

    Ejemplo::
        cm = ConfirmationManager(ws_sender=manager.broadcast)
        result = await cm.request_confirmation("Eliminar archivo.pdf", risk_level="dangerous", session_id="sess-1")
        if result.confirmed:
            print("Usuario aprobó")
    """

    def __init__(
        self,
        ws_sender: WsSender | None = None,
        auth_manager: AuthManager | None = None,
        audit_log: AuditLog | None = None,
    ) -> None:
        self._ws_sender = ws_sender
        self._auth = auth_manager
        self._audit = audit_log
        self._pending: dict[str, tuple[ConfirmationRequest, asyncio.Event, dict[str, object]]] = {}
        self._rate_state: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=_RATE_LIMIT_MAX))

    async def request_confirmation(
        self,
        action_description: str,
        command: str | None = None,
        action_type: str = "",
        risk_level: str = "moderate",
        requires_auth: bool = False,
        affected_items: list[str] | None = None,
        affected_count: int = 0,
        session_id: str = "",
    ) -> ConfirmationResult:
        """Pausa el agente y espera confirmación del usuario (máx. 60 segundos).

        1. Verifica rate limit por sesión (máx 10 en 60s)
        2. Crea ConfirmationRequest con UUID y session_id
        3. Envía al overlay via WebSocket: type="waiting"
        4. Pausa el agente con asyncio.Event
        5. Espera respuesta máximo 60 segundos
        6. Si requires_auth=True → llama auth.authenticate()

        Ejemplo::
            result = await cm.request_confirmation("Eliminar brief.pdf", risk_level="dangerous", session_id="sess-1")
        """
        # Rate limiting por sesión
        if session_id:
            now_mono = time.monotonic()
            times = self._rate_state[session_id]
            while times and now_mono - times[0] >= _RATE_LIMIT_WINDOW:
                times.popleft()
            if len(times) >= _RATE_LIMIT_MAX:
                log.warning(
                    "Rate limit de confirmaciones excedido para sesión %s (%d en %ds)",
                    session_id, _RATE_LIMIT_MAX, int(_RATE_LIMIT_WINDOW),
                )
                return ConfirmationResult(request_id="rate-limited", confirmed=False)
            times.append(now_mono)

        req_id = str(uuid.uuid4())
        now = datetime.now(UTC)
        request = ConfirmationRequest(
            id=req_id,
            session_id=session_id,
            action_description=action_description,
            command=command,
            action_type=action_type,
            risk_level=risk_level,
            requires_auth=requires_auth,
            affected_items=affected_items,
            affected_count=affected_count if affected_count else (len(affected_items) if affected_items else 0),
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
                        "action_type": request.action_type,
                        "risk_level": risk_level,
                        "requires_auth": requires_auth,
                        "affected_items": request.affected_items,
                        "affected_count": request.affected_count,
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

    def resolve(self, request_id: str, confirmed: bool, session_id: str = "") -> None:
        """Desbloquea el agente con el resultado del usuario.

        Verifica que request_id pertenece a session_id antes de resolver.
        Lanza SecurityError si la sesión no coincide (y la registra en audit_log).
        Llamado desde POST /confirm del API.
        Idempotente: llamadas repetidas no alteran el resultado ya resuelto.

        Ejemplo::
            cm.resolve("abc-123", confirmed=True, session_id="sess-1")
        """
        entry = self._pending.get(request_id)
        if entry is None:
            log.warning("resolve() para request_id desconocido: %s", request_id)
            return
        req, event, result_box = entry

        # Scoping: verificar que el resolver pertenece a la sesión propietaria
        if session_id and req.session_id and req.session_id != session_id:
            log.error(
                "Violación de seguridad: sesión %r intentó resolver confirmación de sesión %r (request_id=%s)",
                session_id, req.session_id, request_id,
            )
            self._log_violation_async(
                attacker_session=session_id,
                owner_session=req.session_id,
                request_id=request_id,
            )
            raise SecurityError("Intento de resolver confirmación de otra sesión")

        # Verificar que la solicitud no haya expirado
        if datetime.now(UTC) > req.expires_at:
            log.warning("resolve() para request_id expirado: %s", request_id)
            return
        # Solo resolver la primera vez (idempotente)
        if not event.is_set():
            result_box["confirmed"] = confirmed
            event.set()

    def _log_violation_async(
        self,
        *,
        attacker_session: str,
        owner_session: str,
        request_id: str,
    ) -> None:
        """Registra una violación de seguridad en el audit log (fire-and-forget)."""
        if self._audit is None:
            return
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                self._audit.log_action(
                    session_id=attacker_session,
                    action_type="security_violation",
                    action="cross_session_confirmation",
                    details={
                        "request_id": request_id,
                        "owner_session": owner_session,
                        "attacker_session": attacker_session,
                    },
                    result="blocked",
                    risk_level="dangerous",
                    confirmed=False,
                    authenticated=False,
                    duration_ms=0,
                )
            )
        except RuntimeError:
            log.warning("No se pudo registrar violación en audit log: sin event loop")

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
