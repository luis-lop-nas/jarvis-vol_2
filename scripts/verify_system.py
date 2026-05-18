#!/usr/bin/env python3
"""
Verifica que todos los componentes de JARVIS están listos.
Ejecutar antes del primer arranque: python scripts/verify_system.py
"""
import asyncio
import subprocess
import sys

import httpx
import psutil
from rich.console import Console
from rich.table import Table

console = Console()


async def verify_all() -> bool:
    """
    Verifica todos los componentes necesarios.
    Devuelve True si todo está listo, False si hay problemas críticos.
    """
    table = Table(title="JARVIS — Verificación del sistema")
    table.add_column("Componente", style="cyan")
    table.add_column("Estado", style="green")
    table.add_column("Detalle")

    critical_failed: list[str] = []
    models: list[str] = []

    # Python version
    py = sys.version_info
    ok = py >= (3, 12)
    table.add_row("Python", "✓" if ok else "✗", f"{py.major}.{py.minor}.{py.micro}")
    if not ok:
        critical_failed.append("Python 3.12+ requerido")

    # ChromaDB (modo local: chroma run; modo docker: docker-compose up -d)
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get("http://localhost:8000/api/v2/heartbeat", timeout=3)
            ok = r.status_code == 200
    except Exception:
        ok = False
    table.add_row("ChromaDB", "✓" if ok else "✗", ":8000 (local)")
    if not ok:
        critical_failed.append("ChromaDB no responde — ejecuta: make services-start")

    # Ollama + modelos
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get("http://localhost:11434/api/tags", timeout=3)
            models = [m["name"] for m in r.json().get("models", [])]
            ollama_ok = True
            detail = f"{len(models)} modelos"
    except Exception:
        ollama_ok = False
        detail = "no responde"
    table.add_row("Ollama", "✓" if ollama_ok else "✗", detail)
    if not ollama_ok:
        critical_failed.append("Ollama no responde — ejecuta: ollama serve")

    # nomic-embed-text (requerido para embeddings)
    embed_ok = any("nomic-embed-text" in m for m in models)
    table.add_row("nomic-embed-text", "✓" if embed_ok else "✗", "embeddings locales")
    if not embed_ok:
        critical_failed.append("nomic-embed-text no encontrado — ejecuta: ollama pull nomic-embed-text")

    # gemma4:4b (modelo local rápido)
    gemma_ok = any("gemma4:4b" in m for m in models)
    table.add_row("gemma4:4b", "✓" if gemma_ok else "⚠", "modelo local rápido")

    # 1Password CLI (opcional)
    op_ok = subprocess.run(["which", "op"], capture_output=True).returncode == 0
    table.add_row("1Password CLI", "✓" if op_ok else "⚠", "opcional para vault")

    # Tesseract OCR (opcional)
    tess_ok = subprocess.run(["which", "tesseract"], capture_output=True).returncode == 0
    table.add_row("Tesseract", "✓" if tess_ok else "⚠", "OCR local")

    # API keys
    try:
        import sys as _sys
        _sys.path.insert(0, ".")
        from config.settings import settings

        kimi_ok = bool(
            settings.kimi_api_key
            and settings.kimi_api_key.get_secret_value() not in ("", "your_kimi_api_key_here")
        )
        deepseek_ok = bool(
            settings.deepseek_api_key
            and settings.deepseek_api_key.get_secret_value() not in ("", "your_deepseek_api_key_here")
        )
    except Exception:
        kimi_ok = deepseek_ok = False

    table.add_row("Kimi API Key", "✓" if kimi_ok else "✗", "cerebro principal")
    table.add_row("DeepSeek API Key", "✓" if deepseek_ok else "⚠", "fallback económico")
    if not kimi_ok:
        critical_failed.append("kimi_api_key no configurada en .env")

    # RAM disponible
    ram_gb = psutil.virtual_memory().available / (1024 ** 3)
    ok = ram_gb >= 2.0
    table.add_row("RAM disponible", "✓" if ok else "⚠", f"{ram_gb:.1f} GB libres")

    # Permiso Accessibility macOS
    try:
        import ApplicationServices  # type: ignore[import]
        ax_ok = bool(ApplicationServices.AXIsProcessTrusted())
    except Exception:
        ax_ok = False
    table.add_row("Accessibility", "✓" if ax_ok else "✗", "requerido para control de apps")
    if not ax_ok:
        critical_failed.append("Permiso Accessibility no concedido — Ajustes → Privacidad → Accesibilidad")

    console.print(table)

    if critical_failed:
        console.print("\n[red]❌ Problemas críticos:[/red]")
        for p in critical_failed:
            console.print(f"  • {p}")
        return False

    console.print("\n[green]✅ Sistema listo para arrancar JARVIS[/green]")
    console.print("   Ejecuta: [bold]python main.py[/bold]")
    return True


if __name__ == "__main__":
    ok = asyncio.run(verify_all())
    sys.exit(0 if ok else 1)
