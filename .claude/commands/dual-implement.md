---
description: Implementación paralela Claude + Codex. Codex intenta la tarea en background mientras Claude la implementa en foreground. Compara ambos y aplica el mejor resultado.
argument-hint: '<descripción de la tarea a implementar>'
allowed-tools: Read, Glob, Grep, Edit, Write, Bash(node:*), Bash(git:*), Bash(python3:*), Bash(pytest:*)
---

## Implementación dual: Claude + Codex en paralelo

Tarea: `$ARGUMENTS`

### Paso 1 — Delega la tarea a Codex en background

```
node "/Users/luichi/.claude/plugins/cache/openai-codex/codex/1.0.4/scripts/codex-companion.mjs" rescue --background $ARGUMENTS
```

Confirma: "Codex trabajando en background. Implementando en paralelo."

### Paso 2 — Tu implementación (foreground)

Implementa la tarea respetando las reglas de JARVIS (CLAUDE.md):
- Python 3.12+ con tipado estricto en todos los parámetros y retornos
- Async/await por defecto — sin llamadas bloqueantes
- Pydantic para todas las estructuras de datos
- Docstrings en español con ejemplo de uso
- Side effects solo en `actions/`, nunca directo desde `core/`
- Escribe el test junto con la implementación

### Paso 3 — Ejecuta los tests

```
pytest tests/ -x -q
```

Si fallan, corrige antes de continuar.

### Paso 4 — Recoge la propuesta de Codex

```
node "/Users/luichi/.claude/plugins/cache/openai-codex/codex/1.0.4/scripts/codex-companion.mjs" result --json
```

Si Codex no ha terminado todavía, muestra tu implementación y deja que el usuario espere con `/codex:result`.

### Paso 5 — Compara y decide

Evalúa lado a lado:
| Criterio | Claude | Codex |
|---|---|---|
| Adherencia a reglas JARVIS | | |
| Cobertura de edge cases | | |
| Seguridad | | |
| Legibilidad | | |

Aplica la mejor implementación (o un merge razonado de ambas).
Explica al usuario en 2-3 frases qué decidiste y por qué.
