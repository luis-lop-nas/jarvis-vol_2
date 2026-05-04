"""API HTTP de JARVIS basada en FastAPI."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel as PydanticModel
from sse_starlette.sse import EventSourceResponse

from core.agent import Agente
from security.auth import AutenticadorLocal


class PeticionUsuario(PydanticModel):
    """Cuerpo de la petición /chat."""

    texto: str


class RespuestaAgente(PydanticModel):
    """Respuesta del endpoint /chat."""

    respuesta: str
    sesion_id: str


def crear_app(agente: Agente, autenticador: AutenticadorLocal) -> FastAPI:
    """Construye la `FastAPI` con sus rutas, inyectando dependencias."""
    app = FastAPI(title="JARVIS API", version="0.1.0")
    bearer = HTTPBearer()

    def verificar_token(
        credenciales: HTTPAuthorizationCredentials = Depends(bearer),
    ) -> str:
        if not autenticador.validar(credenciales.credentials):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token inválido o expirado",
            )
        return credenciales.credentials

    @app.get("/health")
    async def health() -> dict[str, str]:
        """Endpoint público para health checks."""
        return {"status": "ok"}

    @app.post("/chat", response_model=RespuestaAgente)
    async def chat(
        peticion: PeticionUsuario, _token: str = Depends(verificar_token)
    ) -> RespuestaAgente:
        """Procesa una petición conversacional síncrona."""
        respuesta = await agente.procesar(peticion.texto)
        return RespuestaAgente(respuesta=respuesta, sesion_id=agente.estado.sesion_id)

    @app.post("/chat/stream")
    async def chat_stream(
        peticion: PeticionUsuario, _token: str = Depends(verificar_token)
    ) -> EventSourceResponse:
        """Streaming SSE de la respuesta del agente."""

        async def generador() -> Any:
            async for trozo in agente.stream(peticion.texto):
                yield {"event": "token", "data": trozo}
            yield {"event": "fin", "data": ""}

        return EventSourceResponse(generador())

    return app
