# Skill: terminal

Ejecución de comandos de shell y código Python en el sandbox de JARVIS.

## Herramientas

| Herramienta | Descripción | Riesgo |
|-------------|-------------|--------|
| `terminal.ejecutar` | Ejecuta un comando de shell | HIGH |
| `terminal.python` | Ejecuta código Python | HIGH |
| `terminal.transmitir` | Transmite un comando interactivo | HIGH |

## Permisos macOS

Ninguno adicional — el sandbox bloquea comandos destructivos.

## Riesgos

- Todas las herramientas de terminal tienen riesgo HIGH.
- El sandbox (`security/sandbox.py`) bloquea comandos `BLOCKED` y requiere confirmación para `DANGEROUS`.
- No se ejecuta código fuera del sandbox sin confirmación explícita.

## Implementación

Las herramientas están implementadas en `mcp_servers/server_code.py`
y protegidas por `security/sandbox.py`.

## Ejemplos

```
# Listar archivos con ls (SAFE)
terminal.ejecutar(comando="ls ~/Documents/JARVIS/")

# Ejecutar script Python
terminal.python(codigo="import os; print(os.getcwd())")

# Ejecutar un script interactivo
terminal.transmitir(comando="python3 script.py")
```
