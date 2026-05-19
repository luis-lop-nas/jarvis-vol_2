"""Modelos Pydantic compartidos entre API REST y WebSocket de JARVIS."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Petición de conversación."""

    message: str = Field(max_length=8192)
    session_id: str | None = Field(None, max_length=64)
    attachments: list[str] = Field(default_factory=list, max_length=10)


class ChatResponse(BaseModel):
    """Respuesta inmediata de POST /chat."""

    session_id: str
    status: str  # "started" | "queued" | "error"


class ConfirmRequest(BaseModel):
    """Confirmación o rechazo de una acción pendiente."""

    action_id: str = Field(max_length=128)
    confirmed: bool
    request_id: str | None = Field(None, max_length=128)


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
    mcp_health: dict[str, bool] = Field(default_factory=dict)
    total_cost_usd: float = 0.0


class SkillInfo(BaseModel):
    """Información pública de un skill registrado."""

    nombre: str
    descripcion: str
    version: str
    autor: str
    enabled: bool
    herramientas: list[str]
    riesgos: list[str]
    ejemplos: int


class SkillsResponse(BaseModel):
    """Respuesta del endpoint GET /skills."""

    total: int
    skills: list[SkillInfo]
