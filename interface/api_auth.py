"""Autenticación y rate limiting por IP para la API local de JARVIS.

Token local generado en memoria al arrancar — nunca persiste en disco por sí solo.
Escríbelo a disco desde main.py si el overlay necesita leerlo.
"""

from __future__ import annotations

import re
import secrets
import time
from collections import defaultdict, deque
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
