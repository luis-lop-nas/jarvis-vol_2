"""Router de modelos: decide qué proveedor atiende cada petición.

Reglas en orden de prioridad (cortocircuito en cuanto una se cumple):
1. Datos sensibles detectados → local (siempre, sin excepción).
2. Sin internet → local.
3. Necesita visión → Kimi (`KIMI_MODEL_DEFAULT`).
4. Tarea compleja + código → Kimi.
5. Embeddings / clasificación → local (`OLLAMA_MODEL_EMBED`).
6. Tarea media o conversacional → DeepSeek (`DEEPSEEK_MODEL_DEFAULT`).
7. Default → DeepSeek.

Cada decisión se loggea (si `ROUTER_LOG_DECISIONS=true`) con:
tarea resumida, modelo elegido, razón y tiempo de la decisión.
"""

from __future__ import annotations

import logging
import re
import socket
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

from config import settings
from models.base import BaseModel, Mensaje
from models.deepseek import DeepSeekModel
from models.kimi import KimiModel
from models.ollama_client import OllamaModel
from models.openrouter import OpenRouterModel

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Listas de keywords (case-insensitive)
# ---------------------------------------------------------------------------

PRIVACIDAD_KEYWORDS: tuple[str, ...] = (
    "contraseña", "password", "token", "api_key", "secret",
    "credencial", "dni", "tarjeta", "cuenta", "banco",
    "privado", "confidencial", "1password", "keychain",
)

COMPLEJIDAD_ALTA: tuple[str, ...] = (
    "programa", "implementa", "diseña", "arquitectura",
    "refactoriza", "depura", "analiza", "planifica",
    "investiga", "crea", "optimiza",
)

VISION_KEYWORDS: tuple[str, ...] = (
    "pantalla", "screenshot", "imagen", "mira", "ve",
    "qué hay", "qué ves", "captura",
)

EMBEDDING_KEYWORDS: tuple[str, ...] = (
    "clasifica", "clasificar", "embedding", "vectoriza",
    "similitud semántica", "categoriza",
)

CODIGO_KEYWORDS: tuple[str, ...] = (
    "código", "codigo", "función", "funcion", "clase",
    "python", "typescript", "javascript", "bug", "tests",
    "pytest", "deploy", "compilar",
)

