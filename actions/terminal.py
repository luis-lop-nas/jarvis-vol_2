"""Ejecución de comandos de shell con sandbox opcional."""

from __future__ import annotations

import asyncio
import shlex
from dataclasses import dataclass
from pathlib import Path

from config import settings


@dataclass(slots=True)
class ResultadoComando:
    """Resultado de la ejecución de un comando."""

    codigo: int
    stdout: str
    stderr: str
    comando: str

    @property
    def exito(self) -> bool:
        return self.codigo == 0


# Comandos prohibidos: nunca deben ejecutarse, ni siquiera tras confirmación.
COMANDOS_PROHIBIDOS: frozenset[str] = frozenset(
    {"rm", "dd", "mkfs", "fdisk", "shutdown", "reboot", "halt", "diskutil"}
)


class Terminal:
    """Ejecutor de comandos con timeout y validación básica."""

    def __init__(self, cwd: Path | None = None) -> None:
        self._cwd = cwd or Path.home()

    async def ejecutar(
        self,
        comando: str,
        *,
        timeout: float = 60.0,
        permitir_destructivo: bool = False,
    ) -> ResultadoComando:
        """Ejecuta `comando` en una subshell asíncrona.

        Si `settings.sandbox_enabled` está activo y el binario aparece en la
        lista negra sin `permitir_destructivo=True`, se aborta con `PermissionError`.
        """
        argv = shlex.split(comando)
        if not argv:
            raise ValueError("Comando vacío")

        if (
            settings.sandbox_enabled
            and not permitir_destructivo
            and Path(argv[0]).name in COMANDOS_PROHIBIDOS
        ):
            raise PermissionError(f"Comando bloqueado por sandbox: {argv[0]}")

        proceso = await asyncio.create_subprocess_exec(
            *argv,
            cwd=self._cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proceso.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proceso.kill()
            await proceso.wait()
            raise

        return ResultadoComando(
            codigo=proceso.returncode or 0,
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
            comando=comando,
        )
