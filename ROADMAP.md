# JARVIS — Ruta hacia asistente autónomo en macOS

> Objetivo: un asistente tipo Claude Code / OpenClaw que **actúe en el Mac** de Luichi —
> ejecuta tareas, ve la pantalla, recuerda contexto y (opcional) habla.
>
> Estado base (2026-07-02): infraestructura ~85% hecha (487 tests, 10 fases), overlay P1–P8
> verificado. **H0 ✅ (cerebro con fallback) y H1 ✅ funcional escrito**: el agente ejecuta tareas
> escribiéndole, con confirmación e2e por overlay. Detalle en `PROGRESS.md`. Esta ruta ordena lo que falta.

Leyenda: ✅ hecho · 🟡 parcial/existe sin validar · ⬜ por hacer

---

## Hito 0 — Encender el cerebro  ✅ HECHO (2026-07-01)  [DESBLOQUEA TODO]

Cerebro encendido vía **Gemini 2.5 Flash** (crédito de pago activo). El agente genera planes
válidos y ejecuta. Demostrado end-to-end con dos tareas reales.

- ✅ **Vía nube:** Gemini 2.5 Flash responde (~1.2 s, ~$0.000004/petición). Primer destino del router.
  - DeepSeek: recargado pero el top-up tarda 1–3 días en liquidar (402 hasta entonces).
  - OpenRouter: slugs `:free` caducados → 404 (bug latente: `complete()` no rota en 404; pendiente).
- ✅ Test de humo real: `agente.run("lista los archivos del escritorio")` →
  `plan → execute_tool → done` con `filesystem.listar`; y `filesystem.leer` en una 2ª tarea.
- **Bugs de camino corregidos:**
  - `main.py`: `security.permission_manager` (políticas por herramienta) nunca se instanciaba →
    skills no registraban política y la defensa de inyección del agente estaba inactiva. Cableado.
  - `reflector.evaluate_task_completion`: un plan solo de pasos `puede_fallar` se daba por completo
    antes de ejecutar (`all([]) == True`) → se saltaba la ejecución. Corregido + test de regresión.

**Criterio de hecho:** ✅ una tarea sencilla genera un plan válido y el loop llega a `EXECUTE_TOOL`
sin caer en `pedir_aclaracion` / runaway guard. **Verificado con log real.**

---

## Hito 1 — Ejecución real fiable  ✅ funcional escrito (2026-07-02)  ⏱️ colas finas (visión/lock)

Las acciones tenían tests con mocks pero **nunca se ejecutaron dirigidas por un modelo**. Se pasó
una batería e2e real (stack + Gemini) que destapó 7 bugs, todos corregidos. En 2026-07-02 se cerraron
los dos bloqueantes de usabilidad (**fallback de modelo** y **confirmación por overlay**) y se
verificaron las familias restantes (comms, "resume archivo", cerrar app). Detalle en `PROGRESS.md`.

- ✅ Batería de tareas reales end-to-end — **familias verificadas OK**:
  - ✅ abrir/cerrar apps, subir volumen (`system` — `cerrar_app` verificado 2026-07-02)
  - ✅ leer/buscar/escribir archivos (`filesystem`, escritura con confirmación)
  - ✅ ejecutar comando de terminal + Python seguro (`terminal`, con confirmación)
  - ✅ abrir URL, extraer texto y ejecutar JS (`browser`, página persistente)
  - ✅ enviar un mail (`comms`, con confirmación) — e2e 2026-07-02 (envío real a la propia dirección)
  - ✅ "resume este archivo" (`filesystem.leer` + modelo) — e2e 2026-07-02
  - 🟡 `percepcion.screenshot`: llega a `execute_tool` pero el handler devuelve solo `{"bytes":N}`
    (no la imagen) → el modelo reintira hasta el runaway guard. **Trabajo de H3 (visión).**
  - ⬜ bloquear pantalla — **no existe tool de bloqueo**; el modelo alucina éxito con `abrir_app`.
- ✅ Arreglar lo que rompa en ejecución real — 7 bugs corregidos (permission_manager sin instanciar,
  evaluate_task_completion prematura, **confirmación MCP fail-closed**, browser no registrado en el
  bus, lazy-start Playwright, Safari sin ventana, página persistente para js/click/fill).
- ✅ **Fallback de modelo real** (2026-07-02): `openrouter.complete()` rota en 404 (slug caducado),
  no solo 429/502/503; slugs `:free` reescritos con los vivos del catálogo. Verificado en vivo: con
  Gemini caído la petición responde por OpenRouter free.
- ✅ **Round-trip de confirmación por overlay P6** (2026-07-02): backend acepta `action_id` del overlay
  como confirmation_id; la rama `waiting` auto-abre el panel con la `ConfirmationCard`. Verificado e2e
  por WebSocket real: **aprobar** → escribe → `done`; **rechazar** → `error` limpio sin tocar disco.
