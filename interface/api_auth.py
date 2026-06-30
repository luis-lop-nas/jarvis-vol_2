"""Autenticación y rate limiting por IP para la API local de JARVIS.

Token local generado en memoria al arrancar — nunca persiste en disco por sí solo.
Escríbelo a disco desde main.py si el overlay necesita leerlo.
"""

from __future__ import annotations

import os
import re
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Annotated

from fastapi import Header, HTTPException

# Exportado para importarlo en api.py (evitar definición duplicada)
SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

_API_TOKEN: str = secrets.token_hex(32)

# Rate limiting por IP: ventana deslizante de 1 minuto
_IP_RATE: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=120))
_IP_RATE_LIMIT = 60
_IP_RATE_WINDOW = 60.0


def get_api_token() -> str:
    """Devuelve el token de sesión activo.

    Ejemplo::
        token = get_api_token()
        # main.py lo escribe a ~/.jarvis/.api_token (0600) para el overlay
    """
    return _API_TOKEN


def token_file_path() -> Path:
    """Ruta del fichero de token que lee el overlay SwiftUI.

    Ejemplo::
        ruta = token_file_path()  # ~/.jarvis/.api_token
    """
    return Path.home() / ".jarvis" / ".api_token"


def write_api_token(path: Path | None = None) -> Path:
    """Escribe el token a ``~/.jarvis/.api_token`` con permisos 0600.

    El overlay SwiftUI lee este fichero para autenticarse en el WebSocket
    (``/ws?token=...``) y en los endpoints REST. Escritura atómica con
    ``O_TRUNC`` y permisos restrictivos para que ningún otro usuario lo lea.

    Ejemplo::
        ruta = write_api_token()  # devuelve la ruta escrita
    """
    destino = path or token_file_path()
    destino.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(destino), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fichero:
        fichero.write(_API_TOKEN)
    return destino


def check_ip_rate(ip: str) -> bool:
    """Devuelve True si la IP no ha superado el límite, registrando la petición.

    Ejemplo::
        if not check_ip_rate(request.client.host):
            raise HTTPException(status_code=429, ...)
    """
    now = time.monotonic()
    times = _IP_RATE[ip]
    while times and now - times[0] >= _IP_RATE_WINDOW:
        times.popleft()
    if len(times) >= _IP_RATE_LIMIT:
        return False
    times.append(now)
    return True


async def require_auth(
    x_jarvis_token: Annotated[str | None, Header()] = None,
) -> None:
    """Dependencia FastAPI: exige cabecera X-JARVIS-Token válida.

    Uso::
        @app.get("/endpoint", dependencies=[Depends(require_auth)])
        async def endpoint(): ...
    """
    if x_jarvis_token != _API_TOKEN:
        raise HTTPException(status_code=401, detail="No autorizado")
