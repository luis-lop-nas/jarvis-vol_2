"""Servidor MCP que expone control del sistema (apps, notificaciones)."""

from __future__ import annotations

from typing import Any

from actions.system import ControlSistema
from perception.system_state import EstadoSistema


class ServidorSistema:
    """Bridge MCP <-> macOS."""

    nombre = "system"

    def __init__(self) -> None:
        self._control = ControlSistema()
        self._estado = EstadoSistema()

    def herramientas(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "abrir_app",
                "description": "Abre una aplicación por nombre o bundle id.",
                "input_schema": {
                    "type": "object",
                    "properties": {"nombre": {"type": "string"}},
                    "required": ["nombre"],
                },
            },
            {
                "name": "notificar",
                "description": "Envía una notificación nativa.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "titulo": {"type": "string"},
                        "mensaje": {"type": "string"},
                        "sonido": {"type": "boolean", "default": False},
                    },
                    "required": ["titulo", "mensaje"],
                },
            },
            {
                "name": "snapshot_sistema",
                "description": "Devuelve el estado actual del sistema.",
                "input_schema": {"type": "object", "properties": {}},
            },
        ]

    async def ejecutar(self, herramienta: str, argumentos: dict[str, Any]) -> Any:
        match herramienta:
            case "abrir_app":
                await self._control.abrir_app(argumentos["nombre"])
                return {"ok": True}
            case "notificar":
                await self._control.notificar(
                    argumentos["titulo"],
                    argumentos["mensaje"],
                    argumentos.get("sonido", False),
                )
                return {"ok": True}
            case "snapshot_sistema":
                snap = await self._estado.snapshot()
                return {
                    "apps": [a.__dict__ for a in snap.apps],
                    "bateria": snap.porcentaje_bateria,
                    "cargando": snap.cargando,
                    "red": snap.nombre_red,
                }
            case _:
                raise ValueError(f"Herramienta desconocida: {herramienta}")
