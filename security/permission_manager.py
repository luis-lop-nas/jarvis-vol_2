"""Gestor centralizado de permisos por herramienta para JARVIS.

Cada herramienta declara su política (riesgo, confirmación, biometría, capacidades).
PermissionManager es el único punto de decisión sobre si una herramienta puede ejecutarse.
Bloquea por defecto cualquier herramienta sin política declarada.
"""

from __future__ import annotations

import logging
import re
from enum import Enum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from security.permissions import Permission

if TYPE_CHECKING:
    from security.audit_log import AuditLog
    from security.auth import AuthManager
    from security.confirmation import ConfirmationManager
    from security.permissions import PermissionsManager

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Modelos públicos
# ---------------------------------------------------------------------------


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ToolPolicy(BaseModel):
    """Política de permisos declarada por una herramienta MCP."""

    nombre: str
    permisos_requeridos: list[Permission] = Field(default_factory=list)
    nivel_riesgo: RiskLevel
    requiere_confirmacion: bool
    requiere_biometria: bool
    puede_modificar_archivos: bool
    puede_usar_red: bool
    puede_leer_pantalla: bool
    puede_acceder_credenciales: bool
    descripcion: str = ""


class PermissionResult(BaseModel):
    """Resultado de la verificación de permisos para una herramienta."""

    permitido: bool
    motivo: str
    dry_run: bool = False
    politica: ToolPolicy | None = None


class InjectionResult(BaseModel):
    """Resultado del análisis de prompt injection sobre contenido externo."""

    es_inyeccion: bool
    confianza: float = Field(ge=0.0, le=1.0)
    patrones_detectados: list[str] = Field(default_factory=list)
    contenido_sanitizado: str


# ---------------------------------------------------------------------------
# Patrones de prompt injection — compilados una vez al importar
# ---------------------------------------------------------------------------

_PATRONES_INYECCION: list[tuple[str, re.Pattern[str]]] = [
    ("instruccion_override", re.compile(
        r"(?i)ignore\s+(?:all\s+)?(?:previous|above|prior)\s+instructions?",
        re.UNICODE,
    )),
    ("forget_previous", re.compile(
        r"(?i)forget\s+(?:everything|all)\s+(?:you\s+)?(?:were\s+)?(?:told|said|instructed)",
        re.UNICODE,
    )),
    ("new_instructions", re.compile(
        r"(?i)(?:your\s+)?new\s+instructions?\s*:",
        re.UNICODE,
    )),
    ("system_role_prefix", re.compile(
        r"(?i)\[?\s*system\s*\]?\s*:\s+",
        re.UNICODE,
    )),
    ("system_xml_tag", re.compile(
        r"<\s*system\s*>",
        re.UNICODE,
    )),
    ("role_change", re.compile(
        r"(?i)you\s+are\s+now\s+(?:a|an|the)\s+\w",
        re.UNICODE,
    )),
    ("act_as", re.compile(
        r"(?i)(?:act|behave|respond|pretend)\s+(?:as|like)\s+(?:a|an|the)\s+\w",
        re.UNICODE,
    )),
    ("reveal_prompt", re.compile(
        r"(?i)(?:print|reveal|show|expose|leak|output|repeat)\s+(?:your\s+)?(?:system\s+)?(?:prompt|instructions?|context|config)",
        re.UNICODE,
    )),
    ("exfil_credentials", re.compile(
        r"(?i)(?:send|email|post|transmit|exfiltrate?|forward)\s+(?:my\s+|the\s+|your\s+)?(?:api\s+keys?|passwords?|tokens?|secrets?|credentials?)",
        re.UNICODE,
    )),
    ("disable_safety", re.compile(
        r"(?i)(?:disable|bypass|skip|ignore|remove|turn\s+off)\s+(?:your\s+)?(?:safety|security|sandbox|filter|restriction|permission|guard|check)",
        re.UNICODE,
    )),
    ("jarvis_bypass", re.compile(
        r"(?i)without\s+(?:confirmation|permission|sandbox|auth(?:entication)?)",
        re.UNICODE,
    )),
    ("jailbreak_prefix", re.compile(
        r"(?i)(?:DAN|Developer\s+Mode|STAN|DUDE|Jailbreak)\s*:",
        re.UNICODE,
    )),
    ("token_smuggling", re.compile(
        r"(?i)(?:<!--|/\*\s*|\[\[|\{\{)\s*(?:ignore|system|instructions?)",
        re.UNICODE,
    )),
    ("hidden_unicode", re.compile(
        r"[​-‏‪-‮⁠-⁤﻿­]",
        re.UNICODE,
    )),
]


