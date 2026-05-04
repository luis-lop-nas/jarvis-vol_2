"""Operaciones seguras sobre el sistema de archivos."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path


class SistemaArchivos:
    """Operaciones de FS con restricción de raíz para evitar pisar el sistema.

    Todas las rutas se resuelven contra `raiz_permitida`. Cualquier intento
    de salir de ese subárbol lanza `PermissionError`.
    """

    def __init__(self, raiz_permitida: Path | None = None) -> None:
        self._raiz = (raiz_permitida or Path.home()).resolve()

    # ------------------------------------------------------------------
    # Lectura
    # ------------------------------------------------------------------

    async def leer(self, ruta: Path, codificacion: str = "utf-8") -> str:
        """Lee un archivo de texto."""
        objetivo = self._validar(ruta)
        return await asyncio.to_thread(objetivo.read_text, encoding=codificacion)

    async def leer_bytes(self, ruta: Path) -> bytes:
        objetivo = self._validar(ruta)
        return await asyncio.to_thread(objetivo.read_bytes)

    async def listar(self, ruta: Path, patron: str = "*") -> list[Path]:
        """Lista archivos que casen con `patron` (glob no recursivo)."""
        objetivo = self._validar(ruta)
        return await asyncio.to_thread(lambda: list(objetivo.glob(patron)))

    # ------------------------------------------------------------------
    # Escritura (potencialmente destructiva)
    # ------------------------------------------------------------------

    async def escribir(self, ruta: Path, contenido: str, codificacion: str = "utf-8") -> Path:
        """Escribe `contenido` en `ruta`, creando directorios si hace falta."""
        objetivo = self._validar(ruta)
        await asyncio.to_thread(objetivo.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(objetivo.write_text, contenido, encoding=codificacion)
        return objetivo

    async def mover(self, origen: Path, destino: Path) -> Path:
        a = self._validar(origen)
        b = self._validar(destino)
        return await asyncio.to_thread(lambda: Path(shutil.move(a, b)))

    async def copiar(self, origen: Path, destino: Path) -> Path:
        a = self._validar(origen)
        b = self._validar(destino)
        return await asyncio.to_thread(lambda: Path(shutil.copy2(a, b)))

    async def eliminar(self, ruta: Path) -> None:
        """Elimina archivo o árbol; debe ir precedido de confirmación humana."""
        objetivo = self._validar(ruta)
        if objetivo.is_dir():
            await asyncio.to_thread(shutil.rmtree, objetivo)
        else:
            await asyncio.to_thread(objetivo.unlink, missing_ok=True)

    # ------------------------------------------------------------------
    # Validación de raíz
    # ------------------------------------------------------------------

    def _validar(self, ruta: Path) -> Path:
        resuelta = ruta.expanduser().resolve()
        try:
            resuelta.relative_to(self._raiz)
        except ValueError as exc:
            raise PermissionError(
                f"Acceso fuera de la raíz permitida ({self._raiz}): {resuelta}"
            ) from exc
        return resuelta
