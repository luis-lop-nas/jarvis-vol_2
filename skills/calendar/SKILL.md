# Skill: calendar

Acceso al Calendario de macOS para listar, crear y eliminar eventos.

## Herramientas

| Herramienta | Descripción | Riesgo |
|-------------|-------------|--------|
| `calendar.listar` | Lista eventos de los próximos N días | LOW |
| `calendar.crear` | Crea un nuevo evento en el calendario | MEDIUM |
| `calendar.eliminar` | Elimina un evento del calendario | HIGH |

## Permisos macOS

- **AUTOMATION** — requerido para controlar la app Calendar via AppleScript

## Riesgos

- `calendar.crear` puede crear eventos duplicados si se llama múltiples veces.
- `calendar.eliminar` es irreversible.
- `calendar.listar` expone eventos privados del usuario.

## Implementación

Este skill implementa sus herramientas directamente en `tools.py` usando
`osascript` (AppleScript) para interactuar con la app Calendar de macOS.
No depende de un MCP server externo.

## Ejemplos

```
# Ver eventos de los próximos 7 días
calendar.listar(dias=7)

# Crear un evento (requiere confirmación)
calendar.crear(
    titulo="Reunión JARVIS",
    fecha="2026-05-20",
    hora_inicio="10:00",
    hora_fin="11:00",
    calendario="Trabajo"
)

# Eliminar un evento (requiere confirmación)
calendar.eliminar(evento_id="ABC123")
```
