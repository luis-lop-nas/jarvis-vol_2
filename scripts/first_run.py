#!/usr/bin/env python3
"""
Primer arranque interactivo de JARVIS.
Guía al usuario por la configuración inicial y verifica que todo funciona.
Ejecutar: python scripts/first_run.py
"""
from __future__ import annotations

import asyncio
import getpass
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# ── rich ───────────────────────────────────────────────────────────────────────
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Confirm, Prompt
    from rich.rule import Rule
    from rich.text import Text
except ImportError:
    print("Instala rich: pip install rich")
    sys.exit(1)

console = Console()

BANNER = r"""
     ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
     ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
     ██║███████║██████╔╝██║   ██║██║███████╗
██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║
 ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝
"""

ROOT = Path(__file__).parent.parent
ENV_FILE = ROOT / ".env"
ENV_EXAMPLE = ROOT / ".env.example"


# ── utilidades ─────────────────────────────────────────────────────────────────


def _set_env_var(key: str, value: str) -> None:
    """Escribe o actualiza una variable en .env preservando el resto."""
    if not ENV_FILE.exists() and ENV_EXAMPLE.exists():
        ENV_FILE.write_text(ENV_EXAMPLE.read_text())

    content = ENV_FILE.read_text() if ENV_FILE.exists() else ""
    pattern = re.compile(rf"^({re.escape(key)}=).*$", re.MULTILINE)
    if pattern.search(content):
        content = pattern.sub(rf"\g<1>{value}", content)
    else:
        content += f"\n{key}={value}\n"
    ENV_FILE.write_text(content)


def _get_env_var(key: str) -> str:
    """Lee una variable de .env (sin cargar el módulo settings)."""
    if not ENV_FILE.exists():
        return ""
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return ""


def _ok(msg: str) -> None:
    console.print(f"  [green]✓[/green] {msg}")


def _warn(msg: str) -> None:
    console.print(f"  [yellow]⚠[/yellow] {msg}")


def _fail(msg: str) -> None:
    console.print(f"  [red]✗[/red] {msg}")


# ── pasos ──────────────────────────────────────────────────────────────────────


def step_banner() -> None:
    console.print(Panel(Text(BANNER, style="bold cyan", justify="center"),
                        subtitle="Agente IA Autónomo para macOS", border_style="cyan"))


async def step_verify() -> bool:
    """Llama a verify_system.verify_all(). Devuelve False si hay críticos."""
    console.print(Rule("[bold]1 / 7  Verificación del sistema[/bold]"))
    sys.path.insert(0, str(ROOT))
    try:
        from scripts.verify_system import verify_all  # type: ignore[import]
        return await verify_all()
    except Exception as exc:
        _fail(f"No se pudo importar verify_system: {exc}")
        return False


def step_api_keys() -> None:
    """Pide las API keys que faltan y las guarda en .env."""
    console.print(Rule("[bold]2 / 7  Configuración de API keys[/bold]"))

    kimi_key = _get_env_var("KIMI_API_KEY")
    if kimi_key in ("", "your_kimi_api_key_here"):
        console.print("  Necesito tu [bold]Kimi API Key[/bold].")
        console.print("  Consíguela en [link=https://platform.moonshot.cn]platform.moonshot.cn[/link]")
        kimi_key = getpass.getpass("  KIMI_API_KEY: ").strip()
        if kimi_key:
            _set_env_var("KIMI_API_KEY", kimi_key)
            _ok("KIMI_API_KEY guardada en .env")
        else:
            _warn("Kimi API Key omitida — algunos tests fallarán")
    else:
        _ok("KIMI_API_KEY ya configurada")

    deepseek_key = _get_env_var("DEEPSEEK_API_KEY")
    if deepseek_key in ("", "your_deepseek_api_key_here"):
        console.print("  [bold]DeepSeek API Key[/bold] (opcional — fallback económico).")
        console.print("  Consíguela en [link=https://platform.deepseek.com]platform.deepseek.com[/link]")
        if Confirm.ask("  ¿Configurarla ahora?", default=False):
            deepseek_key = getpass.getpass("  DEEPSEEK_API_KEY: ").strip()
            if deepseek_key:
                _set_env_var("DEEPSEEK_API_KEY", deepseek_key)
                _ok("DEEPSEEK_API_KEY guardada en .env")
    else:
        _ok("DEEPSEEK_API_KEY ya configurada")

    # Recargar settings con las nuevas keys
    if "config.settings" in sys.modules:
        del sys.modules["config.settings"]
    if "config" in sys.modules:
        del sys.modules["config"]


