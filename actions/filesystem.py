"""Operaciones seguras sobre el sistema de archivos.

Toda operación de fichero en JARVIS pasa por este módulo.
Nunca acceder directamente al FS desde otros módulos.
"""

from __future__ import annotations

import asyncio
import mimetypes
import re
import shutil
from asyncio import Task
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_HOME = Path.home()

# ---------------------------------------------------------------------------
# Tipos públicos
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class InfoArchivo:
    """Metadatos de un archivo o directorio.

    Ejemplo::
        info = await fs.obtener_info(Path("~/Downloads/factura.pdf"))
        print(info.categoria)  # "admin"
    """

    ruta: Path
    nombre: str
    extension: str
    tamaño_bytes: int
    creado_en: datetime
    modificado_en: datetime
    es_directorio: bool
    es_oculto: bool
    mime_type: str


@dataclass(slots=True)
class PropuestaMover:
    """Propuesta de mover un archivo a una ubicación más apropiada.

    Ejemplo::
        propuesta = await fs.organizar_archivo(info)
        if user_confirma:
            await fs.mover_archivo(propuesta.origen, propuesta.destino)
    """

    origen: Path
    destino: Path
    categoria: str
    razon: str


# ---------------------------------------------------------------------------
# Callback de confirmación — inyectable, por defecto fail-closed
# ---------------------------------------------------------------------------

CallbackConfirmacion = Callable[[str], Awaitable[bool]]


async def _denegar(_descripcion: str) -> bool:
    return False


# ---------------------------------------------------------------------------
# Palabras clave para clasificación de PDFs
# ---------------------------------------------------------------------------

_KW_FISICA = re.compile(
    r"(f[ií]sica|mec[aá]nica|[oó]ptica|termodin[aá]mica|electromagnetismo"
    r"|cu[aá]ntica|relatividad|ondas|campo|vector|tensor|hamiltoniano"
    r"|lagrangiano|fourier|maxwell|schr[oö]dinger|dirac|newton|lagrange"
    r"|electrost[aá]tica|magnetismo|potencial|energ[ií]a|fuerza|momento"
    r"|matem[aá]ticas|c[aá]lculo|[aá]lgebra|geometr[ií]a|an[aá]lisis"
    r"|probabilidad|estad[ií]stica|diferencial|integral|topolog[ií]a)",
    re.IGNORECASE,
)

_KW_FACTURA = re.compile(
    r"(factura|recibo|ticket|albar[aá]n|pedido|pago|importe|iva|total"
    r"|invoice|receipt|billing|payment)",
    re.IGNORECASE,
)

_EXTENSIONES_CODIGO = {".py", ".js", ".ts", ".swift", ".go", ".rs", ".cpp", ".c", ".h", ".java", ".kt"}
_EXTENSIONES_IMAGEN = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".webp", ".heic"}
_EXTENSIONES_VIDEO = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".wmv"}
_EXTENSIONES_AUDIO = {".mp3", ".wav", ".aac", ".flac", ".m4a", ".ogg"}


# ---------------------------------------------------------------------------
# SistemaArchivos
# ---------------------------------------------------------------------------


