---
description: Revisión paralela Claude + Codex. Claude analiza debilidades en foreground mientras Codex hace adversarial review en background. Presenta ambos resultados combinados.
argument-hint: '[--base <ref>] [archivos o módulo opcional]'
allowed-tools: Read, Glob, Grep, Bash(node:*), Bash(git:*)
---

## Revisión dual: Claude + Codex en paralelo

Argumentos recibidos: `$ARGUMENTS`

### Paso 1 — Lanza Codex adversarial review en background

Ejecuta en background:
```
node "/Users/luichi/.claude/plugins/cache/openai-codex/codex/1.0.4/scripts/codex-companion.mjs" adversarial-review --background $ARGUMENTS
```

Confirma al usuario: "Codex adversarial review iniciado en background."

### Paso 2 — Tu revisión independiente (mientras Codex trabaja)

Revisa en profundidad el scope indicado en $ARGUMENTS (o todo el proyecto si está vacío).
Analiza y lista debilidades con severidad:
- 🔴 Crítico — fallo de seguridad, corrupción de datos, race condition
- 🟡 Medio — violación de ADR, falta de manejo de error, tipo incorrecto
- 🟢 Menor — estilo, nombre confuso, comentario que falta

Reglas de JARVIS a verificar:
- Side effects solo en `actions/`, nunca en `core/`
- Router es el único que decide modelo — agente no toca modelos directamente
- Toda operación con filesystem/comms/sistema requiere confirmación explícita
- Async/await en todo, sin llamadas bloqueantes en el hilo principal
- Tipado estricto Python 3.12+ con Pydantic para estructuras de datos

### Paso 3 — Recoge los resultados de Codex

```
node "/Users/luichi/.claude/plugins/cache/openai-codex/codex/1.0.4/scripts/codex-companion.mjs" result --json
```

Si Codex aún no ha terminado, muestra tu análisis primero e indica al usuario que ejecute `/codex:result` cuando esté listo.

### Paso 4 — Síntesis combinada

Presenta:
1. **Hallazgos de Claude** — lista priorizada por severidad
2. **Hallazgos de Codex** — verbatim, sin resumir
3. **Lista consolidada** — problemas encontrados por ambos primero, luego los de uno solo

Termina preguntando: "¿Qué problemas atacamos primero?"
