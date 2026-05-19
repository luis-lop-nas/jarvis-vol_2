"""Control del sistema operativo macOS: apps, volumen, brillo, clipboard y notificaciones.

Toda interacción con el sistema macOS pasa por este módulo.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Errores AppleScript
# ---------------------------------------------------------------------------

_SUGERENCIAS_AS: dict[int, str] = {
    -600: "Abre la aplicación antes de usarla",
    -609: "La app puede estar bloqueada; ciérrala y vuelve a abrirla",
    -1708: "La app no estaba lista; el sistema reintentó automáticamente",
    -1712: "La app no responde; verifica que no está colgada",
    -10826: "Verifica permisos de Accesibilidad en Privacidad y Seguridad",
}


class AppleScriptError(Exception):
    """Error al ejecutar un bloque de AppleScript.

    Ejemplo::
        try:
            await cs.ejecutar_applescript_estricto(script)
        except AppleScriptError as e:
            print(f"Error {e.error_code} en {e.app_name}: {e.suggestion}")
    """

    def __init__(self, *, error_code: int, app_name: str, suggestion: str) -> None:
        self.error_code = error_code
        self.app_name = app_name
        self.suggestion = suggestion
        super().__init__(f"AppleScript error {error_code} en '{app_name}': {suggestion}")

# ---------------------------------------------------------------------------
# Tipos públicos
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class InfoApp:
    """Información de una aplicación en ejecución.

    Ejemplo::
        apps = await sistema.obtener_apps_en_ejecucion()
        print(apps[0].nombre)
    """

    nombre: str
    bundle_id: str
    pid: int
    activa: bool


@dataclass(slots=True)
class InfoBateria:
    """Estado de la batería del sistema.

    Ejemplo::
        bateria = await sistema.obtener_bateria()
        print(f"{bateria.porcentaje}% {'cargando' if bateria.cargando else 'descargando'}")
    """

    porcentaje: int
    cargando: bool
    tiempo_restante_min: int | None


@dataclass(slots=True)
class InfoWifi:
    """Estado de la conexión Wi-Fi.

    Ejemplo::
        wifi = await sistema.obtener_wifi()
        print(wifi.ssid)
    """

    ssid: str | None
    conectado: bool
    interfaz: str


# ---------------------------------------------------------------------------
# ControlSistema
# ---------------------------------------------------------------------------


class ControlSistema:
    """Control de alto nivel sobre macOS vía AppleScript y herramientas CLI.

    Ejemplo::
        cs = ControlSistema()
        await cs.enviar_notificacion("JARVIS", "Tarea completada")
    """

    _TIMEOUT_AS = 10.0  # timeout para AppleScript en segundos

    # ------------------------------------------------------------------
    # Aplicaciones
    # ------------------------------------------------------------------

    async def abrir_app(self, nombre_o_bundle: str) -> bool:
        """Abre una aplicación por nombre o bundle ID.

        Ejemplo::
            await cs.abrir_app("Safari")
            await cs.abrir_app("com.apple.Safari")
        """
        if "." in nombre_o_bundle and not nombre_o_bundle.endswith(".app"):
            resultado = await self._ejecutar(["open", "-b", nombre_o_bundle])
        else:
            resultado = await self._ejecutar(["open", "-a", nombre_o_bundle])
        return resultado is not None

    async def cerrar_app(self, bundle_id: str) -> bool:
        """Cierra una app limpiamente vía AppleScript.

        Ejemplo::
            await cs.cerrar_app("com.apple.Safari")
        """
        nombre = await self._bundle_a_nombre(bundle_id)
        if not nombre:
            return False
        script = f'tell application "{self._escapar(nombre)}" to quit'
        return await self._applescript(script) is not None

    async def ocultar_app(self, bundle_id: str) -> bool:
        """Oculta una aplicación.

        Ejemplo::
            await cs.ocultar_app("com.apple.Terminal")
        """
        nombre = await self._bundle_a_nombre(bundle_id)
        if not nombre:
            return False
        script = f'tell application "System Events" to set visible of process "{self._escapar(nombre)}" to false'
        return await self._applescript(script) is not None

    async def enfocar_app(self, bundle_id: str) -> bool:
        """Pone una aplicación en primer plano.

        Ejemplo::
            await cs.enfocar_app("com.apple.Safari")
        """
        nombre = await self._bundle_a_nombre(bundle_id)
        if not nombre:
            return False
        script = f'tell application "{self._escapar(nombre)}" to activate'
        return await self._applescript(script) is not None

    async def app_en_ejecucion(self, bundle_id: str) -> bool:
        """Comprueba si una app está en ejecución.

        Ejemplo::
            corriendo = await cs.app_en_ejecucion("com.apple.Safari")
        """
        nombre = await self._bundle_a_nombre(bundle_id)
        if not nombre:
            return False
        script = f'tell application "System Events" to (name of processes) contains "{self._escapar(nombre)}"'
        res = await self._applescript(script)
        return res == "true" if res else False

    async def obtener_apps_en_ejecucion(self) -> list[InfoApp]:
        """Lista todas las apps en ejecución.

        Ejemplo::
            apps = await cs.obtener_apps_en_ejecucion()
        """
        script = (
            'tell application "System Events"\n'
            '  set procs to every process whose background only is false\n'
            '  set result to {}\n'
            '  repeat with p in procs\n'
            '    set end of result to (name of p) & "," & (unix id of p as string) & "," & (frontmost of p as string)\n'
            '  end repeat\n'
            '  return result\n'
            'end tell'
        )
        salida = await self._applescript(script)
        apps: list[InfoApp] = []
        if not salida:
            return apps
        for entrada in salida.split(", "):
            partes = entrada.split(",")
            if len(partes) >= 3:
                apps.append(InfoApp(
                    nombre=partes[0].strip(),
                    bundle_id="",
                    pid=int(partes[1].strip()) if partes[1].strip().isdigit() else 0,
                    activa=partes[2].strip() == "true",
                ))
        return apps

    async def abrir_url(self, url: str) -> bool:
        """Abre una URL en Safari.

        Ejemplo::
            await cs.abrir_url("https://example.com")
        """
        return await self._ejecutar(["open", url]) is not None

    # ------------------------------------------------------------------
    # Volumen y brillo
    # ------------------------------------------------------------------

    async def obtener_volumen(self) -> int:
        """Devuelve el volumen actual del sistema (0-100).

        Ejemplo::
            vol = await cs.obtener_volumen()
        """
        res = await self._applescript("output volume of (get volume settings)")
        try:
            return int(res or "0")
        except ValueError:
            return 0

    async def establecer_volumen(self, nivel: int) -> bool:
        """Establece el volumen del sistema (0-100).

        Ejemplo::
            await cs.establecer_volumen(50)
        """
        if not 0 <= nivel <= 100:
            raise ValueError(f"Volumen fuera de rango 0-100: {nivel}")
        return await self._applescript(f"set volume output volume {nivel}") is not None

    async def obtener_brillo(self) -> int:
        """Devuelve el brillo de la pantalla (0-100).

        Ejemplo::
            brillo = await cs.obtener_brillo()
        """
        res = await self._applescript(
            'do shell script "brightness -l 2>&1 | grep -oE \'[0-9]+\\.[0-9]+\' | awk \'{ print int($1 * 100) }\'"'
        )
        try:
            return int(res or "50")
        except ValueError:
            return 50

    async def establecer_brillo(self, nivel: int) -> bool:
        """Establece el brillo de la pantalla (0-100). Requiere la CLI `brightness`.

        Ejemplo::
            await cs.establecer_brillo(75)
        """
        if not 0 <= nivel <= 100:
            raise ValueError(f"Brillo fuera de rango 0-100: {nivel}")
        valor = nivel / 100.0
        return await self._ejecutar(["brightness", str(valor)]) is not None

    # ------------------------------------------------------------------
    # Pantalla y DnD
    # ------------------------------------------------------------------

    async def bloquear_pantalla(self) -> bool:
        """Bloquea la pantalla del sistema.

        Ejemplo::
            await cs.bloquear_pantalla()
        """
        return await self._ejecutar([
            "osascript", "-e",
            'tell application "System Events" to key code 12 using {control down, command down}',
        ]) is not None

    async def establecer_no_molestar(self, activado: bool) -> bool:
        """Activa o desactiva el modo No Molestar.

        Ejemplo::
            await cs.establecer_no_molestar(True)
        """
        valor = "1" if activado else "0"
        cmd = f"defaults -currentHost write com.apple.notificationcenterui doNotDisturb -int {valor}"
        return await self._ejecutar_shell(cmd) is not None

    async def obtener_bateria(self) -> InfoBateria:
        """Devuelve información de la batería.

        Ejemplo::
            b = await cs.obtener_bateria()
            print(b.porcentaje)
        """
        import re

        salida = await self._ejecutar_shell("pmset -g batt")
        if not salida:
            return InfoBateria(porcentaje=0, cargando=False, tiempo_restante_min=None)

        pct_match = re.search(r"(\d+)%", salida)
        porcentaje = int(pct_match.group(1)) if pct_match else 0
        cargando = "AC Power" in salida or "charging" in salida.lower()
        tiempo: int | None = None
        tiempo_match = re.search(r"(\d+):(\d+) remaining", salida)
        if tiempo_match:
            tiempo = int(tiempo_match.group(1)) * 60 + int(tiempo_match.group(2))

        return InfoBateria(porcentaje=porcentaje, cargando=cargando, tiempo_restante_min=tiempo)

    async def obtener_wifi(self) -> InfoWifi:
        """Devuelve información de la conexión Wi-Fi activa.

        Ejemplo::
            wifi = await cs.obtener_wifi()
            print(wifi.ssid)
        """
        salida = await self._ejecutar_shell(
            "/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport -I"
        )
        ssid: str | None = None
        if salida:
            for linea in salida.splitlines():
                if "SSID" in linea and "BSSID" not in linea:
                    ssid = linea.split(":", 1)[-1].strip()
                    break
        return InfoWifi(ssid=ssid, conectado=ssid is not None, interfaz="en0")

    async def capturar_escritorios(self) -> dict[int, bytes]:
        """Captura una imagen de cada espacio de Spaces.

        Devuelve dict {índice: bytes_png}.

        Ejemplo::
            escritorios = await cs.capturar_escritorios()
        """
        import tempfile

        tmp = Path(tempfile.mkdtemp())
        await self._ejecutar(["screencapture", "-x", "-C", str(tmp / "screen%02d.png")])
        resultado: dict[int, bytes] = {}
        for i, archivo in enumerate(sorted(tmp.glob("screen*.png"))):
            resultado[i] = archivo.read_bytes()
            archivo.unlink()
        tmp.rmdir()
        return resultado

    # ------------------------------------------------------------------
    # Clipboard
    # ------------------------------------------------------------------

    async def obtener_portapapeles(self) -> str | bytes | None:
        """Devuelve el contenido del portapapeles.

        Ejemplo::
            texto = await cs.obtener_portapapeles()
        """
        proc = await asyncio.create_subprocess_exec(
            "pbpaste",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode == 0:
            return stdout.decode(errors="replace")
        return None

    async def establecer_portapapeles(self, contenido: str) -> bool:
        """Establece el contenido del portapapeles.

        Ejemplo::
            await cs.establecer_portapapeles("texto copiado")
        """
        proc = await asyncio.create_subprocess_exec(
            "pbcopy",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate(input=contenido.encode())
        return proc.returncode == 0

    async def tipo_portapapeles(self) -> str:
        """Devuelve el tipo del contenido del portapapeles: text/image/file/unknown.

        Ejemplo::
            tipo = await cs.tipo_portapapeles()  # "text"
        """
        res = await self._applescript(
            'clipboard info'
        )
        if not res:
            return "unknown"
        if "string" in res or "text" in res.lower():
            return "text"
        if "TIFF" in res or "JPEG" in res or "PNG" in res:
            return "image"
        if "«class furl»" in res or "file" in res.lower():
            return "file"
        return "unknown"

    # ------------------------------------------------------------------
    # Notificaciones
    # ------------------------------------------------------------------

    async def enviar_notificacion(
        self,
        titulo: str,
        cuerpo: str,
        subtitulo: str = "",
    ) -> bool:
        """Envía una notificación nativa de macOS.

        Ejemplo::
            await cs.enviar_notificacion("JARVIS", "Tarea lista", subtitulo="acción completada")
        """
        sub_part = f' subtitle "{self._escapar(subtitulo)}"' if subtitulo else ""
        script = (
            f'display notification "{self._escapar(cuerpo)}"'
            f' with title "{self._escapar(titulo)}"{sub_part}'
        )
        return await self._applescript(script) is not None

    async def mostrar_alerta(
        self,
        titulo: str,
        mensaje: str,
        botones: list[str] | None = None,
    ) -> str:
        """Muestra un diálogo nativo y devuelve el botón pulsado.

        Ejemplo::
            boton = await cs.mostrar_alerta("JARVIS", "¿Continuar?", botones=["Sí", "No"])
        """
        bts = botones or ["OK"]
        bts_as = "{" + ", ".join(f'"{b}"' for b in bts) + "}"
        script = (
            f'tell application "System Events"\n'
            f'  set respuesta to button returned of '
            f'(display alert "{self._escapar(titulo)}" '
            f'message "{self._escapar(mensaje)}" '
            f'buttons {bts_as})\n'
            f'  return respuesta\n'
            f'end tell'
        )
        res = await self._applescript(script)
        return res or ""

    # ------------------------------------------------------------------
    # AppleScript helper (privado)
    # ------------------------------------------------------------------

    async def ejecutar_applescript(self, script: str) -> str | None:
        """Ejecuta AppleScript con timeout de seguridad.

        Ejemplo::
            res = await cs.ejecutar_applescript('return "hola"')
        """
        return await self._applescript(script)

    async def ejecutar_applescript_estricto(self, script: str) -> str:
        """Ejecuta AppleScript y lanza AppleScriptError si falla.

        Ejemplo::
            res = await cs.ejecutar_applescript_estricto('tell application "Safari" to get URL ...')
        """
        resultado = await self._applescript(script, _raise_on_error=True)
        return resultado or ""

    async def _applescript(
        self,
        script: str,
        *,
        timeout: float | None = None,
        _raise_on_error: bool = False,
    ) -> str | None:
        for intento in range(2):
            try:
                proc = await asyncio.create_subprocess_exec(
                    "osascript", "-e", script,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=timeout or self._TIMEOUT_AS,
                )
                if proc.returncode != 0:
                    err = self._parsear_error_as(script, stderr.decode(errors="replace"))
                    if err.error_code == -1708 and intento == 0:
                        await asyncio.sleep(0.5)
                        continue
                    _log.warning("AppleScript error: %s", err)
                    if _raise_on_error:
                        raise err
                    return None
                return stdout.decode(errors="replace").strip()
            except AppleScriptError:
                raise
            except TimeoutError:
                if _raise_on_error:
                    raise AppleScriptError(
                        error_code=-1712,
                        app_name=self._extraer_app(script),
                        suggestion=_SUGERENCIAS_AS.get(-1712, "La app no responde"),
                    )
                return None
            except FileNotFoundError:
                return None
        return None

    @staticmethod
    def _parsear_error_as(script: str, stderr: str) -> AppleScriptError:
        """Extrae código de error AppleScript de stderr y construye AppleScriptError."""
        match = re.search(r'\((-?\d+)\)', stderr)
        codigo = int(match.group(1)) if match else 0
        app_name = ControlSistema._extraer_app(script)
        return AppleScriptError(
            error_code=codigo,
            app_name=app_name,
            suggestion=_SUGERENCIAS_AS.get(codigo, "Verifica que la aplicación esté en ejecución"),
        )

    @staticmethod
    def _extraer_app(script: str) -> str:
        """Extrae el nombre de app de un script AppleScript."""
        m = re.search(r'application "([^"]+)"', script)
        return m.group(1) if m else "desconocida"

    async def _bundle_a_nombre(self, bundle_id: str) -> str | None:
        """Resuelve un bundle ID a nombre de proceso."""
        if "." not in bundle_id:
            return bundle_id  # ya es un nombre
        res = await self._ejecutar_shell(
            f"osascript -e 'id of application \"{bundle_id}\"' 2>/dev/null || echo \"{bundle_id}\""
        )
        # Si no pudo resolver, usa el bundle como nombre
        return res.split(".")[-1].capitalize() if res else None

    async def _ejecutar(self, argv: list[str]) -> str | None:
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=self._TIMEOUT_AS)
            return stdout.decode(errors="replace").strip() if proc.returncode == 0 else None
        except (TimeoutError, FileNotFoundError):
            return None

    async def _ejecutar_shell(self, cmd: str) -> str | None:
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=self._TIMEOUT_AS)
            return stdout.decode(errors="replace").strip() if proc.returncode == 0 else None
        except (TimeoutError, FileNotFoundError):
            return None

    @staticmethod
    def _escapar(texto: str) -> str:
        return texto.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
