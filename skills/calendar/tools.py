"""Herramientas del skill calendar — acceso al Calendario macOS via osascript.

Este skill implementa sus callables directamente (no depende de un MCP server).
Requiere permiso AUTOMATION en macOS para controlar la app Calendar.

Ejemplo::
    from skills.calendar.tools import TOOLS
    resultado = await TOOLS["calendar.listar"](dias=7)
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import date, timedelta
from typing import Any

log = logging.getLogger(__name__)

_IS_MACOS = sys.platform == "darwin"


async def _osascript(script: str) -> str:
    """Ejecuta un script AppleScript y devuelve stdout."""
    if not _IS_MACOS:
        raise RuntimeError("calendar.tools requiere macOS")
    proc = await asyncio.create_subprocess_exec(
        "osascript", "-e", script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        msg = stderr.decode().strip()
        raise RuntimeError(f"osascript error: {msg}")
    return stdout.decode().strip()


async def calendar_listar(dias: int = 7, calendario: str = "") -> dict[str, Any]:
    """Lista eventos del calendario de los próximos N días.

    Ejemplo::
        resultado = await calendar_listar(dias=7)
        print(resultado["eventos"])
    """
    hoy = date.today()
    fin = hoy + timedelta(days=dias)

    filtro_cal = f'whose name is "{calendario}"' if calendario else ""
    script = f"""
    set fechaInicio to date "{hoy.strftime("%Y-%m-%d")}"
    set fechaFin to date "{fin.strftime("%Y-%m-%d")}"
    set salida to {{}}
    tell application "Calendar"
        set calendarList to every calendar {filtro_cal}
        repeat with cal in calendarList
            set eventos to (every event of cal whose start date >= fechaInicio and start date <= fechaFin)
            repeat with ev in eventos
                set uid to uid of ev
                set titulo to summary of ev
                set inicio to start date of ev as string
                set fin_ev to end date of ev as string
                set entrada to uid & "|" & titulo & "|" & inicio & "|" & fin_ev & "|" & (name of cal)
                set end of salida to entrada
            end repeat
        end repeat
    end tell
    set AppleScript's text item delimiters to linefeed
    return salida as text
    """
    try:
        raw = await _osascript(script)
    except RuntimeError as exc:
        return {"error": str(exc), "eventos": []}

    eventos = []
    for linea in raw.splitlines():
        partes = linea.split("|")
        if len(partes) == 5:
            eventos.append({
                "id": partes[0].strip(),
                "titulo": partes[1].strip(),
                "inicio": partes[2].strip(),
                "fin": partes[3].strip(),
                "calendario": partes[4].strip(),
            })

    return {"eventos": eventos, "total": len(eventos), "dias": dias}


async def calendar_crear(
    titulo: str,
    fecha: str,
    hora_inicio: str,
    hora_fin: str,
    calendario: str = "",
    notas: str = "",
) -> dict[str, Any]:
    """Crea un nuevo evento en el calendario macOS.

    Ejemplo::
        resultado = await calendar_crear(
            titulo="Reunión",
            fecha="2026-05-20",
            hora_inicio="10:00",
            hora_fin="11:00",
        )
    """
    inicio_str = f"{fecha} {hora_inicio}"
    fin_str = f"{fecha} {hora_fin}"
    cal_clause = f'calendar "{calendario}"' if calendario else "first calendar"
    notas_clause = f'set description of nuevo_evento to "{notas}"' if notas else ""

    script = f"""
    tell application "Calendar"
        set cal to {cal_clause}
        set nuevo_evento to make new event at end of events of cal with properties {{summary:"{titulo}", start date:date "{inicio_str}", end date:date "{fin_str}"}}
        {notas_clause}
        set evento_uid to uid of nuevo_evento
    end tell
    return evento_uid
    """
    try:
        uid = await _osascript(script)
        return {"creado": True, "evento_id": uid, "titulo": titulo}
    except RuntimeError as exc:
        return {"creado": False, "error": str(exc)}


async def calendar_eliminar(evento_id: str) -> dict[str, Any]:
    """Elimina un evento del calendario por su UID.

    Ejemplo::
        resultado = await calendar_eliminar(evento_id="abc123")
    """
    script = f"""
    tell application "Calendar"
        set objetivo to (first event of (every calendar) whose uid is "{evento_id}")
        if objetivo is not {{}} then
            delete first item of objetivo
            return "eliminado"
        else
            return "no_encontrado"
        end if
    end tell
    """
    try:
        resultado = await _osascript(script)
        if resultado == "eliminado":
            return {"eliminado": True, "evento_id": evento_id}
        return {"eliminado": False, "motivo": "Evento no encontrado"}
    except RuntimeError as exc:
        return {"eliminado": False, "error": str(exc)}


TOOLS: dict[str, Any] = {
    "calendar.listar": calendar_listar,
    "calendar.crear": calendar_crear,
    "calendar.eliminar": calendar_eliminar,
}
