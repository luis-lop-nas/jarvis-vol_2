# Skill: files

Acceso al sistema de archivos dentro del sandbox de JARVIS.

## Herramientas

| Herramienta | Descripción | Riesgo |
|-------------|-------------|--------|
| `filesystem.leer` | Lee un archivo de texto | LOW |
| `filesystem.listar` | Lista el contenido de un directorio | LOW |
| `filesystem.buscar` | Busca archivos por nombre o contenido | LOW |
| `filesystem.escribir` | Escribe o sobreescribe un archivo | MEDIUM |
| `filesystem.mover` | Mueve un archivo a otra ruta | MEDIUM |
| `filesystem.copiar` | Copia un archivo a otra ruta | MEDIUM |
| `filesystem.eliminar` | Elimina un archivo o directorio | HIGH |

## Permisos macOS

Ninguno adicional — el sandbox de JARVIS restringe las rutas accesibles.

## Riesgos

- `filesystem.eliminar` es irreversible.
- `filesystem.escribir` sobreescribe sin confirmación si el archivo ya existe.
- Todas las operaciones están restringidas al sandbox (`~/Documents/JARVIS/`).

## Implementación

Las herramientas están implementadas en `mcp_servers/server_filesystem.py`
y se protegen mediante `security/sandbox.py`.

## Ejemplos

```
# Leer un archivo
filesystem.leer(ruta="~/Documents/JARVIS/notas.txt")

# Listar un directorio
filesystem.listar(ruta="~/Documents/JARVIS/")

# Escribir un archivo (requiere confirmación)
filesystem.escribir(ruta="~/Documents/JARVIS/output.txt", contenido="Hola")

# Eliminar un archivo (requiere confirmación)
filesystem.eliminar(ruta="~/Documents/JARVIS/temp.txt")
```
