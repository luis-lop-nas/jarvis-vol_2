"""Control del sistema operativo: apps, ventanas, notificaciones."""

from __future__ import annotations

import asyncio
import subprocess


class ControlSistema:
    """Acciones de alto nivel sobre macOS (apps, AppleScript, notificaciones)."""

    async def abrir_app(self, nombre_o_bundle: str) -> None:
        """Abre la app por nombre (`Safari`) o bundle id (`com.apple.Safari`)."""
        if "." in nombre_o_bundle:
            await self._ejecutar(["open", "-b", nombre_o_bundle])
        else:
            await self._ejecutar(["open", "-a", nombre_o_bundle])

    async def cerrar_app(self, nombre: str) -> None:
        """Cierra una app limpiamente vía AppleScript."""
        await self.ejecutar_applescript(f'tell application "{nombre}" to quit')

    async def activar_app(self, nombre: str) -> None:
        """Pone una app en primer plano."""
        await self.ejecutar_applescript(f'tell application "{nombre}" to activate')

    async def notificar(self, titulo: str, mensaje: str, sonido: bool = False) -> None:
        """Envía una notificación nativa de macOS."""
        sonido_clausula = ' sound name "default"' if sonido else ""
        script = (
            f'display notification "{self._escapar(mensaje)}" '
            f'with title "{self._escapar(titulo)}"{sonido_clausula}'
        )
        await self.ejecutar_applescript(script)

    async def ejecutar_applescript(self, script: str) -> str:
        """Ejecuta AppleScript y devuelve su salida estándar."""
        proceso = await asyncio.create_subprocess_exec(
            "osascript",
            "-e",
            script,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        salida, error = await proceso.communicate()
        if proceso.returncode != 0:
            raise RuntimeError(f"AppleScript falló: {error.decode()}")
        return salida.decode().strip()

    async def bloquear_pantalla(self) -> None:
        """Bloquea la pantalla."""
        await self.ejecutar_applescript(
            'tell application "System Events" to keystroke "q" '
            "using {control down, command down}"
        )

    async def _ejecutar(self, argv: list[str]) -> None:
        proceso = await asyncio.create_subprocess_exec(*argv)
        await proceso.wait()

    @staticmethod
    def _escapar(texto: str) -> str:
        return texto.replace("\\", "\\\\").replace('"', '\\"')
