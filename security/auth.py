"""Autenticación local del usuario para el servidor de JARVIS."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone


class AutenticadorLocal:
    """Autenticación simple basada en token compartido y sesiones efímeras.

    Pensado para uso en `localhost` (un solo usuario). Para multiusuario o
    exposición remota habría que migrar a OAuth2 / mTLS.
    """

    def __init__(self, secreto_maestro: str, duracion_sesion_horas: int = 12) -> None:
        if len(secreto_maestro) < 32:
            raise ValueError("El secreto debe tener al menos 32 caracteres")
        self._secreto = secreto_maestro.encode("utf-8")
        self._duracion = timedelta(hours=duracion_sesion_horas)
        self._sesiones: dict[str, datetime] = {}

    def crear_token(self) -> str:
        """Crea un token de sesión criptográficamente fuerte."""
        token = secrets.token_urlsafe(48)
        self._sesiones[token] = datetime.now(timezone.utc) + self._duracion
        return token

    def revocar(self, token: str) -> None:
        self._sesiones.pop(token, None)

    def validar(self, token: str) -> bool:
        """`True` si el token existe y no ha expirado."""
        expira = self._sesiones.get(token)
        if expira is None:
            return False
        if datetime.now(timezone.utc) > expira:
            self._sesiones.pop(token, None)
            return False
        return True

    def hash_secreto(self, datos: str) -> str:
        """HMAC-SHA256 con el secreto maestro (para firmar payloads internos)."""
        return hmac.new(self._secreto, datos.encode("utf-8"), hashlib.sha256).hexdigest()
