"""Modelos Pydantic compartidos entre API REST y WebSocket de JARVIS."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Petición de conversación."""

    message: str
    session_id: str | None = None
    attachments: list[str] = Field(default_factory=list)


class ChatResponse(BaseModel):
    """Respuesta inmediata de POST /chat."""

    session_id: str
    status: str  # "started" | "queued" | "error"


class ConfirmRequest(BaseModel):
    """Confirmación o rechazo de una acción pendiente."""

    action_id: str
    confirmed: bool


class AgentUpdate(BaseModel):
    """Evento que el servidor emite al cliente via SSE o WebSocket."""

    type: str  # "thinking" | "acting" | "waiting" | "done" | "error"
    message: str
    progress: float = 0.0
    step: dict | None = None
    result: dict | None = None
    state: str = "silent"  # hint para el overlay: "notch"|"edge"|"modal"|"inline"|"silent"


class ConfirmationRequest(BaseModel):
    """Descripción de una acción que espera confirmación del usuario."""

    action_id: str
    action_description: str
    command: str | None = None
    is_destructive: bool = False


class SystemStatus(BaseModel):
    """Estado de salud del sistema completo."""

    api_running: bool
    chroma_connected: bool
    ollama_running: bool
    available_models: list[str]
    ram_available_gb: float
    onepassword_available: bool
