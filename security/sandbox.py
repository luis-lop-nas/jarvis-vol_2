"""Sandbox para ejecución acotada de comandos y código generado."""

from __future__ import annotations

import os
from pathlib import Path


class Sandbox:
    """Define qué rutas son escribibles y qué binarios pueden ejecutarse.

    Esta es una primera capa declarativa; la aplicación real de las
    restricciones la hacen las clases que consumen el sandbox (Terminal,
    SistemaArchivos, etc.).
    """

    def __init__(
        self,
        rutas_lectura: list[Path] | None = None,
        rutas_escritura: list[Path] | None = None,
        binarios_permitidos: set[str] | None = None,
        max_memoria_mb: int = 1024,
        max_segundos: int = 60,
    ) -> None:
        self.rutas_lectura: list[Path] = [
            p.expanduser().resolve() for p in (rutas_lectura or [Path.home()])
        ]
        self.rutas_escritura: list[Path] = [
            p.expanduser().resolve()
            for p in (rutas_escritura or [Path.home() / "Documents", Path.cwd() / "data"])
        ]
        self.binarios_permitidos = binarios_permitidos or {
            "ls", "cat", "grep", "find", "echo", "git", "python", "python3",
            "pip", "uv", "node", "npm", "open", "osascript",
        }
        self.max_memoria_mb = max_memoria_mb
        self.max_segundos = max_segundos

    def puede_leer(self, ruta: Path) -> bool:
        ruta_resuelta = ruta.expanduser().resolve()
        return any(ruta_resuelta.is_relative_to(r) for r in self.rutas_lectura)

    def puede_escribir(self, ruta: Path) -> bool:
        ruta_resuelta = ruta.expanduser().resolve()
        return any(ruta_resuelta.is_relative_to(r) for r in self.rutas_escritura)

    def binario_permitido(self, ejecutable: str) -> bool:
        return os.path.basename(ejecutable) in self.binarios_permitidos
