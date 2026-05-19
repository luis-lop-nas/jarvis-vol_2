# Skill: browser

Control del navegador web Safari en macOS.

## Herramientas

| Herramienta | Descripción | Riesgo |
|-------------|-------------|--------|
| `browser.abrir` | Navega a una URL | MEDIUM |
| `browser.leer` | Lee el contenido de la página actual | LOW |
| `browser.click` | Hace click en un elemento de la página | MEDIUM |
| `browser.fill` | Rellena un campo de formulario | MEDIUM |
| `browser.screenshot` | Captura pantalla del navegador | LOW |
| `browser.ejecutar_js` | Ejecuta JavaScript arbitrario en la página | HIGH |

## Permisos macOS

- **SCREEN_RECORDING** — requerido por `browser.screenshot`

## Riesgos

- Puede navegar a URLs arbitrarias, incluyendo sitios maliciosos.
- `browser.ejecutar_js` permite ejecutar código en el contexto de cualquier página.
- No accede a credenciales guardadas del navegador.

## Implementación

Las herramientas de este skill están implementadas en `mcp_servers/server_browser.py`
y se exponen a través del `MCPBus`. El skill declara sus políticas en `permissions.yaml`
para que el `PermissionManager` pueda tomar decisiones informadas.

## Ejemplos

```
# Navegar a una URL
browser.abrir(url="https://example.com")

# Leer contenido de la página activa
browser.leer()

# Hacer screenshot del navegador
browser.screenshot()

# Ejecutar JS (requiere confirmación)
browser.ejecutar_js(codigo="document.title")
```
