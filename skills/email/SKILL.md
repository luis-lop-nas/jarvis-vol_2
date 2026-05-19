# Skill: email

Lectura y envío de correos electrónicos vía la app Mail de macOS.

## Herramientas

| Herramienta | Descripción | Riesgo |
|-------------|-------------|--------|
| `mail.leer` | Lee correos del buzón de entrada | MEDIUM |
| `mail.enviar` | Envía un correo electrónico | HIGH |
| `mail.eliminar` | Elimina un correo permanentemente | HIGH |

## Permisos macOS

- **AUTOMATION** — para controlar la app Mail via AppleScript

## Riesgos

- `mail.enviar` envía mensajes reales. Siempre requiere confirmación.
- `mail.eliminar` es irreversible.
- `mail.leer` accede al buzón completo del usuario.

## Implementación

Las herramientas están implementadas en `mcp_servers/server_comms.py`.

## Ejemplos

```
# Leer los últimos 5 correos
mail.leer(limite=5)

# Enviar un correo (requiere confirmación)
mail.enviar(
    destinatario="juan@example.com",
    asunto="Resumen JARVIS",
    cuerpo="Te adjunto el informe de hoy."
)

# Eliminar un correo (requiere confirmación)
mail.eliminar(mensaje_id="abc123")
```
