"""Tipos compartidos para el bus MCP interno de JARVIS."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

TipoJsonSchema = Literal["string", "integer", "number", "boolean", "array", "object"]


class MCPRequest(BaseModel):
    """Solicitud normalizada para ejecutar una herramienta MCP.

    Ejemplo::
        req = MCPRequest(tool_name="filesystem.leer", params={"ruta": "README.md"})
    """

    tool_name: str
    params: dict[str, Any] = Field(default_factory=dict)
    session_id: str = ""
    requires_confirmation: bool = False


class MCPResult(BaseModel):
    """Resultado normalizado de una llamada MCP.

    Ejemplo::
        MCPResult(success=True, data={"ok": True}, duration_ms=12)
    """

    success: bool
    data: Any = None
    error: str | None = None
    duration_ms: int = 0
    side_effects: list[str] = Field(default_factory=list)
    tool_name: str = ""


class MCPTool(BaseModel):
    """Descripción de una herramienta expuesta por un servidor MCP."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    requires_confirmation: bool = False
    side_effects: list[str] = Field(default_factory=list)
    annotations: dict[str, Any] = Field(default_factory=dict)

    def to_protocol_dict(self) -> dict[str, Any]:
        """Convierte la herramienta al formato `tools/list` del protocolo MCP.

        Returns:
            Diccionario serializable con nombre, descripción, schema y anotaciones.
        """
        annotations = {
            "readOnlyHint": not self.side_effects and not self.requires_confirmation,
            "destructiveHint": any(
                effect.endswith(".delete") or effect.endswith(".move")
                for effect in self.side_effects
            ),
            "idempotentHint": False,
            "openWorldHint": bool(self.side_effects),
        }
        annotations.update(self.annotations)
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema or schema_objeto(),
            "annotations": annotations,
        }


class MCPServer(Protocol):
    """Contrato mínimo que implementan los servidores MCP internos."""

    nombre: str

    def herramientas(self) -> list[MCPTool]:
        """Devuelve las herramientas expuestas por el servidor."""
        ...

    async def ejecutar(self, tool_name: str, params: dict[str, Any]) -> Any:
        """Ejecuta una herramienta declarada por el servidor."""
        ...


def serializar_dato(valor: Any) -> Any:
    """Convierte resultados Python en estructuras JSON-friendly.

    Args:
        valor: Objeto devuelto por una acción o servidor.

    Returns:
        Valor compuesto por tipos simples, listas y diccionarios.
    """
    if isinstance(valor, BaseModel):
        return serializar_dato(valor.model_dump())
    if is_dataclass(valor) and not isinstance(valor, type):
        return serializar_dato(asdict(valor))
    if isinstance(valor, dict):
        return {str(k): serializar_dato(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple, set, frozenset)):
        return [serializar_dato(v) for v in valor]
    if isinstance(valor, Path):
        return str(valor)
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, bytes):
        return {"bytes": len(valor)}
    return valor


def schema_objeto(
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
    *,
    additional_properties: bool = False,
) -> dict[str, Any]:
    """Construye un JSON Schema pequeño para entradas de herramientas.

    Args:
        properties: Propiedades aceptadas por la herramienta.
        required: Nombres de propiedades obligatorias.
        additional_properties: Si se permiten propiedades no declaradas.

    Returns:
        JSON Schema compatible con MCP `inputSchema`.
    """
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties or {},
        "additionalProperties": additional_properties,
    }
    if required:
        schema["required"] = required
    return schema


def campo(
    tipo: TipoJsonSchema,
    descripcion: str,
    **restricciones: Any,
) -> dict[str, Any]:
    """Construye la definición de un campo JSON Schema.

    Args:
        tipo: Tipo JSON básico.
        descripcion: Descripción humana del parámetro.
        **restricciones: Restricciones adicionales como `minimum` o `items`.

    Returns:
        Diccionario de schema para una propiedad.
    """
    return {"type": tipo, "description": descripcion, **restricciones}


def validar_parametros(params: dict[str, Any], schema: dict[str, Any]) -> list[str]:
    """Valida parámetros contra el subconjunto JSON Schema usado por JARVIS.

    Args:
        params: Parámetros recibidos por el bus.
        schema: Schema declarado por `MCPTool.input_schema`.

    Returns:
        Lista de errores humanos; vacía si los parámetros son válidos.
    """
    errores: list[str] = []
    requeridos = [str(item) for item in schema.get("required", [])]
    for nombre in requeridos:
        if nombre not in params:
            errores.append(f"falta parámetro requerido '{nombre}'")

    propiedades = dict(schema.get("properties", {}))
    if schema.get("additionalProperties") is False:
        extra = sorted(set(params) - set(propiedades))
        if extra:
            errores.append(f"parámetros no permitidos: {', '.join(extra)}")

    for nombre, valor in params.items():
        definicion = propiedades.get(nombre)
        if not isinstance(definicion, dict) or "type" not in definicion:
            continue
        esperado = definicion["type"]
        if isinstance(esperado, list):
            tipos = [str(t) for t in esperado]
        else:
            tipos = [str(esperado)]
        if not _tipo_valido(valor, tipos):
            errores.append(
                f"parámetro '{nombre}' debe ser {', '.join(tipos)} "
                f"y llegó {type(valor).__name__}"
            )
    return errores


def _tipo_valido(valor: Any, tipos: list[str]) -> bool:
    """Comprueba si un valor encaja con tipos JSON Schema básicos.

    Args:
        valor: Valor recibido.
        tipos: Tipos JSON permitidos.

    Returns:
        `True` si el valor cumple al menos uno de los tipos.
    """
    for tipo in tipos:
        match tipo:
            case "string":
                if isinstance(valor, str):
                    return True
            case "integer":
                if isinstance(valor, int) and not isinstance(valor, bool):
                    return True
            case "number":
                if isinstance(valor, (int, float)) and not isinstance(valor, bool):
                    return True
            case "boolean":
                if isinstance(valor, bool):
                    return True
            case "array":
                if isinstance(valor, list):
                    return True
            case "object":
                if isinstance(valor, dict):
                    return True
    return False
