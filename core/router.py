"""Router de modelos.

Decide qué proveedor (local / Kimi / DeepSeek) atiende cada petición en
función de tres ejes:
  1. Privacidad: ¿hay datos sensibles? -> forzar local.
  2. Complejidad: ¿requiere razonamiento profundo? -> DeepSeek-reasoner.
  3. Latencia y coste: para tareas triviales, local; para conversación
     general, Kimi por su contexto largo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from models.base import BaseModel, Mensaje
from models.deepseek import DeepSeekModel
from models.kimi import KimiModel
from models.ollama_client import OllamaModel

# ----------------------------------------------------------------------
# Listas de detección (mantener en minúsculas; se compara case-insensitive)
# ----------------------------------------------------------------------

KEYWORDS_SENSIBLES: tuple[str, ...] = (
    # Identificación personal
    "contraseña", "password", "passwd", "credencial", "credentials",
    "api[_-]?key", "secret", "token", "auth", "bearer",
    "dni", "nie", "pasaporte", "passport",
    "tarjeta", "credit card", "iban", "swift", "cvv", "cvc",
    "cuenta bancaria", "bank account",
    # Salud y datos personales
    "historia clínica", "diagnóstico", "medical record",
    "ssn", "social security",
    # Privado del usuario
    "íntimo", "privado", "confidencial", "no compartir",
    "luistghc03@gmail.com",
)

KEYWORDS_COMPLEJAS: tuple[str, ...] = (
    "analiza", "analizar", "analyze",
    "diseña", "diseñar", "design",
    "estrategia", "strategy",
    "planifica", "planificar", "plan",
    "demuestra", "demostrar", "prove",
    "razona", "razonar", "reason",
    "compara", "comparar", "compare",
    "evalúa", "evaluar", "evaluate",
    "sintetiza", "synthesize",
    "depura", "debug",
    "refactoriza", "refactor",
    "arquitectura", "architecture",
)

PATRON_SENSIBLE = re.compile(
    "|".join(KEYWORDS_SENSIBLES) + r"|"
    r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b|"  # tarjeta
    r"\b[A-Z]{2}\d{2}[A-Z0-9]{4,30}\b|"             # IBAN
    r"\b\d{8}[A-Z]\b",                              # DNI
    re.IGNORECASE,
)

PATRON_COMPLEJO = re.compile("|".join(KEYWORDS_COMPLEJAS), re.IGNORECASE)


class DecisionRouter(str, Enum):
    """Resultado del enrutado."""

    LOCAL = "local"
    KIMI = "kimi"
    DEEPSEEK = "deepseek"
    DEEPSEEK_REASONER = "deepseek_reasoner"


@dataclass(slots=True)
class ContextoRuteo:
    """Información mínima que el router necesita para decidir."""

    mensajes: list[Mensaje]
    forzar_local: bool = False
    requiere_contexto_largo: bool = False
    requiere_razonamiento: bool = False
    tokens_estimados: int = 0


class Router:
    """Selector de modelo según privacidad, complejidad y coste."""

    def __init__(
        self,
        umbral_contexto_largo: int = 32_000,
        modelos: dict[DecisionRouter, BaseModel] | None = None,
    ) -> None:
        self._umbral_contexto_largo = umbral_contexto_largo
        self._modelos: dict[DecisionRouter, BaseModel] = modelos or {}

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    def decidir(self, contexto: ContextoRuteo) -> DecisionRouter:
        """Aplica las reglas de enrutado y devuelve el destino elegido."""
        texto = self._concatenar(contexto.mensajes)

        if contexto.forzar_local or self.contiene_datos_sensibles(texto):
            return DecisionRouter.LOCAL

        if contexto.requiere_razonamiento or self._es_tarea_de_razonamiento(texto):
            return DecisionRouter.DEEPSEEK_REASONER

        if contexto.requiere_contexto_largo or contexto.tokens_estimados > self._umbral_contexto_largo:
            return DecisionRouter.KIMI

        if self._es_compleja(texto):
            return DecisionRouter.DEEPSEEK

        return DecisionRouter.LOCAL

    def obtener_modelo(self, decision: DecisionRouter) -> BaseModel:
        """Devuelve la instancia perezosa del modelo destino, creándola si hace falta."""
        if decision not in self._modelos:
            self._modelos[decision] = self._crear(decision)
        return self._modelos[decision]

    async def cerrar(self) -> None:
        """Cierra todos los clientes inicializados."""
        for modelo in self._modelos.values():
            await modelo.cerrar()

    # ------------------------------------------------------------------
    # Heurísticas
    # ------------------------------------------------------------------

    @staticmethod
    def contiene_datos_sensibles(texto: str) -> bool:
        """`True` si detecta keywords o patrones sensibles en el texto."""
        return bool(PATRON_SENSIBLE.search(texto))

    @staticmethod
    def _es_compleja(texto: str) -> bool:
        return bool(PATRON_COMPLEJO.search(texto))

    @staticmethod
    def _es_tarea_de_razonamiento(texto: str) -> bool:
        marcadores = ("demuestra", "razona paso a paso", "chain of thought", "step by step")
        bajo = texto.lower()
        return any(m in bajo for m in marcadores)

    @staticmethod
    def _concatenar(mensajes: list[Mensaje]) -> str:
        return "\n".join(m.contenido for m in mensajes)

    @staticmethod
    def _crear(decision: DecisionRouter) -> BaseModel:
        match decision:
            case DecisionRouter.LOCAL:
                return OllamaModel()
            case DecisionRouter.KIMI:
                return KimiModel()
            case DecisionRouter.DEEPSEEK:
                return DeepSeekModel("deepseek-chat")
            case DecisionRouter.DEEPSEEK_REASONER:
                return DeepSeekModel("deepseek-reasoner")
