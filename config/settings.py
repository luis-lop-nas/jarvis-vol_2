"""Configuración central cargada desde variables de entorno (.env)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

NivelLog = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """Configuración global del agente.

    Las variables se cargan desde el archivo `.env` en la raíz del proyecto.
    Cualquier valor puede sobrescribirse vía variable de entorno del proceso.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Kimi ---
    kimi_api_key: SecretStr = Field(default=SecretStr(""))
    kimi_base_url: str = Field(default="https://api.moonshot.ai/v1")
    kimi_model_default: str = Field(default="kimi-k2.6")
    kimi_model_thinking: str = Field(default="kimi-k2-thinking")

    # --- DeepSeek ---
    deepseek_api_key: SecretStr = Field(default=SecretStr(""))
    deepseek_base_url: str = Field(default="https://api.deepseek.com/v1")
    deepseek_model_default: str = Field(default="deepseek-chat")
    deepseek_model_reasoner: str = Field(default="deepseek-reasoner")

    # --- OpenRouter ---
    openrouter_api_key: SecretStr = Field(default=SecretStr(""))
    openrouter_base_url: str = Field(default="https://openrouter.ai/api/v1")

    # --- Ollama ---
    ollama_base_url: str = Field(default="http://localhost:11434")
    ollama_model_default: str = Field(default="gemma4:4b")
    ollama_model_code: str = Field(default="qwen3-coder:8b")
    ollama_model_reasoning: str = Field(default="qwen3:8b")
    ollama_model_embed: str = Field(default="nomic-embed-text")
    ollama_max_ram_gb: float = Field(default=5.0, gt=0)
    ollama_timeout_s: int = Field(default=30, gt=0)

    # --- Router ---
    router_prefer_local: bool = Field(default=False)
    router_log_decisions: bool = Field(default=True)
    router_fallback_enabled: bool = Field(default=True)

    # --- Puertos ---
    api_port: int = Field(default=8765, ge=1, le=65535)
    websocket_port: int = Field(default=8765, ge=1, le=65535)
    chromadb_port: int = Field(default=8000, ge=1, le=65535)
    n8n_port: int = Field(default=5678, ge=1, le=65535)

    # --- Memoria ---
    chroma_host: str = Field(default="localhost")
    chroma_port: int = Field(default=8000, ge=1, le=65535)
    chroma_collection: str = Field(default="jarvis_memory")
    short_term_max_tokens: int = Field(default=8000, ge=1)
    short_term_max_messages: int = Field(default=100, ge=1)
    memory_importance_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    memory_dedup_threshold: float = Field(default=0.92, ge=0.0, le=1.0)
    vault_timeout_seconds: int = Field(default=30, ge=1)

    # --- Rutas ---
    chromadb_path: Path = Field(default=Path("./data/chromadb"))
    vault_path: Path = Field(default=Path("./data/vault"))
    audit_log_path: Path = Field(default=Path("./data/audit.log"))
    embed_cache_path: Path = Field(default=Path("./data/embeddings_cache.sqlite"))

    # --- Logging ---
    log_level: NivelLog = Field(default="INFO")

    # --- Modo de ejecución ---
    chroma_mode: Literal["local", "docker"] = Field(default="local")
    use_docker: bool = Field(default=False)

    # --- Seguridad ---
    confirmacion_destructiva: bool = Field(default=True)
    max_acciones_autonomas: int = Field(default=10, ge=1)
    sandbox_enabled: bool = Field(default=True)
    security_docker_sandbox_enabled: bool = Field(default=False)

    # --- MCP / Observabilidad ---
    mcp_otel_enabled: bool = Field(default=False)

    # --- Identidad ---
    usuario_nombre: str = Field(default="Usuario")
    zona_horaria: str = Field(default="Europe/Madrid")

    def asegurar_directorios(self) -> None:
        """Crea los directorios de datos si no existen."""
        for ruta in (self.chromadb_path, self.vault_path):
            ruta.mkdir(parents=True, exist_ok=True)
        for archivo in (self.audit_log_path, self.embed_cache_path):
            archivo.parent.mkdir(parents=True, exist_ok=True)


settings = Settings()