- 🟡 Manejo de fallos reales: replanning/reflector ejercitados (runaway guard, replan). Pendiente:
  que un fallo determinista (p.ej. screenshot sin contenido útil) no consuma 3 repeticiones hasta el
  guard (abortar antes con el error real).

**Criterio de hecho:** 10/10 tareas comunes se completan e2e o fallan de forma limpia y explicada.
**Estado:** **funcional para uso escrito diario** — cerebro con fallback, confirmación e2e por overlay,
y familias system/filesystem/terminal/browser/comms + "resume archivo" ✅. Pendiente fino: visión (H3)
y tool de bloqueo de pantalla.

---

## Hito 2 — Voz  ⏱️ 3–5 días  [no existe nada aún]

Convierte "escribir en el modal" en "hablarle como a JARVIS". Módulo `voice/` a crear.

- ⬜ STT: captura de micrófono → texto (Groq Whisper, baja latencia; según diseño en jarvis.md).
- ⬜ Activación: push-to-talk (hotkey) y/o wake word.
- ⬜ TTS: respuesta hablada (Kokoro local, según diseño).
- ⬜ Integración overlay: estados "escuchando" / "hablando" en el notch (reusar fases P2).
- ⬜ Pipeline optimizado para minimizar latencia percibida.

**Criterio de hecho:** hablas → transcribe → ejecuta → responde por voz, con feedback visual.

---

## Hito 3 — Percepción y contexto proactivo  ⏱️ 2–3 días

Aprovechar lo que ya existe (OCR, accesibilidad, screenshot, detector de app activa).

- 🟡 "Mira la pantalla y…" — visión sobre screenshot dirigida por el modelo (ya hay captura + OCR).
- 🟡 Sugerencias inline según la app activa (P5 ya renderiza; falta lógica que las genere).
- ⬜ "¿Qué dice este error?" / "resume lo que veo" usando percepción real.

**Criterio de hecho:** JARVIS responde sobre el contenido de la pantalla sin copiar/pegar.

---

## Hito 4 — Memoria útil y personalización  ⏱️ 2–3 días

La maquinaria existe (ChromaDB + episódica + procedural + vault). Falta que se note.

- 🟡 Que recuerde preferencias y tareas pasadas entre sesiones y las aplique.
- ⬜ Integración con Obsidian/Notion como fuentes de contexto del usuario.
- ⬜ Aprendizaje de workflows exitosos (procedural memory) para repetir tareas más rápido.

**Criterio de hecho:** repites una tarea y JARVIS usa lo aprendido; recuerda tus preferencias.

---

## Hito 5 — Autonomía y proactividad  ⏱️ 3–5 días

- ⬜ n8n / tareas programadas: acciones proactivas (resumen diario, recordatorios).
- ⬜ Letta `request_heartbeat`: el agente decide si continuar solo (ya identificado en jarvis.md).
- ⬜ Triggers por eventos del sistema (archivo nuevo en Downloads → organizar, etc. — ya hay `vigilar_downloads`).

**Criterio de hecho:** JARVIS hace cosas útiles sin que se lo pidas explícitamente.

---

## Hito 6 — Uso diario y distribución  ⏱️ 1–2 días

- ⬜ Auto-arranque al iniciar sesión (LaunchAgent para backend + overlay).
- ⬜ Supervisión: reiniciar el backend si muere; healthcheck.
- ⬜ Onboarding de permisos macOS en frío (Accesibilidad, Screen Recording, Micrófono).
- 🟡 Auto-update del overlay (ya identificado como candidato).
- 🟡 Firma/notarización para distribución (build.sh ya lo soporta si hay Developer ID).

**Criterio de hecho:** lo enciendes una vez y vive en el Mac sin mantenimiento manual.

---

## Resumen de prioridad

| Hito | Impacto | Esfuerzo | Depende de |
|------|---------|----------|-----------|
| 0 · Cerebro | ✅ HECHO | — | — |
| 1 · Ejecución real | ✅ funcional escrito | colas finas | H0 ✅ |
| 2 · Voz | 🟠 alto (tu objetivo) | 3–5 d | H0 |
| 3 · Percepción | 🟠 medio | 2–3 d | H0 |
| 4 · Memoria | 🟡 medio | 2–3 d | H1 |
| 5 · Autonomía | 🟡 medio | 3–5 d | H1 |
| 6 · Uso diario | 🟢 acabado | 1–2 d | H1 |

**Ruta mínima a "asistente usable" = H0 + H1** (≈1 semana). Con eso ya te ejecuta tareas
escribiéndole. Añadir **H2 (voz)** lo convierte en el JARVIS que quieres.