async def step_test_models() -> None:
    """Prueba cada modelo con una llamada simple."""
    console.print(Rule("[bold]3 / 7  Test de modelos[/bold]"))

    sys.path.insert(0, str(ROOT))

    # Kimi
    try:
        from models.base import Mensaje
        from models.kimi import KimiModel
        msg = [Mensaje(rol="user", contenido="Responde solo: OK")]
        kimi = KimiModel()
        resp = await kimi.complete(msg, max_tokens=10)
        _ok(f"Kimi K2.6 · '{resp.content[:40]}'")
    except Exception as exc:
        _fail(f"Kimi K2.6 · {exc}")

    # DeepSeek
    deepseek_key = _get_env_var("DEEPSEEK_API_KEY")
    if deepseek_key not in ("", "your_deepseek_api_key_here"):
        try:
            from models.base import Mensaje
            from models.deepseek import DeepSeekModel
            msg = [Mensaje(rol="user", contenido="Responde solo: OK")]
            ds = DeepSeekModel()
            resp = await ds.complete(msg, max_tokens=10)
            _ok(f"DeepSeek V3.2 · '{resp.content[:40]}'")
        except Exception as exc:
            _warn(f"DeepSeek V3.2 · {exc}")
    else:
        _warn("DeepSeek omitido — key no configurada")

    # Ollama local
    try:
        import httpx as _httpx
        async with _httpx.AsyncClient() as c:
            r = await c.post(
                "http://localhost:11434/api/generate",
                json={"model": "gemma4:4b", "prompt": "Responde solo: OK", "stream": False},
                timeout=30,
            )
            body = r.json()
            response_text = body.get("response", "").strip()[:40]
            _ok(f"Ollama gemma4:4b · '{response_text}'")
    except Exception as exc:
        _warn(f"Ollama local · {exc}")


def step_test_permissions() -> None:
    """Prueba los permisos macOS: screenshot + Accessibility."""
    console.print(Rule("[bold]4 / 7  Test de permisos macOS[/bold]"))

    # Screenshot
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        tmp = f.name
    result = subprocess.run(
        ["screencapture", "-x", "-t", "png", tmp],
        capture_output=True, timeout=5,
    )
    if result.returncode == 0 and Path(tmp).stat().st_size > 0:
        _ok("Screen Recording · captura OK")
        Path(tmp).unlink(missing_ok=True)
    else:
        _fail("Screen Recording · sin permiso — Ajustes → Privacidad → Grabación de pantalla")

    # Accessibility
    try:
        import ApplicationServices  # type: ignore[import]
        if ApplicationServices.AXIsProcessTrusted():
            _ok("Accessibility · permiso concedido")
        else:
            _fail("Accessibility · sin permiso — Ajustes → Privacidad → Accesibilidad")
    except ImportError:
        _warn("Accessibility · pyobjc no disponible (pip install pyobjc-framework-ApplicationServices)")


async def step_test_memory() -> None:
    """Escribe, recupera y borra una entrada en ChromaDB."""
    console.print(Rule("[bold]5 / 7  Test de memoria (ChromaDB)[/bold]"))
    try:
        import chromadb  # type: ignore[import]
        client = chromadb.HttpClient(host="localhost", port=8000)
        col_name = "_jarvis_first_run_test"
        # crear colección temporal
        col = client.get_or_create_collection(col_name)
        col.add(
            documents=["Test de primer arranque JARVIS"],
            ids=["test_001"],
        )
        results = col.get(ids=["test_001"])
        assert results["documents"] and results["documents"][0]
        client.delete_collection(col_name)
        _ok("ChromaDB · escritura/lectura/borrado OK")
    except Exception as exc:
        _fail(f"ChromaDB · {exc}")


def step_personality() -> None:
    """Configura nombre de usuario y directorio de proyectos."""
    console.print(Rule("[bold]6 / 7  Configuración de personalidad[/bold]"))

    nombre_actual = _get_env_var("USUARIO_NOMBRE") or "Luichi"
    nombre = Prompt.ask("  ¿Cómo quieres que te llame JARVIS?", default=nombre_actual)
    _set_env_var("USUARIO_NOMBRE", nombre)
    _ok(f"JARVIS te llamará: [bold]{nombre}[/bold]")

    proyectos_actual = _get_env_var("JARVIS_PROJECTS_DIR") or str(Path.home() / "Documents/Proyectos")
    proyectos = Prompt.ask("  ¿Cuál es tu carpeta raíz de proyectos?", default=proyectos_actual)
    _set_env_var("JARVIS_PROJECTS_DIR", proyectos)
    _ok(f"Carpeta de proyectos: [bold]{proyectos}[/bold]")


async def step_launch() -> None:
    """Arranque final de JARVIS."""
    console.print(Rule("[bold]7 / 7  Arranque final[/bold]"))

    if not Confirm.ask("\n  Todo listo. ¿Arrancar JARVIS ahora?", default=True):
        console.print("\n  Cuando quieras: [bold]make dev[/bold]")
        return

    console.print("\n  [bold cyan]Arrancando JARVIS...[/bold cyan]")
    os.execv(sys.executable, [sys.executable, str(ROOT / "main.py")])


# ── main ───────────────────────────────────────────────────────────────────────


async def main() -> None:
    step_banner()

    ok = await step_verify()
    if not ok:
        console.print("\n[red]Resuelve los problemas críticos antes de continuar.[/red]")
        sys.exit(1)

    step_api_keys()
    await step_test_models()
    step_test_permissions()
    await step_test_memory()
    step_personality()
    await step_launch()


if __name__ == "__main__":
    asyncio.run(main())
