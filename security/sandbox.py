"""Análisis de riesgo y ejecución segura de comandos.

Todo comando que ejecute JARVIS pasa por aquí primero.
Sin excepciones — si bypaseas el sandbox, rompes la seguridad.
"""

from __future__ import annotations

import asyncio
import enum
import os
import re
import shlex
import time
from asyncio import subprocess as aio_sub
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from security.auth import AuthManager
    from security.audit_log import AuditLog
    from security.confirmation import ConfirmationManager

log = __import__("logging").getLogger(__name__)

_HOME = Path.home()
_MAX_TIMEOUT = 120.0

_SECRET_VAR_RE = re.compile(
    r"(_API_KEY|_SECRET|_TOKEN|_PASSWORD|ANTHROPIC|KIMI|DEEPSEEK|OPENROUTER|TELEGRAM)",
    re.IGNORECASE,
)


class CommandRisk(enum.Enum):
    """Nivel de riesgo de un comando."""

    SAFE = "safe"
    MODERATE = "moderate"
    DANGEROUS = "dangerous"
    BLOCKED = "blocked"


class SandboxResult(BaseModel):
    """Resultado del análisis de riesgo de un comando."""

    allowed: bool
    risk_level: CommandRisk
    reason: str
    sanitized_command: str | None = None


@dataclass(slots=True)
class CommandResult:
    """Resultado de la ejecución segura de un comando.

    Ejemplo::
        res = await sandbox.execute_safe("ls -la ~/Downloads")
        if res.exito:
            print(res.stdout)
    """

    stdout: str
    stderr: str
    codigo_retorno: int
    duracion_ms: float
    comando: str
    directorio: str

    @property
    def exito(self) -> bool:
        return self.codigo_retorno == 0


class SandboxError(Exception):
    """Lanzado cuando el sandbox bloquea o rechaza un comando.

    Ejemplo::
        try:
            await sandbox.execute_safe("rm -rf /")
        except SandboxError as e:
            print(e.risk_level, e.reason)
    """

    def __init__(
        self,
        command: str,
        reason: str,
        risk_level: CommandRisk,
        timestamp: datetime,
    ) -> None:
        super().__init__(f"[{risk_level.value.upper()}] {reason}: {command!r}")
        self.command = command
        self.reason = reason
        self.risk_level = risk_level
        self.timestamp = timestamp


# ---------------------------------------------------------------------------
# Listas de patrones de riesgo (compiladas una vez al importar)
# ---------------------------------------------------------------------------

_BLOCKED_PATTERNS: list[re.Pattern[str]] = [re.compile(p, re.IGNORECASE) for p in [
    r"rm\s+-[rf]+\s+/(?:\s|$)",          # rm -rf /
    r"rm\s+-[rf]+\s+~\s*$",             # rm -rf ~
    r"\bmkfs\b",                          # formatear disco
    r"\bdd\s+if=",                        # copia raw de disco
    r"\bchmod\s+777\s+/",               # permisos root
    r":\(\)\s*\{\s*:\s*\|",             # fork bomb
    r"curl\s+[^\|]+\|\s*(?:ba)?sh",     # ejecutar script remoto via curl
    r"wget\s+[^\|]+\|\s*(?:ba)?sh",     # ejecutar script remoto via wget
    r"\bsudo\s+rm\s+-[rf]+",            # sudo borrar recursivo
    r">\s*/dev/sd",                      # escribir a dispositivo raw
]]

_DANGEROUS_PATTERNS: list[re.Pattern[str]] = [re.compile(p, re.IGNORECASE) for p in [
    r"\bsudo\s+",                        # cualquier sudo
    r"\brm\s+(-r\s+|-[rf]{1,2}\s+)",   # borrar recursivo
    r"\bmv\s+.*\s+/dev/null",           # borrar via mv
    r"\bgit\s+push\s+--force",          # force push
    r"\bDROP\s+TABLE\b",                # SQL destructivo
    r"\bDELETE\s+FROM\b",              # SQL destructivo
]]

_MODERATE_PATTERNS: list[re.Pattern[str]] = [re.compile(p, re.IGNORECASE) for p in [
    r"\brm\s+",                          # borrar archivo
    r"\bpip\s+install\b",               # instalar paquete Python
    r"\bnpm\s+install\b",               # instalar paquete Node
    r"\bbrew\s+install\b",              # instalar con Homebrew
    r"\bssh\s+",                         # conexión SSH
]]