class SistemaArchivos:
    """Operaciones de FS con sandbox de raíz y log de auditoría.

    Ejemplo::
        fs = SistemaArchivos()
        texto = await fs.leer_archivo(Path("~/Documents/notas.txt"))
    """

    def __init__(
        self,
        raiz_permitida: Path | None = None,
        *,
        callback_confirmacion: Callable[[str], asyncio.Future[bool]] | None = None,
        audit_log: AuditLog | None = None,
        auth_manager: AuthManager | None = None,
    ) -> None:
        self._raiz = (raiz_permitida or _HOME).resolve()
        self._confirmar = callback_confirmacion or _denegar
        self._audit = audit_log
        self._auth = auth_manager

        # Importado perezosamente para no romper en CI sin macOS
        self._watchdog_observer: object | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------
    # Operaciones de lectura
    # ------------------------------------------------------------------

    async def leer_archivo(self, ruta: Path) -> str:
        """Lee un archivo de texto UTF-8.

        Ejemplo::
            texto = await fs.leer_archivo(Path("~/notas.txt"))
        """
        objetivo = self._validar(ruta)
        contenido = await asyncio.to_thread(objetivo.read_text, "utf-8")
        await self._audit_log("leer_archivo", {"ruta": str(objetivo)})
        return contenido

    async def leer_bytes(self, ruta: Path) -> bytes:
        """Lee un archivo en binario.

        Ejemplo::
            datos = await fs.leer_bytes(Path("~/imagen.png"))
        """
        objetivo = self._validar(ruta)
        return await asyncio.to_thread(objetivo.read_bytes)

    async def obtener_info(self, ruta: Path) -> InfoArchivo:
        """Devuelve metadatos de un archivo o directorio.

        Ejemplo::
            info = await fs.obtener_info(Path("~/Downloads/doc.pdf"))
            print(info.tamaño_bytes)
        """
        objetivo = self._validar(ruta)
        return await asyncio.to_thread(self._info_sync, objetivo)

    async def listar_directorio(self, ruta: Path) -> list[InfoArchivo]:
        """Lista el contenido de un directorio.

        Ejemplo::
            entradas = await fs.listar_directorio(Path("~/Documents"))
        """
        objetivo = self._validar(ruta)

        def _listar() -> list[InfoArchivo]:
            return [self._info_sync(p) for p in sorted(objetivo.iterdir())]

        return await asyncio.to_thread(_listar)

    async def buscar_archivos(
        self,
        consulta: str,
        directorio: Path,
        *,
        recursivo: bool = True,
    ) -> list[InfoArchivo]:
        """Busca archivos cuyo nombre contenga `consulta` (case-insensitive).

        Ejemplo::
            resultados = await fs.buscar_archivos("factura", Path("~/Documents"))
        """
        objetivo = self._validar(directorio)
        patron = "**/*" if recursivo else "*"

        def _buscar() -> list[InfoArchivo]:
            coincidencias = []
            for p in objetivo.glob(patron):
                if consulta.lower() in p.name.lower():
                    coincidencias.append(self._info_sync(p))
            return coincidencias

        return await asyncio.to_thread(_buscar)

    # ------------------------------------------------------------------
    # Operaciones de escritura
    # ------------------------------------------------------------------

    async def escribir_archivo(self, ruta: Path, contenido: str) -> bool:
        """Escribe texto en un archivo, creando directorios intermedios.

        Ejemplo::
            ok = await fs.escribir_archivo(Path("~/notas.txt"), "hola")
        """
        objetivo = self._validar(ruta)

        def _escribir() -> None:
            objetivo.parent.mkdir(parents=True, exist_ok=True)
            objetivo.write_text(contenido, encoding="utf-8")

        await asyncio.to_thread(_escribir)
        await self._audit_log("escribir_archivo", {"ruta": str(objetivo), "bytes": len(contenido)})
        return True

    async def añadir_archivo(self, ruta: Path, contenido: str) -> bool:
        """Añade texto al final de un archivo.

        Ejemplo::
            await fs.añadir_archivo(Path("~/log.txt"), "nueva línea\n")
        """
        objetivo = self._validar(ruta)

        def _añadir() -> None:
            objetivo.parent.mkdir(parents=True, exist_ok=True)
            with objetivo.open("a", encoding="utf-8") as f:
                f.write(contenido)

        await asyncio.to_thread(_añadir)
        await self._audit_log("añadir_archivo", {"ruta": str(objetivo)})
        return True

    async def crear_directorio(self, ruta: Path) -> bool:
        """Crea un directorio (y sus padres).

        Ejemplo::
            await fs.crear_directorio(Path("~/Proyectos/nuevo"))
        """
        objetivo = self._validar(ruta)
        await asyncio.to_thread(objetivo.mkdir, parents=True, exist_ok=True)
        await self._audit_log("crear_directorio", {"ruta": str(objetivo)})
        return True

    async def mover_archivo(self, origen: Path, destino: Path) -> bool:
        """Mueve o renombra un archivo.

        Ejemplo::
            await fs.mover_archivo(Path("~/a.txt"), Path("~/b.txt"))
        """
        src = self._validar(origen)
        dst = self._validar(destino)

        def _mover() -> None:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), dst)

        await asyncio.to_thread(_mover)
        await self._audit_log("mover_archivo", {"origen": str(src), "destino": str(dst)})
        return True

    async def copiar_archivo(self, origen: Path, destino: Path) -> bool:
        """Copia un archivo preservando metadatos.

        Ejemplo::
            await fs.copiar_archivo(Path("~/original.txt"), Path("~/copia.txt"))
        """
        src = self._validar(origen)
        dst = self._validar(destino)

        def _copiar() -> None:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

        await asyncio.to_thread(_copiar)
        await self._audit_log("copiar_archivo", {"origen": str(src), "destino": str(dst)})
        return True

    # ------------------------------------------------------------------
    # Operaciones destructivas — requieren confirmación
    # ------------------------------------------------------------------

    async def eliminar_archivo(self, ruta: Path) -> bool:
        """Elimina un archivo. Requiere confirmación explícita.

        Ejemplo::
            ok = await fs.eliminar_archivo(Path("~/temporal.txt"))
        """
        objetivo = self._validar(ruta)
        aprobado = await self._confirmar(f"Eliminar archivo: {objetivo}")
        if not aprobado:
            return False
        await asyncio.to_thread(objetivo.unlink, True)
        await self._audit_log("eliminar_archivo", {"ruta": str(objetivo)})
        return True

    async def eliminar_directorio(self, ruta: Path, *, recursivo: bool = False) -> bool:
        """Elimina un directorio. Siempre requiere Face ID + confirmación.

        Ejemplo::
            ok = await fs.eliminar_directorio(Path("~/temporal/"), recursivo=True)
        """
        objetivo = self._validar(ruta)
        desc = f"Eliminar directorio {'recursivamente' if recursivo else ''}: {objetivo}"
        if self._auth is not None:
            await self._auth.require_auth(desc)
        aprobado = await self._confirmar(desc)
        if not aprobado:
            return False

        def _eliminar() -> None:
            if recursivo:
                shutil.rmtree(objetivo)
            else:
                objetivo.rmdir()

        await asyncio.to_thread(_eliminar)
        await self._audit_log("eliminar_directorio", {"ruta": str(objetivo), "recursivo": recursivo})
        return True

    # ------------------------------------------------------------------
    # Organización proactiva de Downloads
    # ------------------------------------------------------------------

    def clasificar_archivo(self, info: InfoArchivo) -> str:
        """Devuelve la categoría de un archivo según su tipo y nombre.

        Ejemplo::
            categoria = fs.clasificar_archivo(info)  # "universidad"
        """
        ext = info.extension.lower()
        nombre_lower = info.nombre.lower()

        if ext in _EXTENSIONES_IMAGEN:
            if "screenshot" in nombre_lower or "captura" in nombre_lower:
                return "screenshot"
            return "imagen"

        if ext in _EXTENSIONES_VIDEO:
            return "video"

        if ext in _EXTENSIONES_AUDIO:
            return "audio"

        if ext in _EXTENSIONES_CODIGO:
            return "codigo"

        if ext == ".pdf":
            # Intenta leer las primeras líneas del nombre para clasificar
            if _KW_FISICA.search(info.nombre):
                return "universidad"
            if _KW_FACTURA.search(info.nombre):
                return "admin"
            return "documento"

        if ext in {".doc", ".docx", ".odt", ".pages"}:
            return "documento"

        if ext in {".xls", ".xlsx", ".csv", ".numbers"}:
            return "datos"

        if ext in {".zip", ".tar", ".gz", ".bz2", ".7z", ".rar", ".dmg", ".pkg"}:
            return "instalador"

        return "varios"

    def sugerir_destino(self, info: InfoArchivo) -> Path:
        """Devuelve la ruta de destino sugerida para organizar el archivo.

        Ejemplo::
            destino = fs.sugerir_destino(info)
            # Path("~/Documents/Universidad/Física/")
        """
        categoria = self.clasificar_archivo(info)
        año = info.modificado_en.strftime("%Y")
        mes_año = info.modificado_en.strftime("%Y-%m")

        destinos: dict[str, Path] = {
            "universidad": _HOME / "Documents" / "Universidad" / "Física",
            "admin": _HOME / "Documents" / "Admin" / "Facturas" / año,
            "codigo": _HOME / "Projects",
            "imagen": _HOME / "Pictures" / año,
            "screenshot": _HOME / "Pictures" / "Screenshots" / mes_año,
            "video": _HOME / "Movies" / año,
            "audio": _HOME / "Music" / año,
            "documento": _HOME / "Documents" / año,
            "datos": _HOME / "Documents" / "Datos",
            "instalador": _HOME / "Downloads" / "Instaladores",
            "varios": _HOME / "Downloads" / "Varios",
        }
        return destinos.get(categoria, _HOME / "Downloads" / "Varios")

    async def organizar_archivo(self, info: InfoArchivo) -> PropuestaMover:
        """Propone (sin ejecutar) dónde mover un archivo.

        Ejemplo::
            propuesta = await fs.organizar_archivo(info)
            print(propuesta.destino)
        """
        categoria = self.clasificar_archivo(info)
        destino_dir = self.sugerir_destino(info)
        destino = destino_dir / info.nombre
        return PropuestaMover(
            origen=info.ruta,
            destino=destino,
            categoria=categoria,
            razon=f"Clasificado como '{categoria}' → {destino_dir}",
        )

    async def vigilar_downloads(self) -> Task[None]:
        """Inicia una tarea asyncio que monitoriza ~/Downloads y clasifica archivos nuevos.

        Devuelve la Task para poder cancelarla.

        Ejemplo::
            tarea = await fs.vigilar_downloads()
            # más tarde:
            tarea.cancel()
        """
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer

        fs_ref = self

        class _Handler(FileSystemEventHandler):
            def on_created(self, event: object) -> None:
                if not getattr(event, "is_directory", False):
                    src = Path(getattr(event, "src_path", ""))
                    asyncio.run_coroutine_threadsafe(
                        fs_ref._procesar_archivo_nuevo(src),
                        fs_ref._loop,
                    )

        observer = Observer()
        observer.schedule(_Handler(), str(_HOME / "Downloads"), recursive=False)
        self._watchdog_observer = observer
        self._loop = asyncio.get_running_loop()

        async def _bucle() -> None:
            observer.start()
            try:
                while True:
                    await asyncio.sleep(1)
            finally:
                observer.stop()
                observer.join()

        return asyncio.create_task(_bucle())

    async def _procesar_archivo_nuevo(self, ruta: Path) -> None:
        try:
            info = await self.obtener_info(ruta)
            propuesta = await self.organizar_archivo(info)
            await self._audit_log("organizar_sugerencia", {
                "origen": str(propuesta.origen),
                "destino": str(propuesta.destino),
                "categoria": propuesta.categoria,
            })
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Helpers internos
    # ------------------------------------------------------------------

    def _validar(self, ruta: Path) -> Path:
        """Resuelve y verifica que la ruta esté bajo la raíz permitida."""
        resuelta = ruta.expanduser().resolve()
        # Resolver symlinks antes de validar para evitar escape
        try:
            resuelta.relative_to(self._raiz)
        except ValueError as exc:
            raise PermissionError(
                f"Ruta fuera de la raíz permitida ({self._raiz}): {resuelta}"
            ) from exc
        return resuelta

    def _info_sync(self, ruta: Path) -> InfoArchivo:
        stat = ruta.stat()
        mime, _ = mimetypes.guess_type(ruta.name)
        return InfoArchivo(
            ruta=ruta,
            nombre=ruta.name,
            extension=ruta.suffix,
            tamaño_bytes=stat.st_size,
            creado_en=datetime.fromtimestamp(stat.st_birthtime if hasattr(stat, "st_birthtime") else stat.st_ctime, tz=UTC),
            modificado_en=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
            es_directorio=ruta.is_dir(),
            es_oculto=ruta.name.startswith("."),
            mime_type=mime or "application/octet-stream",
        )

    async def _audit_log(self, evento: str, datos: dict) -> None:
        if self._audit is not None:
            await self._audit.registrar(evento, datos)


# Importaciones diferidas para evitar ciclo con security/
try:
    from security.audit_log import AuditLog  # noqa: F401
except ImportError:
    AuditLog = None  # type: ignore[assignment,misc]

try:
    from security.auth import AuthManager  # noqa: F401
except ImportError:
    AuthManager = None  # type: ignore[assignment,misc]
