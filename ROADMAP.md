# JARVIS — Ruta hacia asistente autónomo en macOS

> Objetivo: un asistente tipo Claude Code / OpenClaw que **actúe en el Mac** de Luichi —
> ejecuta tareas, ve la pantalla, recuerda contexto y (opcional) habla.
>
> Estado base (2026-07-01): infraestructura ~85% hecha (467 tests, 10 fases), overlay P1–P8
> verificado. **Bloqueante: no hay un LLM capaz respondiendo** → el agente no ejecuta tareas.
> Detalle en `PROGRESS.md`. Esta ruta ordena lo que falta por impacto.

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

## Hito 1 — Ejecución real fiable  ⏱️ 2–4 días

Las acciones tienen tests con mocks pero **nunca se ejecutaron dirigidas por un modelo**.
Aquí saldrán los bugs del mundo real.

- ⬜ Batería de 10 tareas reales end-to-end, p.ej.:
  - abrir/cerrar apps, subir volumen, bloquear pantalla (`system`)
  - leer/buscar/mover archivos (`filesystem`)
  - ejecutar comando de terminal seguro (`terminal`)
  - abrir URL y extraer texto (`browser`)
  - enviar un iMessage/mail (`comms`, con confirmación)
  - "resume este PDF/archivo" (percepción + memoria)
- ⬜ Arreglar lo que rompa en ejecución real (paths, permisos macOS, timeouts, parsing).
- 🟡 Verificar el **flujo de confirmación completo** en real (overlay P6 ↔ backend resolve).
- ⬜ Verificar escritura física en el modal (el auto-foco ya se ve; falta confirmación manual).
- ⬜ Manejo de fallos reales: replanning y reflector con errores de verdad, no simulados.

**Criterio de hecho:** 10/10 tareas comunes se completan e2e o fallan de forma limpia y explicada.

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
| 1 · Ejecución real | 🔴 alto | 2–4 d | H0 |
| 2 · Voz | 🟠 alto (tu objetivo) | 3–5 d | H0 |
| 3 · Percepción | 🟠 medio | 2–3 d | H0 |
| 4 · Memoria | 🟡 medio | 2–3 d | H1 |
| 5 · Autonomía | 🟡 medio | 3–5 d | H1 |
| 6 · Uso diario | 🟢 acabado | 1–2 d | H1 |

**Ruta mínima a "asistente usable" = H0 + H1** (≈1 semana). Con eso ya te ejecuta tareas
escribiéndole. Añadir **H2 (voz)** lo convierte en el JARVIS que quieres.