def _sanitizar(contenido: str, patrones_detectados: list[str]) -> str:
    sanitizado = contenido
    patron_map = dict(_PATRONES_INYECCION)
    for nombre in patrones_detectados:
        if nombre in patron_map:
            sanitizado = patron_map[nombre].sub("[CONTENIDO_ELIMINADO]", sanitizado)
    return sanitizado


# ---------------------------------------------------------------------------
# PermissionManager
# ---------------------------------------------------------------------------


class PermissionManager:
    """Gestor centralizado de permisos por herramienta.

    Ejemplo::
        pm = PermissionManager(auth_manager, confirmation_manager, audit_log, pm_macos)
        resultado = await pm.verificar("filesystem.eliminar", {}, session_id="abc")
        if not resultado.permitido:
            raise PermissionError(resultado.motivo)
    """

    def __init__(
        self,
        auth_manager: AuthManager | None = None,
        confirmation_manager: ConfirmationManager | None = None,
        audit_log: AuditLog | None = None,
        permissions_manager: PermissionsManager | None = None,
    ) -> None:
        self._auth = auth_manager
        self._confirmation = confirmation_manager
        self._audit = audit_log
        self._permisos_mac = permissions_manager
        self._modo_readonly = False
        self._modo_dry_run = False
        self._politicas: dict[str, ToolPolicy] = _build_default_policies()

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    async def verificar(
        self,
        nombre_herramienta: str,
        params: dict[str, object],
        session_id: str,
    ) -> PermissionResult:
        """Punto de decisión único: ¿puede ejecutarse esta herramienta?

        Args:
            nombre_herramienta: Nombre canónico, ej. ``filesystem.eliminar``.
            params: Parámetros que recibirá la herramienta (solo para contexto).
            session_id: Sesión originante.

        Returns:
            :class:`PermissionResult` con ``permitido``, ``motivo`` y flag ``dry_run``.
        """
        politica = self._politicas.get(nombre_herramienta)

        # 1. Default-deny: sin política → bloqueada
        if politica is None:
            await self._auditar("permiso_denegado", nombre_herramienta, session_id, "sin_politica")
            return PermissionResult(
                permitido=False,
                motivo=f"Herramienta sin política declarada (bloqueada por defecto): {nombre_herramienta}",
            )

        # 2. Modo read-only
        if self._modo_readonly and (politica.puede_modificar_archivos or politica.puede_acceder_credenciales):
            await self._auditar("permiso_denegado", nombre_herramienta, session_id, "modo_readonly")
            return PermissionResult(
                permitido=False,
                motivo=f"Modo solo lectura activo: '{nombre_herramienta}' requiere acceso de escritura/credenciales",
            )

        # 3. Modo dry-run: herramientas con efectos reales → simular
        if self._modo_dry_run and (
            politica.puede_modificar_archivos
            or politica.puede_usar_red
            or politica.puede_acceder_credenciales
        ):
            await self._auditar("dry_run", nombre_herramienta, session_id, "dry_run")
            return PermissionResult(
                permitido=True,
                dry_run=True,
                motivo="Modo dry-run: simulación sin efectos reales",
                politica=politica,
            )

        # 4. Verificar permisos macOS requeridos
        if self._permisos_mac and politica.permisos_requeridos:
            for permiso in politica.permisos_requeridos:
                status = self._permisos_mac.check(permiso)
                if not status.granted:
                    await self._auditar("permiso_denegado", nombre_herramienta, session_id, f"mac_{permiso.value}")
                    return PermissionResult(
                        permitido=False,
                        motivo=f"Permiso macOS no concedido: {permiso.value} — {status.how_to_grant}",
                    )

        # 5. Riesgo CRITICAL → biometría obligatoria antes de cualquier otra comprobación
        if politica.nivel_riesgo == RiskLevel.CRITICAL and self._auth:
            try:
                auth = await self._auth.authenticate(f"Acción crítica: {nombre_herramienta}")
                if not auth.success:
                    await self._auditar("permiso_denegado", nombre_herramienta, session_id, "biometria_critica_fallida")
                    return PermissionResult(
                        permitido=False,
                        motivo=f"Autenticación biométrica requerida para acción crítica: {nombre_herramienta}",
                    )
            except Exception as exc:
                log.warning("Error en autenticación biométrica (critical): %s", exc)
                return PermissionResult(
                    permitido=False,
                    motivo=f"Error de autenticación biométrica: {exc}",
                )

        # 6. Confirmación humana (incluye biometría si requiere_biometria=True)
        if politica.requiere_confirmacion and self._confirmation:
            try:
                confirmacion = await self._confirmation.request_confirmation(
                    session_id=session_id,
                    description=f"{nombre_herramienta}: {politica.descripcion}",
                    risk_level=politica.nivel_riesgo.value,
                    requires_auth=politica.requiere_biometria,
                )
                if not confirmacion.confirmed:
                    await self._auditar("permiso_denegado", nombre_herramienta, session_id, "confirmacion_denegada")
                    return PermissionResult(
                        permitido=False,
                        motivo=f"Usuario denegó la confirmación: {nombre_herramienta}",
                    )
            except Exception as exc:
                log.warning("Error al pedir confirmación: %s", exc)
                return PermissionResult(
                    permitido=False,
                    motivo=f"Error al pedir confirmación: {exc}",
                )

        elif politica.requiere_biometria and not politica.requiere_confirmacion and self._auth:
            # Biometría sin diálogo de confirmación
            try:
                auth = await self._auth.authenticate(f"Acción privilegiada: {nombre_herramienta}")
                if not auth.success:
                    await self._auditar("permiso_denegado", nombre_herramienta, session_id, "biometria_fallida")
                    return PermissionResult(
                        permitido=False,
                        motivo=f"Autenticación biométrica fallida: {nombre_herramienta}",
                    )
            except Exception as exc:
                return PermissionResult(
                    permitido=False,
                    motivo=f"Error de autenticación biométrica: {exc}",
                )

        await self._auditar("permiso_concedido", nombre_herramienta, session_id, "ok")
        return PermissionResult(
            permitido=True,
            motivo="Política verificada correctamente",
            politica=politica,
        )

    def registrar_politica(self, politica: ToolPolicy) -> None:
        """Registra o sobreescribe la política de una herramienta."""
        self._politicas[politica.nombre] = politica

    def activar_readonly(self) -> None:
        """Bloquea todas las herramientas que modifican archivos o acceden a credenciales."""
        self._modo_readonly = True

    def desactivar_readonly(self) -> None:
        self._modo_readonly = False

    def activar_dry_run(self) -> None:
        """Herramientas con efectos reales devuelven simulación en lugar de ejecutar."""
        self._modo_dry_run = True

    def desactivar_dry_run(self) -> None:
        self._modo_dry_run = False

    @property
    def readonly(self) -> bool:
        return self._modo_readonly

    @property
    def dry_run(self) -> bool:
        return self._modo_dry_run

    def politica(self, nombre: str) -> ToolPolicy | None:
        return self._politicas.get(nombre)

    def politicas(self) -> list[ToolPolicy]:
        return list(self._politicas.values())

    async def verificar_inyeccion(self, contenido: str) -> InjectionResult:
        """Detecta intentos de prompt injection en contenido leído de fuentes externas.

        Llamar antes de pasar cualquier contenido de web, PDF o archivo al modelo.

        Args:
            contenido: Texto a analizar.

        Returns:
            :class:`InjectionResult` con diagnóstico y versión sanitizada del contenido.
        """
        patrones_detectados: list[str] = []
        for nombre, patron in _PATRONES_INYECCION:
            if patron.search(contenido):
                patrones_detectados.append(nombre)

        es_inyeccion = bool(patrones_detectados)
        confianza = min(1.0, len(patrones_detectados) / 3.0) if es_inyeccion else 0.0
        sanitizado = _sanitizar(contenido, patrones_detectados) if es_inyeccion else contenido

        if es_inyeccion:
            log.warning(
                "Prompt injection detectado — patrones: %s | confianza: %.2f",
                patrones_detectados,
                confianza,
            )
            if self._audit:
                try:
                    await self._audit.log_action(
                        action_type="injection_detectada",
                        action="verificar_inyeccion",
                        details={"patrones": patrones_detectados, "confianza": confianza},
                        result="blocked",
                    )
                except Exception:
                    pass

        return InjectionResult(
            es_inyeccion=es_inyeccion,
            confianza=confianza,
            patrones_detectados=patrones_detectados,
            contenido_sanitizado=sanitizado,
        )

    # ------------------------------------------------------------------
    # Privado
    # ------------------------------------------------------------------

    async def _auditar(
        self,
        action_type: str,
        tool: str,
        session_id: str,
        result: str,
    ) -> None:
        if self._audit:
            try:
                await self._audit.log_action(
                    action_type=action_type,
                    action=tool,
                    details={"session_id": session_id},
                    result=result,
                )
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Políticas por defecto — todas las herramientas registradas
# ---------------------------------------------------------------------------


