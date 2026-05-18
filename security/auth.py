"""Autenticación local vía Face ID / Touch ID usando LocalAuthentication de macOS."""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import datetime, timezone

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

_LA_POLICY_BIO = 1       # LAPolicyDeviceOwnerAuthenticationWithBiometrics
_LA_POLICY_DEVICE = 2    # LAPolicyDeviceOwnerAuthentication
_LA_BIOMETRY_TOUCH = 1   # LABiometryTypeTouchID
_LA_BIOMETRY_FACE = 2    # LABiometryTypeFaceID

_AUTH_CACHE_SECONDS = 60
_AUTH_TIMEOUT_SECONDS = 30


class AuthResult(BaseModel):
    """Resultado de un intento de autenticación."""

    success: bool
    method: str  # "face_id" | "touch_id" | "password" | "failed"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reason: str | None = None
    error: str | None = None


class AuthError(Exception):
    """Lanzado por require_auth() si la autenticación falla.

    Ejemplo::
        try:
            await auth.require_auth("Acceder al vault")
        except AuthError as e:
            print(e.message)
    """

    def __init__(self, message: str, reason: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.timestamp = datetime.now(timezone.utc)


class AuthManager:
    """Gestiona autenticación biométrica macOS via LocalAuthentication.

    Ejemplo::
        auth = AuthManager()
        result = await auth.authenticate("JARVIS necesita acceder a tus credenciales")
        if result.success:
            print("Autenticado via", result.method)
    """

    def __init__(self) -> None:
        self._last_auth: AuthResult | None = None
        self._lock = asyncio.Lock()
        # Single-flight: evita abrir dos diálogos Face ID en paralelo
        self._in_flight: "asyncio.Future[AuthResult] | None" = None

    async def authenticate(self, reason: str) -> AuthResult:
        """Muestra el diálogo nativo de Face ID con el motivo dado.

        Caché 60s + single-flight: llamadas concurrentes comparten el mismo diálogo.

        Ejemplo::
            result = await auth.authenticate("JARVIS necesita tus credenciales")
        """
        async with self._lock:
            # 1. Comprobar caché
            if self._last_auth and self._last_auth.success:
                elapsed = (datetime.now(timezone.utc) - self._last_auth.timestamp).total_seconds()
                if elapsed < _AUTH_CACHE_SECONDS:
                    return self._last_auth

            # 2. Single-flight: si ya hay un diálogo abierto, suscribirse a él
            if self._in_flight is not None:
                follower_future = self._in_flight
            else:
                loop = asyncio.get_running_loop()
                follower_future = None
                self._in_flight = loop.create_future()

        if follower_future is not None:
            # Esperar el resultado del líder sin posibilidad de cancelar el diálogo
            return await asyncio.shield(follower_future)

        # 3. Somos el líder — ejecutar biometría en thread pool
        result = AuthResult(success=False, method="failed", reason=reason, error="No iniciado")
        try:
            result = await asyncio.to_thread(self._authenticate_sync, reason)
        except Exception as exc:
            result = AuthResult(success=False, method="failed", reason=reason, error=str(exc))
        finally:
            # Siempre resolver el future y limpiar, incluso si hay CancelledError
            async with self._lock:
                if self._in_flight is not None and not self._in_flight.done():
                    self._in_flight.set_result(result)
                self._in_flight = None
                if result.success:
                    self._last_auth = result

        return result

    async def authenticate_for_action(self, action_description: str) -> AuthResult:
        """Wrapper con reason formateado: "Autorizar: {action_description}".

        Ejemplo::
            result = await auth.authenticate_for_action("borrar ~/Downloads/temp.pdf")
        """
        return await self.authenticate(f"Autorizar: {action_description}")

    def is_biometrics_available(self) -> bool:
        """Devuelve True si Face ID o Touch ID está configurado en este Mac.

        Ejemplo::
            if auth.is_biometrics_available():
                print("Biometría disponible")
        """
        try:
            import LocalAuthentication as LA  # pyobjc-framework-LocalAuthentication
            ctx = LA.LAContext.alloc().init()
            can_use, _ = ctx.canEvaluatePolicy_error_(
                _LA_POLICY_BIO, None  # type: ignore[arg-type]
            )
            return bool(can_use)
        except Exception:
            return False

    async def require_auth(self, reason: str) -> None:
        """Lanza AuthError si la autenticación falla.

        Usado como guard en vault.py y confirmation.py.

        Ejemplo::
            await auth.require_auth("Acceder a 1Password")  # lanza AuthError si falla
        """
        result = await self.authenticate(reason)
        if not result.success:
            raise AuthError(
                f"Autenticación fallida: {result.error or 'rechazada por el usuario'}",
                reason=reason,
            )

    def get_auth_policy(self) -> str:
        """Devuelve la política de autenticación disponible: "face_id" | "touch_id" | "password_only" | "none".

        Ejemplo::
            policy = auth.get_auth_policy()  # "face_id"
        """
        try:
            import LocalAuthentication as LA  # pyobjc-framework-LocalAuthentication
            ctx = LA.LAContext.alloc().init()
            can_bio, _ = ctx.canEvaluatePolicy_error_(_LA_POLICY_BIO, None)  # type: ignore[arg-type]
            if not can_bio:
                can_pwd, _ = ctx.canEvaluatePolicy_error_(_LA_POLICY_DEVICE, None)  # type: ignore[arg-type]
                return "password_only" if can_pwd else "none"
            biometry = int(ctx.biometryType())
            if biometry == _LA_BIOMETRY_FACE:
                return "face_id"
            if biometry == _LA_BIOMETRY_TOUCH:
                return "touch_id"
            return "password_only"
        except Exception:
            return "none"

    # ------------------------------------------------------------------
    # Sincrónico — corre en thread pool via asyncio.to_thread
    # ------------------------------------------------------------------

    def _authenticate_sync(self, reason: str) -> AuthResult:
        try:
            import LocalAuthentication as LA  # type: ignore[import]
        except ImportError:
            return AuthResult(
                success=False,
                method="failed",
                reason=reason,
                error="LocalAuthentication no disponible (¿no es macOS o falta pyobjc?)",
            )
        except Exception as exc:
            return AuthResult(success=False, method="failed", reason=reason, error=str(exc))

        try:
            ctx = LA.LAContext.alloc().init()
            can_bio, _ = ctx.canEvaluatePolicy_error_(_LA_POLICY_BIO, None)  # type: ignore[arg-type]
            policy = _LA_POLICY_BIO if can_bio else _LA_POLICY_DEVICE

            event = threading.Event()
            result_box: dict[str, object] = {}

            def reply(success: bool, error: object) -> None:
                result_box["success"] = bool(success)
                result_box["error"] = str(error) if error else None
                event.set()

            ctx.evaluatePolicy_localizedReason_reply_(policy, reason, reply)  # type: ignore[attr-defined]

            if not event.wait(timeout=_AUTH_TIMEOUT_SECONDS):
                return AuthResult(
                    success=False,
                    method="failed",
                    reason=reason,
                    error=f"Timeout: no hubo respuesta en {_AUTH_TIMEOUT_SECONDS}s",
                )

            success = bool(result_box.get("success", False))
            if success and can_bio:
                biometry = int(ctx.biometryType())
                method = (
                    "face_id" if biometry == _LA_BIOMETRY_FACE
                    else "touch_id" if biometry == _LA_BIOMETRY_TOUCH
                    else "password"
                )
            elif success:
                method = "password"
            else:
                method = "failed"

            return AuthResult(
                success=success,
                method=method,
                reason=reason,
                error=result_box.get("error") if not success else None,  # type: ignore[arg-type]
            )
        except Exception as exc:
            return AuthResult(success=False, method="failed", reason=reason, error=str(exc))
