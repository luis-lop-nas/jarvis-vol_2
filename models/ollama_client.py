"""Cliente para Ollama (modelos locales).

Características críticas en M3 8 GB:
- Detección automática de modelos disponibles al construir el cliente.
- Verificación de RAM disponible antes de cargar (`ollama_max_ram_gb`).
- Solo un modelo cargado a la vez: descarga (`keep_alive=0`) el anterior.
- Timeout agresivo (default 30s) para no bloquear el agente.
- Fallback automático a un modelo más pequeño si no hay RAM.
- Calcula tokens/segundo en cada respuesta (`eval_count` / `eval_duration`).
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
import orjson
import psutil

from config import settings
from models._common import log_model_call, mensaje_a_dict
from models.base import (
    BaseModel,
    Mensaje,
    ModelCapability,
    ModelConfig,
    ModelResponse,
    StreamChunk,
)

log = logging.getLogger(__name__)


# Tabla aproximada de RAM por modelo (GB). Se usa para decidir si cabemos.
RAM_APROXIMADA_GB: dict[str, float] = {
    "gemma4:4b": 3.5,
    "gemma3:4b": 3.5,
    "qwen3:8b": 5.5,
    "qwen3-coder:8b": 5.5,
    "qwen2.5-coder:7b": 5.0,
    "qwen2.5:3b": 2.5,
    "llama3.2": 2.5,
    "llama3.2:1b": 1.3,
    "qwen2.5:1.5b": 1.2,
    "qwen2.5:0.5b": 0.6,
    "nomic-embed-text": 0.3,
}


class OllamaModel(BaseModel):
    """Adaptador del servicio HTTP local de Ollama."""

    nombre = "ollama"

    def __init__(
        self,
        modelo: str | None = None,
        cliente: httpx.AsyncClient | None = None,
        audit_log: AuditLog | None = None,
    ) -> None:
        config = ModelConfig(
            name=modelo or settings.ollama_model_default,
            base_url=settings.ollama_base_url,
            timeout=float(settings.ollama_timeout_s),
            capabilities=(
                ModelCapability.TEXT
                | ModelCapability.TOOL_USE
                | ModelCapability.EMBEDDING
            ),
        )
        super().__init__(config)
        self._cliente = cliente or httpx.AsyncClient(
            base_url=config.base_url,
            timeout=httpx.Timeout(connect=5, read=config.timeout, write=10, pool=5),
        )
        self._modelos_disponibles: set[str] = set()
        self._modelo_cargado: str | None = None
        self._inicializado = False
        self._audit_log = audit_log

    # ------------------------------------------------------------------
    # Inicialización (perezosa)
    # ------------------------------------------------------------------

    async def _asegurar_inicializado(self) -> None:
        if self._inicializado:
            return
        try:
            resp = await self._cliente.get("/api/tags", timeout=5.0)
            resp.raise_for_status()
            datos = resp.json()
            self._modelos_disponibles = {m["name"] for m in datos.get("models", [])}
            log.info("Ollama detectó modelos: %s", sorted(self._modelos_disponibles))
        except (httpx.HTTPError, httpx.TransportError) as exc:
            log.warning("No se pudo enumerar modelos de Ollama: %s", exc)
            self._modelos_disponibles = set()
        self._inicializado = True

    # ------------------------------------------------------------------
    # complete / stream
    # ------------------------------------------------------------------

    async def complete(
        self,
        mensajes: list[Mensaje],
        *,
        modelo: str | None = None,
        temperatura: float = 0.7,
        max_tokens: int | None = None,
        herramientas: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ModelResponse:
        await self._asegurar_inicializado()
        modelo_id = await self._preparar_modelo(modelo or self.config.name)

        cuerpo: dict[str, Any] = {
            "model": modelo_id,
            "messages": [mensaje_a_dict(m) for m in mensajes],
            "stream": False,
            "options": {"temperature": temperatura},
        }
        if max_tokens is not None:
            cuerpo["options"]["num_predict"] = max_tokens
        if herramientas:
            cuerpo["tools"] = herramientas

        inicio = time.monotonic()
        respuesta = await self._cliente.post("/api/chat", json=cuerpo)
        respuesta.raise_for_status()
        datos = orjson.loads(respuesta.content)
        duracion = int((time.monotonic() - inicio) * 1000)

        mensaje = datos.get("message", {})
        eval_count = int(datos.get("eval_count", 0))
        eval_dur_ns = int(datos.get("eval_duration", 0)) or 1
        tps = eval_count / (eval_dur_ns / 1_000_000_000)
        # Coste aproximado: tiempo de inferencia × tarifa configurada
        coste = (duracion / 1000.0) * settings.ollama_cost_per_second

        tokens_in = int(datos.get("prompt_eval_count", 0))
        respuesta = ModelResponse(
            content=mensaje.get("content", ""),
            model=datos.get("model", modelo_id),
            tokens_input=tokens_in,
            tokens_output=eval_count,
            duration_ms=duracion,
            finish_reason=datos.get("done_reason"),
            tool_calls=mensaje.get("tool_calls") or [],
            cost_usd=coste,
            metadatos={"tokens_per_second": tps},
        )
        await log_model_call(
            self._audit_log,
            modelo=respuesta.model,
            tokens_input=tokens_in,
            tokens_output=eval_count,
            latencia_ms=duracion,
            cost_usd=coste,
            cache_hit=False,
        )
        return respuesta

    async def stream(
        self,
        mensajes: list[Mensaje],
        *,
        modelo: str | None = None,
        temperatura: float = 0.7,
        max_tokens: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[StreamChunk]:
        await self._asegurar_inicializado()
        modelo_id = await self._preparar_modelo(modelo or self.config.name)

        cuerpo: dict[str, Any] = {
            "model": modelo_id,
            "messages": [mensaje_a_dict(m) for m in mensajes],
            "stream": True,
            "options": {"temperature": temperatura},
        }
        if max_tokens is not None:
            cuerpo["options"]["num_predict"] = max_tokens

        inicio = time.monotonic()
        tokens_emitidos = 0

        async with self._cliente.stream("POST", "/api/chat", json=cuerpo) as resp:
            resp.raise_for_status()
            async for linea in resp.aiter_lines():
                if not linea:
                    continue
                evento = orjson.loads(linea)
                trozo = evento.get("message", {}).get("content")
                if trozo:
                    tokens_emitidos += 1
                    transcurrido = max(time.monotonic() - inicio, 1e-6)
                    yield StreamChunk(
                        content=trozo,
                        model=modelo_id,
                        tokens_per_second=tokens_emitidos / transcurrido,
                    )
                if evento.get("done"):
                    yield StreamChunk(
                        content="", model=modelo_id, is_final=True
                    )
                    break

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------

    async def embed(self, textos: list[str]) -> list[list[float]]:
        """Calcula embeddings con `OLLAMA_MODEL_EMBED`."""
        await self._asegurar_inicializado()
        respuesta = await self._cliente.post(
            "/api/embed",
            json={"model": settings.ollama_model_embed, "input": textos},
        )
        respuesta.raise_for_status()
        return orjson.loads(respuesta.content)["embeddings"]

    # ------------------------------------------------------------------
    # Salud
    # ------------------------------------------------------------------

    async def health_check(self) -> bool:
        try:
            resp = await self._cliente.get("/api/tags", timeout=3.0)
            return resp.status_code == 200
        except (httpx.HTTPError, httpx.TransportError):
            return False

    async def cerrar(self) -> None:
        await self._cliente.aclose()

    # ------------------------------------------------------------------
    # Gestión de modelo cargado y RAM
    # ------------------------------------------------------------------

    async def _preparar_modelo(self, deseado: str) -> str:
        """Asegura que `deseado` está cargado, descargando otros si hace falta.

        Si no hay RAM suficiente, intenta caer a un modelo más pequeño.
        """
        if self._modelos_disponibles and deseado not in self._modelos_disponibles:
            log.warning("Modelo %s no disponible localmente; intentando uso directo.", deseado)

        if self._modelo_cargado == deseado:
            return deseado

        ram_disponible = self._ram_libre_gb()
        coste = RAM_APROXIMADA_GB.get(deseado, 4.0)
        limite = settings.ollama_max_ram_gb

        if coste > min(ram_disponible, limite):
            alternativa = self._fallback_mas_pequeno(deseado, min(ram_disponible, limite))
            if alternativa is None:
                raise RuntimeError(
                    f"Sin RAM suficiente para {deseado} ({coste:.1f} GB) "
                    f"y no hay alternativa más pequeña."
                )
            log.warning(
                "RAM insuficiente para %s (%.1f GB); cayendo a %s",
                deseado,
                coste,
                alternativa,
            )
            deseado = alternativa

        if self._modelo_cargado and self._modelo_cargado != deseado:
            await self._descargar(self._modelo_cargado)

        self._modelo_cargado = deseado
        return deseado

    async def _descargar(self, modelo: str) -> None:
        """Descarga el modelo de la RAM enviando `keep_alive=0`."""
        try:
            await self._cliente.post(
                "/api/generate",
                json={"model": modelo, "prompt": "", "keep_alive": 0},
                timeout=10.0,
            )
            log.info("Modelo %s descargado de RAM", modelo)
        except (httpx.HTTPError, httpx.TransportError) as exc:
            log.warning("No se pudo descargar %s: %s", modelo, exc)

    @staticmethod
    def _ram_libre_gb() -> float:
        """RAM libre del sistema en GB."""
        return psutil.virtual_memory().available / (1024**3)

    def _fallback_mas_pequeno(self, deseado: str, presupuesto_gb: float) -> str | None:
        """Devuelve el modelo disponible más grande que quepa en el presupuesto."""
        candidatos = [
            (m, RAM_APROXIMADA_GB.get(m, 99.0))
            for m in self._modelos_disponibles
            if m != deseado and RAM_APROXIMADA_GB.get(m, 99.0) <= presupuesto_gb
        ]
        if not candidatos:
            return None
        candidatos.sort(key=lambda c: c[1], reverse=True)
        return candidatos[0][0]


# ---------------------------------------------------------------------------
# Helpers de instalación (usado por scripts/Makefile)
# ---------------------------------------------------------------------------


# Importación diferida para evitar ciclos
try:
    from security.audit_log import AuditLog  # noqa: F401
except ImportError:
    AuditLog = None  # type: ignore[assignment,misc]


def ollama_instalado() -> bool:
    """`True` si el binario `ollama` está en el PATH."""
    return shutil.which("ollama") is not None


async def esperar_ollama(timeout_s: int = 10) -> bool:
    """Espera hasta que el servicio responda (útil tras `ollama serve`)."""
    inicio = time.monotonic()
    async with httpx.AsyncClient(base_url=settings.ollama_base_url, timeout=2.0) as c:
        while time.monotonic() - inicio < timeout_s:
            try:
                resp = await c.get("/api/tags")
                if resp.status_code == 200:
                    return True
            except (httpx.HTTPError, httpx.TransportError):
                pass
            await asyncio.sleep(0.5)
    return False
