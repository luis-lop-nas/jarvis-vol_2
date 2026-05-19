"""Ejecución de comandos de shell con sandbox y auditoría.

Toda ejecución de comandos externos pasa por este módulo.
Nunca usar subprocess directamente desde otros módulos de JARVIS.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import sys
import time
from asyncio import subprocess as aio_sub
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from pathlib import Path

from actions.filesystem import DryRunResult

_log = logging.getLogger(__name__)

_HOME = Path.home()
_MAX_TIMEOUT = 120.0

# ---------------------------------------------------------------------------
# Tipos públicos
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ResultadoComando:
    """Resultado de la ejecución de un comando externo.

    Ejemplo::
        res = await terminal.ejecutar_comando("ls -la")
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
        """True si el proceso terminó con código 0."""
        return self.codigo_retorno == 0


# ---------------------------------------------------------------------------
# Clasificación de comandos
# ---------------------------------------------------------------------------

# Nunca se ejecutan, sin excepción
_BLOQUEADOS: frozenset[str] = frozenset({
    "mkfs", "fdisk", "dd", "halt", "poweroff", "shutdown", "reboot",
    "chmod",   # bloqueado en combinación peligrosa — se filtra en _analizar
    "chown",
    ":(){ :|:& };:",   # fork bomb
})

# Requieren confirmación explícita antes de ejecutar
_REQUIEREN_CONFIRMACION: frozenset[str] = frozenset({
    "rm", "sudo", "pip", "pip3", "npm", "yarn", "pnpm",
    "curl", "wget", "brew", "gem", "cargo",
})

# Siempre permitidos sin confirmación
_PERMITIDOS: frozenset[str] = frozenset({
    "python", "python3", "pytest", "make", "git", "ls", "cat", "grep",
    "find", "echo", "pwd", "which", "env", "rg", "fd", "bat", "head",
    "tail", "wc", "sort", "uniq", "cut", "awk", "sed", "diff", "patch",
    "uv", "ruff", "mypy", "black", "isort",
})

# Subcomandos de git que siempre requieren confirmación
_GIT_CONFIRMACION: frozenset[str] = frozenset({
    "push", "reset", "clean", "checkout", "switch", "branch",
})

CallbackConfirmacion = Callable[[str], "asyncio.Future[bool]"]


async def _denegar(_: str) -> bool:
    return False


# ---------------------------------------------------------------------------
# Terminal
# ---------------------------------------------------------------------------


