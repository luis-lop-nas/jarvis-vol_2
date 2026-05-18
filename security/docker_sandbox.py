"""Sandbox Docker opcional para comandos DANGEROUS.

Crea un contenedor Alpine temporal con el directorio de trabajo montado
read-only y ejecuta el comando dentro. El contenedor se destruye siempre
al terminar, incluso en caso de error (fail-closed, ADR-52).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

log = logging.getLogger(__name__)

_ALPINE_IMAGE = "alpine:latest"


class DockerSandboxError(Exception):
    """Lanzado cuando el sandbox Docker falla o no está disponible.

    Ejemplo::
        try:
            stdout, stderr, rc = await sandbox.run("echo hello")
        except DockerSandboxError as e:
            print("Docker falló:", e)
    """


class DockerSandbox:
    """Ejecuta comandos DANGEROUS en un contenedor Alpine temporal.

    El directorio de trabajo se monta read-only. El contenedor se destruye
    siempre al terminar, incluso en caso de error. Sin red.

    Ejemplo::
        sandbox = DockerSandbox()
        if await sandbox.is_available():
            stdout, stderr, rc = await sandbox.run("ls -la", cwd=Path.home())
    """

    def __init__(self, image: str = _ALPINE_IMAGE) -> None:
        self._image = image
        self._available: bool | None = None

    async def is_available(self) -> bool:
        """Verifica si Docker está disponible en el sistema (resultado cacheado).

        Ejemplo::
            if await docker.is_available():
                await docker.run("ls")
        """
        if self._available is not None:
            return self._available
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "version",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=3.0)
            self._available = proc.returncode == 0
        except Exception:
            self._available = False
        return self._available

    async def run(
        self,
        command: str,
        *,
        cwd: Path | None = None,
        timeout: float = 60.0,
    ) -> tuple[str, str, int]:
        """Ejecuta un comando en un contenedor Alpine temporal.

        El contenedor se destruye siempre al terminar (finally).
        Sin acceso de red. El directorio de trabajo se monta read-only.

        Devuelve (stdout, stderr, returncode).

        Ejemplo::
            stdout, stderr, rc = await sandbox.run("echo hello", cwd=Path.home())
        """
        work_dir = str((cwd or Path.home()).resolve())
        container_name = f"jarvis-sandbox-{uuid.uuid4().hex[:8]}"

        argv = [
            "docker", "run",
            "--name", container_name,
            "--rm",
            "--network", "none",
            "--read-only",
            "--tmpfs", "/tmp",
            "-v", f"{work_dir}:/work:ro",
            "-w", "/work",
            self._image,
            "/bin/sh", "-c", command,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_b, stderr_b = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
                return (
                    stdout_b.decode(errors="replace"),
                    stderr_b.decode(errors="replace"),
                    proc.returncode or 0,
                )
            except TimeoutError:
                proc.kill()
                await proc.wait()
                raise
        except TimeoutError:
            raise DockerSandboxError(
                f"Comando superó {timeout}s en contenedor Docker"
            ) from None
        except DockerSandboxError:
            raise
        except Exception as exc:
            raise DockerSandboxError(f"Error ejecutando en Docker: {exc}") from exc
        finally:
            await self._force_remove(container_name)

    async def _force_remove(self, container_name: str) -> None:
        """Destruye el contenedor por nombre. Nunca lanza excepción."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "rm", "-f", container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except Exception:
            pass