# ---------------------------------------------------------------------------
# Sandbox
# ---------------------------------------------------------------------------


class Sandbox:
    """Ejecutor seguro con análisis de riesgo, confirmación y auditoría.

    Ejemplo::
        sandbox = Sandbox(auth_manager=auth, confirmation_manager=confirm)
        result = await sandbox.execute_safe("pip install requests")
    """

    def __init__(
        self,
        auth_manager: AuthManager | None = None,
        confirmation_manager: ConfirmationManager | None = None,
        audit_log: AuditLog | None = None,
    ) -> None:
        self._auth = auth_manager
        self._confirm = confirmation_manager
        self._audit = audit_log

    @staticmethod
    def _normalize_command(command: str) -> str:
        """Normaliza el comando para la detección de patrones.

        Reemplaza paths absolutos a binarios por su nombre base:
        /bin/rm -rf / → rm -rf /
        """
        try:
            tokens = shlex.split(command)
            if tokens:
                tokens[0] = Path(tokens[0]).name
            return " ".join(shlex.quote(t) for t in tokens)
        except Exception:
            return command

    def check_command(self, command: str) -> SandboxResult:
        """Analiza un comando y devuelve su nivel de riesgo.

        Primero BLOCKED, luego DANGEROUS, luego MODERATE, luego SAFE.
        Normaliza el binario para evitar bypass con paths absolutos (/bin/rm).

        Ejemplo::
            result = sandbox.check_command("rm -rf /")
            # SandboxResult(allowed=False, risk_level=BLOCKED, ...)
        """
        normalized = self._normalize_command(command)
        # Verificar tanto el comando original como el normalizado
        targets = {command, normalized}

        for pattern in _BLOCKED_PATTERNS:
            if any(pattern.search(t) for t in targets):
                return SandboxResult(
                    allowed=False,
                    risk_level=CommandRisk.BLOCKED,
                    reason=f"Patrón peligroso detectado: {pattern.pattern}",
                )

        for pattern in _DANGEROUS_PATTERNS:
            if any(pattern.search(t) for t in targets):
                return SandboxResult(
                    allowed=True,
                    risk_level=CommandRisk.DANGEROUS,
                    reason=f"Comando peligroso: {pattern.pattern}",
                )

        for pattern in _MODERATE_PATTERNS:
            if any(pattern.search(t) for t in targets):
                return SandboxResult(
                    allowed=True,
                    risk_level=CommandRisk.MODERATE,
                    reason=f"Comando moderado: {pattern.pattern}",
                )

        return SandboxResult(allowed=True, risk_level=CommandRisk.SAFE, reason="Comando seguro")

    async def validate_command(self, command: str) -> CommandRisk:
        """Verifica riesgo y obtiene confirmación sin ejecutar el comando.

        Extrae la lógica de autorización de execute_safe para que rutas de
        ejecución alternativas (streaming, scripts) puedan reutilizarla.
        Raises SandboxError si BLOCKED o si la confirmación se deniega.
        Devuelve el CommandRisk resultante para que el llamador lo audite.

        Ejemplo::
            risk = await sandbox.validate_command("rm -rf ~/tmp")
            # SandboxError si bloqueado o denegado
        """
        analysis = self.check_command(command)
        now = datetime.now(timezone.utc)

        if analysis.risk_level == CommandRisk.BLOCKED:
            raise SandboxError(command, analysis.reason, CommandRisk.BLOCKED, now)

        if analysis.risk_level == CommandRisk.DANGEROUS:
            if self._confirm is None:
                raise SandboxError(
                    command,
                    "Comando peligroso requiere ConfirmationManager (no configurado)",
                    CommandRisk.DANGEROUS,
                    now,
                )
            if self._auth is not None:
                await self._auth.require_auth(f"Ejecutar comando peligroso: {command}")
            conf = await self._confirm.request_confirmation(
                action_description=f"Ejecutar: {command}",
                command=command,
                risk_level="dangerous",
                requires_auth=False,
            )
            if not conf.confirmed:
                raise SandboxError(command, "Confirmación denegada", CommandRisk.DANGEROUS, now)

        elif analysis.risk_level == CommandRisk.MODERATE:
            if self._confirm is None:
                raise SandboxError(
                    command,
                    "Comando moderado requiere ConfirmationManager (no configurado)",
                    CommandRisk.MODERATE,
                    now,
                )
            conf = await self._confirm.request_confirmation(
                action_description=f"Ejecutar: {command}",
                command=command,
                risk_level="moderate",
                requires_auth=False,
            )
            if not conf.confirmed:
                raise SandboxError(command, "Confirmación denegada", CommandRisk.MODERATE, now)

        return analysis.risk_level

    async def execute_safe(
        self,
        command: str,
        *,
        cwd: Path | None = None,
        timeout: float = 60.0,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        """Ejecuta un comando tras verificar riesgo, pedir confirmación y auditar.

        1. validate_command() — BLOCKED → SandboxError; DANGEROUS/MODERATE → confirmación
        2. ejecutar con subprocess, timeout, sin shell=True
        3. audit_log del resultado con risk_level real

        Ejemplo::
            result = await sandbox.execute_safe("git status")
        """
        risk_level = await self.validate_command(command)
        return await self._run(command, cwd=cwd, timeout=timeout, env=env, risk_level=risk_level)

    def sanitize_path(self, path: str | Path) -> Path:
        """Resuelve symlinks y verifica que la ruta esté dentro de HOME.

        Ejemplo::
            safe = sandbox.sanitize_path("~/Documents/file.txt")
        """
        p = Path(path).expanduser().resolve()
        try:
            p.relative_to(_HOME)
        except ValueError as exc:
            raise SandboxError(
                str(path),
                "Ruta fuera de HOME",
                CommandRisk.BLOCKED,
                datetime.now(timezone.utc),
            ) from exc
        return p

    def sanitize_env(self, env: dict[str, str] | None = None) -> dict[str, str]:
        """Elimina variables de entorno sensibles (API keys, tokens, passwords).

        Ejemplo::
            clean_env = sandbox.sanitize_env()  # sin KIMI_API_KEY, etc.
        """
        base = env if env is not None else dict(os.environ)
        return {k: v for k, v in base.items() if not _SECRET_VAR_RE.search(k)}

    # ------------------------------------------------------------------
    # Ejecución interna
    # ------------------------------------------------------------------

    async def _run(
        self,
        command: str,
        *,
        cwd: Path | None = None,
        timeout: float,
        env: dict[str, str] | None = None,
        risk_level: CommandRisk = CommandRisk.SAFE,
    ) -> CommandResult:
        timeout = min(timeout, _MAX_TIMEOUT)
        argv = shlex.split(command)
        if not argv:
            raise ValueError("Comando vacío")

        work_dir = str((cwd or _HOME).resolve())
        safe_env = self.sanitize_env(env)
        inicio = time.monotonic()

        proceso = await asyncio.create_subprocess_exec(
            *argv,
            stdout=aio_sub.PIPE,
            stderr=aio_sub.PIPE,
            cwd=work_dir,
            env=safe_env,
        )

        try:
            stdout_b, stderr_b = await asyncio.wait_for(proceso.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proceso.kill()
            await proceso.wait()
            raise TimeoutError(f"Comando superó {timeout}s: {argv[0]}")

        duracion_ms = (time.monotonic() - inicio) * 1000
        result = CommandResult(
            stdout=stdout_b.decode(errors="replace"),
            stderr=stderr_b.decode(errors="replace"),
            codigo_retorno=proceso.returncode or 0,
            duracion_ms=duracion_ms,
            comando=command,
            directorio=work_dir,
        )

        if self._audit is not None:
            await self._audit.log_action(
                session_id="",
                action_type="terminal",
                action="sandbox.execute",
                details={"command": command, "exit_code": result.codigo_retorno},
                result="success" if result.exito else "failed",
                risk_level=risk_level.value,
                confirmed=risk_level in (CommandRisk.DANGEROUS, CommandRisk.MODERATE),
                authenticated=risk_level == CommandRisk.DANGEROUS and self._auth is not None,
                duration_ms=round(duracion_ms),
            )

        return result