# Patrones estructurales: DNI español, IBAN, tarjeta de crédito, env vars, paths a secretos.
PATRON_DNI = re.compile(r"\b\d{8}[A-Z]\b")
PATRON_IBAN = re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{4,30}\b")
PATRON_TARJETA = re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b")
PATRON_ENV_SECRETO = re.compile(r"\b[A-Z][A-Z0-9_]*(?:_KEY|_SECRET|_TOKEN|_PASSWORD)\b")
PATRON_RUTA_SECRETO = re.compile(r"\.env|\.ssh/|/\.aws/|Keychain", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Decisiones y selección
# ---------------------------------------------------------------------------


class ModeloDestino(str, Enum):
    """Identificadores lógicos de destinos de enrutado."""

    LOCAL_DEFAULT = "local_default"
    LOCAL_CODE = "local_code"
    LOCAL_REASONING = "local_reasoning"
    LOCAL_EMBED = "local_embed"
    KIMI = "kimi"
    KIMI_THINKING = "kimi_thinking"
    DEEPSEEK = "deepseek"
    DEEPSEEK_REASONER = "deepseek_reasoner"
    OPENROUTER = "openrouter"


@dataclass(slots=True)
class ContextoRuteo:
    """Información necesaria para tomar una decisión de routing."""

    mensajes: list[Mensaje]
    nombres_archivos: list[str] = field(default_factory=list)
    historial: list[Mensaje] = field(default_factory=list)
    forzar_local: bool = False
    sin_internet: bool | None = None  # None = autodetectar


@dataclass(slots=True)
class ModelSelection:
    """Resultado del enrutado: modelo principal + cadena de fallback."""

    model_name: ModeloDestino
    razon: str
    fallback_chain: list[ModeloDestino] = field(default_factory=list)
    complejidad: float = 0.0
    decision_ms: float = 0.0


# ---------------------------------------------------------------------------
# ModelRouter
# ---------------------------------------------------------------------------


class ModelRouter:
    """Selector determinista de modelos según privacidad y complejidad."""

    def __init__(
        self,
        clientes: dict[ModeloDestino, BaseModel] | None = None,
        chequeo_internet_ttl_s: float = 30.0,
    ) -> None:
        self._clientes: dict[ModeloDestino, BaseModel] = clientes or {}
        self._cache_internet: tuple[float, bool] | None = None
        self._chequeo_internet_ttl = chequeo_internet_ttl_s

    # ------------------------------------------------------------------
    # Entrada principal
    # ------------------------------------------------------------------

    def route(self, tarea: str, contexto: ContextoRuteo | None = None) -> ModelSelection:
        """Aplica las reglas y devuelve la selección con fallback."""
        inicio = time.perf_counter()
        contexto = contexto or ContextoRuteo(mensajes=[Mensaje(rol="user", contenido=tarea)])

        complejidad = self.estimate_complexity(tarea)

        destino, razon = self._aplicar_reglas(tarea, contexto, complejidad)
        fallback = self._fallback_para(destino) if settings.router_fallback_enabled else []
        decision_ms = (time.perf_counter() - inicio) * 1000

        seleccion = ModelSelection(
            model_name=destino,
            razon=razon,
            fallback_chain=fallback,
            complejidad=complejidad,
            decision_ms=decision_ms,
        )

        if settings.router_log_decisions:
            resumen = (tarea[:80] + "…") if len(tarea) > 80 else tarea
            log.info(
                "ROUTE %-20s razón='%s' complejidad=%.2f decisión=%.2fms tarea=%r",
                destino.value,
                razon,
                complejidad,
                decision_ms,
                resumen,
            )
        return seleccion

    # ------------------------------------------------------------------
    # Reglas
    # ------------------------------------------------------------------

    def _aplicar_reglas(
        self,
        tarea: str,
        contexto: ContextoRuteo,
        complejidad: float,
    ) -> tuple[ModeloDestino, str]:
        if contexto.forzar_local or settings.router_prefer_local:
            return ModeloDestino.LOCAL_DEFAULT, "preferencia_local"

        if self.detect_sensitive_data(tarea, contexto):
            return ModeloDestino.LOCAL_DEFAULT, "datos_sensibles"

        sin_red = contexto.sin_internet
        if sin_red is None:
            sin_red = not self._hay_internet()
        if sin_red:
            return ModeloDestino.LOCAL_DEFAULT, "sin_internet"

        if self._coincide(tarea, VISION_KEYWORDS) or any(
            m.imagenes_base64 for m in contexto.mensajes
        ):
            return ModeloDestino.KIMI, "vision_requerida"

        es_codigo = self._coincide(tarea, CODIGO_KEYWORDS)
        es_complejo = complejidad >= 0.6 or self._coincide(tarea, COMPLEJIDAD_ALTA)

        if es_codigo and es_complejo:
            return ModeloDestino.KIMI, "tarea_compleja_codigo"

        if self._coincide(tarea, EMBEDDING_KEYWORDS):
            return ModeloDestino.LOCAL_EMBED, "embeddings_clasificacion"

        if es_complejo:
            return ModeloDestino.DEEPSEEK_REASONER, "razonamiento_profundo"

        return ModeloDestino.DEEPSEEK, "default_conversacional"

    # ------------------------------------------------------------------
    # detect_sensitive_data
    # ------------------------------------------------------------------

    def detect_sensitive_data(self, texto: str, contexto: ContextoRuteo) -> bool:
        """Escanea texto + nombres de archivos + historial reciente + variables de entorno."""
        if self._contiene_sensible(texto):
            return True
        for nombre in contexto.nombres_archivos:
            if PATRON_RUTA_SECRETO.search(nombre):
                return True
        for mensaje in contexto.historial[-6:]:
            if self._contiene_sensible(mensaje.contenido):
                return True
        return False

    @staticmethod
    def _contiene_sensible(texto: str) -> bool:
        bajo = texto.lower()
        if any(kw in bajo for kw in PRIVACIDAD_KEYWORDS):
            return True
        return bool(
            PATRON_DNI.search(texto)
            or PATRON_IBAN.search(texto)
            or PATRON_TARJETA.search(texto)
            or PATRON_ENV_SECRETO.search(texto)
            or PATRON_RUTA_SECRETO.search(texto)
        )

    # ------------------------------------------------------------------
    # estimate_complexity
    # ------------------------------------------------------------------

    @classmethod
    def estimate_complexity(cls, tarea: str) -> float:
        """Heurística determinista en [0, 1]."""
        if not tarea.strip():
            return 0.0
        bajo = tarea.lower()

        # Longitud (escala suave hasta 1500 caracteres ≈ 1.0)
        longitud = min(len(tarea) / 1500, 1.0)

        # Keywords de complejidad alta
        hits_keywords = sum(1 for kw in COMPLEJIDAD_ALTA if kw in bajo)
        keywords = min(hits_keywords / 4, 1.0)

        # Marcadores de pasos múltiples ("y", "luego", "después", listas numeradas).
        pasos = (
            bajo.count(" y ")
            + bajo.count(" luego")
            + bajo.count(" después")
            + bajo.count(" then ")
            + len(re.findall(r"\b\d+[\).]", tarea))
        )
        pasos_norm = min(pasos / 6, 1.0)

        # Fórmula ponderada
        complejidad = 0.45 * keywords + 0.35 * pasos_norm + 0.20 * longitud
        return round(min(complejidad, 1.0), 3)

    # ------------------------------------------------------------------
    # Fallback chain
    # ------------------------------------------------------------------

    @staticmethod
    def _fallback_para(destino: ModeloDestino) -> list[ModeloDestino]:
        match destino:
            case ModeloDestino.KIMI | ModeloDestino.KIMI_THINKING:
                return [
                    ModeloDestino.DEEPSEEK,
                    ModeloDestino.OPENROUTER,
                    ModeloDestino.LOCAL_DEFAULT,
                ]
            case ModeloDestino.DEEPSEEK | ModeloDestino.DEEPSEEK_REASONER:
                return [
                    ModeloDestino.KIMI,
                    ModeloDestino.OPENROUTER,
                    ModeloDestino.LOCAL_DEFAULT,
                ]
            case ModeloDestino.OPENROUTER:
                return [ModeloDestino.LOCAL_DEFAULT]
            case ModeloDestino.LOCAL_DEFAULT:
                return [ModeloDestino.LOCAL_REASONING]
            case ModeloDestino.LOCAL_CODE:
                return [ModeloDestino.LOCAL_DEFAULT]
            case ModeloDestino.LOCAL_REASONING:
                return [ModeloDestino.LOCAL_DEFAULT]
            case ModeloDestino.LOCAL_EMBED:
                return []
        return []

    # ------------------------------------------------------------------
    # Cliente para un destino (perezoso)
    # ------------------------------------------------------------------

    def obtener_cliente(self, destino: ModeloDestino) -> BaseModel:
        """Devuelve la instancia del cliente; la crea perezosamente."""
        if destino in self._clientes:
            return self._clientes[destino]
        cliente = self._construir_cliente(destino)
        self._clientes[destino] = cliente
        return cliente

    @staticmethod
    def _construir_cliente(destino: ModeloDestino) -> BaseModel:
        match destino:
            case ModeloDestino.KIMI:
                return KimiModel()
            case ModeloDestino.KIMI_THINKING:
                return KimiModel(modelo=settings.kimi_model_thinking)
            case ModeloDestino.DEEPSEEK:
                return DeepSeekModel()
            case ModeloDestino.DEEPSEEK_REASONER:
                return DeepSeekModel(modelo=settings.deepseek_model_reasoner)
            case ModeloDestino.OPENROUTER:
                return OpenRouterModel()
            case ModeloDestino.LOCAL_DEFAULT:
                return OllamaModel(modelo=settings.ollama_model_default)
            case ModeloDestino.LOCAL_CODE:
                return OllamaModel(modelo=settings.ollama_model_code)
            case ModeloDestino.LOCAL_REASONING:
                return OllamaModel(modelo=settings.ollama_model_reasoning)
            case ModeloDestino.LOCAL_EMBED:
                return OllamaModel(modelo=settings.ollama_model_embed)
        raise ValueError(f"Destino desconocido: {destino}")

    async def cerrar(self) -> None:
        for cliente in self._clientes.values():
            await cliente.cerrar()

    # ------------------------------------------------------------------
    # Internet
    # ------------------------------------------------------------------

    def _hay_internet(self) -> bool:
        if self._cache_internet is not None:
            ts, valor = self._cache_internet
            if time.monotonic() - ts < self._chequeo_internet_ttl:
                return valor
        valor = _socket_alcanza("1.1.1.1", 53, timeout=1.0)
        self._cache_internet = (time.monotonic(), valor)
        return valor

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _coincide(texto: str, palabras: Iterable[str]) -> bool:
        bajo = texto.lower()
        return any(kw in bajo for kw in palabras)


def _socket_alcanza(host: str, puerto: int, timeout: float) -> bool:
    """`True` si se puede abrir un socket TCP al host:puerto en `timeout` s."""
    try:
        with socket.create_connection((host, puerto), timeout=timeout):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Aliases retro-compatibles
# ---------------------------------------------------------------------------

# Mantenemos `Router` y `DecisionRouter` como aliases para no romper imports
# antiguos en core/agent.py y main.py mientras se migra el resto del sistema.
Router = ModelRouter
DecisionRouter = ModeloDestino


__all__: list[str] = [
    "COMPLEJIDAD_ALTA",
    "CODIGO_KEYWORDS",
    "ContextoRuteo",
    "DecisionRouter",
    "EMBEDDING_KEYWORDS",
    "ModelRouter",
    "ModelSelection",
    "ModeloDestino",
    "PRIVACIDAD_KEYWORDS",
    "Router",
    "VISION_KEYWORDS",
]


# Conveniencia: cuando se necesita un destino por defecto sin instanciar el router.
def destino_por_defecto() -> ModeloDestino:
    """Destino que usa main.py al arrancar (warmup)."""
    return ModeloDestino.LOCAL_DEFAULT if settings.router_prefer_local else ModeloDestino.DEEPSEEK


# Helper Any-typed para evitar import de Any en módulos que solo necesitan el router.
_ = Any