class Terminal:
    """Ejecutor seguro de comandos con sandbox, timeout y log de auditoría.

    Ejemplo::
        terminal = Terminal()
        res = await terminal.ejecutar_comando("pytest tests/ -q")
        print(res.stdout)
    """

    def __init__(
        self,
        directorio_trabajo: Path | None = None,
        *,
        callback_confirmacion: CallbackConfirmacion | None = None,
        audit_log: AuditLog | None = None,
        sandbox_habilitado: bool = True,
        sandbox: Sandbox | None = None,
    ) -> None:
        self._cwd = (directorio_trabajo or _HOME).resolve()
        self._confirmar = callback_confirmacion or _denegar
        self._audit = audit_log
        self._sandbox_enabled = sandbox_habilitado
        self._sandbox = sandbox_habilitado  # mantiene compat con código interno
        self._security_sandbox = sandbox
        self._procesos_activos: dict[int, asyncio.subprocess.Process] = {}

    # ------------------------------------------------------------------
    # API pública
    # ------------------------------------------------------------------

    async def ejecutar_comando(
        self,
        comando: str,
        *,
        timeout: float = 60.0,
        directorio: Path | None = None,
        env_extra: dict[str, str] | None = None,
        dry_run: bool = False,
    ) -> ResultadoComando | DryRunResult:
        """Ejecuta un comando de shell y devuelve el resultado.

        Si se inyectó un Sandbox de seguridad, delega en él (verifica riesgo + auth).
        Con dry_run=True devuelve DryRunResult sin ejecutar el comando.

        Ejemplo::
            res = await terminal.ejecutar_comando("git status", timeout=10)
        """
        argv = self._parsear(comando)
        binario = Path(argv[0]).name

        if dry_run:
            necesita_confirmacion = self._sandbox and (
                binario in _REQUIEREN_CONFIRMACION
                or binario in _BLOQUEADOS
                or (binario == "git" and len(argv) > 1 and argv[1] in _GIT_CONFIRMACION)
            )
            return DryRunResult(
                accion="terminal.ejecutar_comando",
                descripcion=f"Ejecutar: {comando}",
                efecto_esperado=(
                    "Comando bloqueado — no se ejecutaría"
                    if binario in _BLOQUEADOS
                    else f"Se ejecutaría '{binario}' con sus efectos asociados"
                    + (" (requiere confirmación)" if necesita_confirmacion else "")
                ),
            )

        if self._security_sandbox is not None:
            cmd_result = await self._security_sandbox.execute_safe(
                comando,
                cwd=directorio,
                timeout=timeout,
                env=env_extra,
            )
            resultado = ResultadoComando(
                stdout=cmd_result.stdout,
                stderr=cmd_result.stderr,
                codigo_retorno=cmd_result.codigo_retorno,
                duracion_ms=cmd_result.duracion_ms,
                comando=cmd_result.comando,
                directorio=cmd_result.directorio,
            )
        else:
            await self._verificar_permiso(argv, comando)
            resultado = await self._ejecutar(argv, timeout=timeout, directorio=directorio, env_extra=env_extra)

        if not resultado.exito and resultado.stderr:
            _log.warning("Comando '%s' terminó con código %d: %s", argv[0], resultado.codigo_retorno, resultado.stderr[:300])

        return resultado

    async def ejecutar_script(
        self,
        ruta_script: Path,
        args: list[str] | None = None,
        *,
        timeout: float = 60.0,
    ) -> ResultadoComando:
        """Ejecuta un script de shell o Python.

        Ejemplo::
            res = await terminal.ejecutar_script(Path("~/scripts/backup.sh"))
        """
        script = ruta_script.expanduser().resolve()
        if not script.exists():
            raise FileNotFoundError(f"Script no encontrado: {script}")

        if script.suffix == ".py":
            argv = [sys.executable, str(script)] + (args or [])
        else:
            argv = [str(script)] + (args or [])

        if self._security_sandbox is not None:
            cmd_str = " ".join(shlex.quote(a) for a in argv)
            await self._security_sandbox.validate_command(cmd_str)

        await self._audit_log("ejecutar_script", {"script": str(script)})
        return await self._ejecutar(argv, timeout=timeout)

    async def ejecutar_python(self, codigo: str, *, timeout: float = 30.0) -> ResultadoComando:
        """Ejecuta código Python en un subproceso aislado.

        Ejemplo::
            res = await terminal.ejecutar_python("print(2 + 2)")
            # res.stdout == "4\n"
        """
        aprobado = await self._confirmar(f"Ejecutar código Python:\n{codigo[:200]}")
        if not aprobado:
            raise PermissionError("Ejecución de código Python no confirmada")

        argv = [sys.executable, "-c", codigo]
        await self._audit_log("ejecutar_python", {"bytes": len(codigo)})
        return await self._ejecutar(argv, timeout=timeout)

    async def transmitir_comando(
        self,
        comando: str,
        *,
        timeout: float = 60.0,
    ) -> AsyncGenerator[str, None]:
        """Ejecuta un comando y transmite su stdout línea a línea.

        Ejemplo::
            async for linea in terminal.transmitir_comando("tail -f /var/log/system.log"):
                print(linea)
        """
        argv = self._parsear(comando)
        if self._security_sandbox is not None:
            await self._security_sandbox.validate_command(comando)
        else:
            await self._verificar_permiso(argv, comando)

        cwd_str = str(self._cwd)
        env = self._construir_env()

        proceso = await asyncio.create_subprocess_exec(
            *argv,
            stdout=aio_sub.PIPE,
            stderr=aio_sub.STDOUT,
            cwd=cwd_str,
            env=env,
        )
        self._procesos_activos[proceso.pid or 0] = proceso

        try:
            assert proceso.stdout is not None
            deadline = time.monotonic() + timeout
            async for linea in proceso.stdout:
                if time.monotonic() > deadline:
                    proceso.kill()
                    break
                yield linea.decode(errors="replace").rstrip("\n")
        finally:
            self._procesos_activos.pop(proceso.pid or 0, None)
            try:
                await asyncio.wait_for(proceso.wait(), timeout=5.0)
            except TimeoutError:
                proceso.kill()

    async def matar_proceso(self, pid: int) -> bool:
        """Termina un proceso por PID.

        Ejemplo::
            ok = await terminal.matar_proceso(12345)
        """
        if pid in self._procesos_activos:
            self._procesos_activos[pid].kill()
            await self._audit_log("matar_proceso", {"pid": pid})
            return True

        try:
            import signal
            os.kill(pid, signal.SIGTERM)
            await self._audit_log("matar_proceso", {"pid": pid, "externo": True})
            return True
        except ProcessLookupError:
            return False

    # ------------------------------------------------------------------
    # Validación y helpers internos
    # ------------------------------------------------------------------

    def _parsear(self, comando: str) -> list[str]:
        argv = shlex.split(comando)
        if not argv:
            raise ValueError("Comando vacío")
        return argv

    async def _verificar_permiso(self, argv: list[str], comando_raw: str) -> None:
        binario = Path(argv[0]).name

        if self._sandbox:
            # Comandos siempre bloqueados
            if binario in _BLOQUEADOS:
                raise PermissionError(f"Comando bloqueado por sandbox: {binario}")

            # Detectar rm -rf /
            if binario == "rm" and ("-rf" in argv or "-fr" in argv):
                for arg in argv[2:]:
                    if arg in ("/", str(_HOME)):
                        raise PermissionError(f"Destrucción del sistema bloqueada: {comando_raw}")

            # chmod 777 / — bloquear
            if binario == "chmod" and "777" in argv:
                raise PermissionError(f"chmod 777 bloqueado: {comando_raw}")

            # git push --force bloqueado
            if binario == "git" and len(argv) > 1:
                sub = argv[1]
                if sub in _GIT_CONFIRMACION:
                    if "--force" in argv or "-f" in argv:
                        aprobado = await self._confirmar(f"git {sub} --force: {comando_raw}")
                        if not aprobado:
                            raise PermissionError("git push --force no confirmado")
                    elif sub == "push":
                        aprobado = await self._confirmar(f"git push: {comando_raw}")
                        if not aprobado:
                            raise PermissionError("git push no confirmado")

            # curl | bash — peligro de ejecución remota
            if (
                "|" in comando_raw
                and ("bash" in comando_raw or "sh" in comando_raw)
                and ("curl" in comando_raw or "wget" in comando_raw)
            ):
                raise PermissionError(f"curl|bash bloqueado: {comando_raw}")

            # Requieren confirmación
            if binario in _REQUIEREN_CONFIRMACION:
                aprobado = await self._confirmar(f"Ejecutar: {comando_raw}")
                if not aprobado:
                    raise PermissionError(f"Comando '{binario}' no confirmado")

        await self._audit_log("ejecutar_comando", {"comando": comando_raw})

    async def _ejecutar(
        self,
        argv: list[str],
        *,
        timeout: float,
        directorio: Path | None = None,
        env_extra: dict[str, str] | None = None,
    ) -> ResultadoComando:
        timeout = min(timeout, _MAX_TIMEOUT)
        cwd = str((directorio or self._cwd).resolve())
        env = self._construir_env(env_extra)

        inicio = time.monotonic()
        proceso = await asyncio.create_subprocess_exec(
            *argv,
            stdout=aio_sub.PIPE,
            stderr=aio_sub.PIPE,
            cwd=cwd,
            env=env,
        )
        self._procesos_activos[proceso.pid or 0] = proceso

        try:
            stdout_b, stderr_b = await asyncio.wait_for(proceso.communicate(), timeout=timeout)
        except TimeoutError:
            proceso.kill()
            await proceso.wait()
            self._procesos_activos.pop(proceso.pid or 0, None)
            raise TimeoutError(f"Comando superó el timeout de {timeout}s: {argv[0]}") from None
        finally:
            self._procesos_activos.pop(proceso.pid or 0, None)

        duracion_ms = (time.monotonic() - inicio) * 1000
        return ResultadoComando(
            stdout=stdout_b.decode(errors="replace"),
            stderr=stderr_b.decode(errors="replace"),
            codigo_retorno=proceso.returncode or 0,
            duracion_ms=duracion_ms,
            comando=" ".join(argv),
            directorio=cwd,
        )

    def _construir_env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        """Construye el entorno del subproceso sin filtrar secrets del sistema."""
        # Solo pasar variables seguras — nunca keys de API del proceso padre
        secretos_filtrar = {
            "KIMI_API_KEY", "DEEPSEEK_API_KEY", "OPENROUTER_API_KEY",
            "TELEGRAM_TOKEN", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
        }
        # Filtrar también cualquier variable cuyo nombre contenga patrones de secret
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in secretos_filtrar
            and not any(pat in k.upper() for pat in ("_API_KEY", "_SECRET", "_TOKEN", "_PASSWORD"))
        }
        if extra:
            env.update(extra)
        return env

    async def _audit_log(self, evento: str, datos: dict) -> None:
        if self._audit is not None:
            await self._audit.registrar(evento, datos)


# Importaciones diferidas para evitar ciclo
try:
    from security.audit_log import AuditLog  # noqa: F401
except ImportError:
    AuditLog = None  # type: ignore[assignment,misc]

try:
    from security.sandbox import Sandbox  # noqa: F401
except ImportError:
    Sandbox = None  # type: ignore[assignment,misc]
