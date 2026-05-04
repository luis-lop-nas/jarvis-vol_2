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

    # --- Ollama ---
    ollama_host: str = Field(
        default="http://localhost:11434",
        description="URL base del servicio Ollama local.",
    )
    ollama_default_model: str = Field(default="llama3.2")
    ollama_embed_model: str = Field(default="nomic-embed-text")

    # --- Kimi (Moonshot) ---
    kimi_api_key: SecretStr = Field(default=SecretStr(""))
    kimi_base_url: str = Field(default="https://api.moonshot.cn/v1")
    kimi_default_model: str = Field(default="moonshot-v1-128k")

    # --- DeepSeek ---
    deepseek_api_key: SecretStr = Field(default=SecretStr(""))
    deepseek_base_url: str = Field(default="https://api.deepseek.com/v1")
    deepseek_default_model: str = Field(default="deepseek-chat")

    # --- OpenRouter ---
    openrouter_api_key: SecretStr = Field(default=SecretStr(""))
    openrouter_base_url: str = Field(default="https://openrouter.ai/api/v1")

    # --- Puertos ---
    api_port: int = Field(default=8080, ge=1, le=65535)
    websocket_port: int = Field(default=8081, ge=1, le=65535)
    chromadb_port: int = Field(default=8000, ge=1, le=65535)
    n8n_port: int = Field(default=5678, ge=1, le=65535)

    # --- Rutas ---
    chromadb_path: Path = Field(default=Path("./data/chromadb"))
    vault_path: Path = Field(default=Path("./data/vault"))
    audit_log_path: Path = Field(default=Path("./data/audit.log"))

    # --- Logging ---
    log_level: NivelLog = Field(default="INFO")

    # --- Seguridad ---
    confirmacion_destructiva: bool = Field(
        default=True,
        description="Pedir confirmación antes de ejecutar acciones destructivas.",
    )
    max_acciones_autonomas: int = Field(
        default=10,
        ge=1,
        description="Número máximo de acciones encadenadas sin intervención humana.",
    )
    sandbox_enabled: bool = Field(default=True)

    # --- Identidad ---
    usuario_nombre: str = Field(default="Usuario")
    zona_horaria: str = Field(default="Europe/Madrid")

    def asegurar_directorios(self) -> None:
        """Crea los directorios de datos si no existen."""
        for ruta in (self.chromadb_path, self.vault_path):
            ruta.mkdir(parents=True, exist_ok=True)
        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)


settings = Settings()