def _p(
    nombre: str,
    riesgo: RiskLevel,
    *,
    confirmacion: bool = False,
    biometria: bool = False,
    archivos: bool = False,
    red: bool = False,
    pantalla: bool = False,
    credenciales: bool = False,
    permisos: list[Permission] | None = None,
    desc: str = "",
) -> ToolPolicy:
    return ToolPolicy(
        nombre=nombre,
        nivel_riesgo=riesgo,
        requiere_confirmacion=confirmacion,
        requiere_biometria=biometria,
        puede_modificar_archivos=archivos,
        puede_usar_red=red,
        puede_leer_pantalla=pantalla,
        puede_acceder_credenciales=credenciales,
        permisos_requeridos=permisos or [],
        descripcion=desc,
    )


def _build_default_policies() -> dict[str, ToolPolicy]:
    politicas: list[ToolPolicy] = [
        # ── Filesystem ─────────────────────────────────────────────────
        _p("filesystem.leer",     RiskLevel.LOW,    desc="Lee un archivo del sandbox"),
        _p("filesystem.listar",   RiskLevel.LOW,    desc="Lista un directorio del sandbox"),
        _p("filesystem.buscar",   RiskLevel.LOW,    desc="Busca archivos por nombre"),
        _p("filesystem.escribir", RiskLevel.MEDIUM, confirmacion=True, archivos=True,
           desc="Escribe o sobreescribe un archivo"),
        _p("filesystem.mover",    RiskLevel.MEDIUM, confirmacion=True, archivos=True,
           desc="Mueve un archivo a otra ruta"),
        _p("filesystem.copiar",   RiskLevel.MEDIUM, confirmacion=True, archivos=True,
           desc="Copia un archivo a otra ruta"),
        _p("filesystem.eliminar", RiskLevel.HIGH,   confirmacion=True, archivos=True,
           desc="Elimina permanentemente un archivo o directorio"),
        # ── Browser ────────────────────────────────────────────────────
        _p("browser.abrir",       RiskLevel.LOW,    red=True,
           desc="Navega a una URL"),
        _p("browser.leer",        RiskLevel.LOW,    red=True,
           desc="Lee el contenido de la página actual"),
        _p("browser.click",       RiskLevel.MEDIUM, red=True,
           desc="Hace click en un elemento de la página"),
        _p("browser.fill",        RiskLevel.MEDIUM, red=True,
           desc="Rellena un campo de formulario"),
        _p("browser.screenshot",  RiskLevel.LOW,    pantalla=True,
           permisos=[Permission.SCREEN_RECORDING],
           desc="Captura pantalla del navegador"),
        _p("browser.ejecutar_js", RiskLevel.HIGH,   confirmacion=True, red=True,
           desc="Ejecuta JavaScript arbitrario en la página activa"),
        # ── Sistema ────────────────────────────────────────────────────
        _p("sistema.abrir_app",    RiskLevel.LOW,
           desc="Abre una aplicación macOS"),
        _p("sistema.cerrar_app",   RiskLevel.MEDIUM, confirmacion=True,
           desc="Cierra una aplicación en ejecución"),
        _p("sistema.volumen",      RiskLevel.LOW,
           desc="Ajusta el volumen del sistema"),
        _p("sistema.brillo",       RiskLevel.LOW,
           desc="Ajusta el brillo de la pantalla"),
        _p("sistema.clipboard",    RiskLevel.LOW,
           desc="Lee o escribe el portapapeles"),
        _p("sistema.notificacion", RiskLevel.LOW,
           desc="Muestra una notificación del sistema"),
        # ── Comunicaciones ─────────────────────────────────────────────
        _p("mail.leer",            RiskLevel.MEDIUM, red=True,
           desc="Lee correos del buzón"),
        _p("mail.enviar",          RiskLevel.HIGH,   confirmacion=True, red=True,
           desc="Envía un correo electrónico"),
        _p("mail.eliminar",        RiskLevel.HIGH,   confirmacion=True, red=True,
           desc="Elimina un correo permanentemente"),
        _p("imessage.leer",        RiskLevel.MEDIUM, red=True,
           permisos=[Permission.AUTOMATION],
           desc="Lee mensajes de iMessage"),
        _p("imessage.enviar",      RiskLevel.HIGH,   confirmacion=True, red=True,
           permisos=[Permission.AUTOMATION],
           desc="Envía un mensaje por iMessage"),
        _p("telegram.leer",        RiskLevel.MEDIUM, red=True,
           desc="Lee mensajes de Telegram"),
        _p("telegram.enviar",      RiskLevel.HIGH,   confirmacion=True, red=True,
           desc="Envía un mensaje por Telegram"),
        _p("whatsapp.leer",        RiskLevel.MEDIUM, red=True,
           desc="Lee mensajes de WhatsApp"),
        _p("whatsapp.enviar",      RiskLevel.HIGH,   confirmacion=True, red=True,
           desc="Envía un mensaje por WhatsApp"),
        # ── Terminal / Código ──────────────────────────────────────────
        _p("terminal.ejecutar",    RiskLevel.HIGH,   confirmacion=True, archivos=True, red=True,
           desc="Ejecuta un comando de shell en el sandbox"),
        _p("terminal.python",      RiskLevel.HIGH,   confirmacion=True, archivos=True, red=True,
           desc="Ejecuta código Python en el sandbox"),
        _p("terminal.transmitir",  RiskLevel.HIGH,   confirmacion=True, archivos=True, red=True,
           desc="Transmite un comando interactivo al terminal"),
        # ── Percepción ─────────────────────────────────────────────────
        _p("percepcion.screenshot",    RiskLevel.LOW, pantalla=True,
           permisos=[Permission.SCREEN_RECORDING],
           desc="Captura la pantalla completa"),
        _p("percepcion.accesibilidad", RiskLevel.MEDIUM,
           permisos=[Permission.ACCESSIBILITY],
           desc="Lee el árbol de accesibilidad de la UI"),
        # ── Teclado / Ratón ────────────────────────────────────────────
        _p("teclado.escribir",     RiskLevel.MEDIUM,
           permisos=[Permission.ACCESSIBILITY],
           desc="Escribe texto en la aplicación activa"),
        _p("teclado.atajo",        RiskLevel.MEDIUM,
           permisos=[Permission.ACCESSIBILITY],
           desc="Ejecuta un atajo de teclado"),
        _p("teclado.click",        RiskLevel.MEDIUM,
           permisos=[Permission.ACCESSIBILITY],
           desc="Hace click en coordenadas de pantalla"),
        _p("teclado.doble_click",  RiskLevel.MEDIUM,
           permisos=[Permission.ACCESSIBILITY],
           desc="Doble click en coordenadas de pantalla"),
        _p("teclado.scroll",       RiskLevel.LOW,
           permisos=[Permission.ACCESSIBILITY],
           desc="Desplaza la rueda del ratón"),
        # ── Memoria ────────────────────────────────────────────────────
        _p("memory.contexto",      RiskLevel.LOW,
           desc="Obtiene el contexto de memoria relevante"),
        _p("memory.buscar",        RiskLevel.LOW,
           desc="Busca en la memoria semántica o episódica"),
        _p("memory.guardar",       RiskLevel.LOW,  archivos=True,
           desc="Guarda una interacción en memoria"),
        _p("memory.workflow",      RiskLevel.LOW,
           desc="Recupera un workflow procedural"),
        _p("memory.episodio",      RiskLevel.LOW,  archivos=True,
           desc="Registra un episodio en memoria"),
        _p("memory.health",        RiskLevel.LOW,
           desc="Verifica el estado de salud de la memoria"),
    ]
    return {p.nombre: p for p in politicas}
