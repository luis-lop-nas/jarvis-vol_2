# JARVIS — Progreso

> Documento vivo. Se actualiza al final de cada sesión.
> Para retomar: lee `PROGRESS.md` y `CLAUDE.md`, después continúa desde "Siguiente a implementar".

---

## Estado global

- **Fase 1 — Esqueleto del proyecto:** ✅ completada
- **Fase 2 — Sistema de modelos + router:** ✅ completada
- **Fase 3 — Memoria + MCP servers:** ⏳ pendiente
- **Fase 3b — Sistema de percepción:** ✅ completada
- **Fase 4 — Acciones + percepción:** ⏳ pendiente
- **Fase 5 — Interfaz (overlay/UI):** ⏳ pendiente

---

## ✅ Completado

### Fase 1 (2026-05-05)
- Estructura completa de paquetes en `~/Projects/jarvis`, después migrada a `jarvis-vol_2`.
- 59 archivos esqueleto con tipado estricto, docstrings en español.
- `docker-compose.yml` (ChromaDB + n8n), `Makefile`, `.env.example`, `.gitignore`, `requirements.txt`.
- Subagentes Claude Code: `architect`, `security-reviewer`, `test-writer`, `debugger`.
- `.claude/settings.json` con permisos por proyecto (allow / ask / deny).
- `.github/pull_request_template.md` y `.github/ARCHITECTURE.md` (diagramas ASCII, ADRs).
- `CLAUDE.md` con la configuración de producción.

### Fase 2 (2026-05-05)
- **`models/base.py`** — `BaseModel` (ABC), `ModelResponse`, `StreamChunk`, `ModelCapability` (Flag), `ModelConfig`, context manager async, `health_check`.
- **`models/_common.py`** — `RetryPolicy` (backoff exponencial + jitter, 429/5xx), `TTLCache` (LRU+TTL), `mensaje_a_dict` (data-URL para visión).
- **`models/kimi.py`** — Kimi K2.6 vía httpx, `complete_with_thinking()`, tool_use, vision, caché 5 min, retry 3×, log de tokens.
- **`models/deepseek.py`** — V3.2 chat/reasoner híbrido por `complejidad`, conciencia de `prompt_cache_hit_tokens`, coste USD por llamada con tarifas oficiales en `TARIFAS_USD`.
- **`models/ollama_client.py`** — detección de modelos al arrancar, control de RAM (`ollama_max_ram_gb`), descarga del modelo anterior con `keep_alive=0`, fallback a modelo más pequeño, `tokens_per_second` por respuesta.
- **`models/openrouter.py`** — selector automático de free-tier, lista `MODELOS_FREE_PREFERIDOS`.
- **`models/embeddings.py`** — `EmbeddingsClient` con caché persistente SQLite (`CacheEmbeddings`), normalización L2, dimensión 768; aliases compatibles con `memory/`.
- **`core/router.py`** — `ModelRouter.route()` → `ModelSelection(model_name, razon, fallback_chain, complejidad, decision_ms)`. Reglas en orden: preferencia local → datos sensibles → sin internet → visión → compleja+código → embeddings → razonamiento → default. `detect_sensitive_data` escanea texto + nombres de archivo + historial. `estimate_complexity ∈ [0,1]`.
- **Tests** — `tests/test_router.py` (30) + `tests/test_models.py` (23). Resultado: **53/53 verde en ~1.2 s**.
- **Adaptaciones** — `core/agent.py`, `core/planner.py`, `core/reflector.py`, `main.py` migrados al nuevo `ModelResponse.content` y `ModelRouter`.
- **`pyproject.toml`** con `asyncio_mode="auto"`, ruff, mypy strict.
- **`.env.example` y `config/settings.py`** alineados con las variables nuevas (Kimi K2.6, DeepSeek V3.2, Ollama, Router, `embed_cache_path`).
- `psutil>=6.0.0` añadido a `requirements.txt`.

### Fase 3b — Sistema de percepción (2026-05-09)
- **`perception/screenshot.py`** — `capture_screen()`, `capture_region()`, `capture_window()`, `capture_to_file()`, `encode_for_vision()`. Rate limiter 2fps, escala 1x automática en M3 retina vía `NSScreen.backingScaleFactor`.
- **`perception/ocr.py`** — `extract_text()` (auto), `extract_text_local()` (Tesseract), `extract_text_vision()` (Kimi Vision API), `extract_structured()`. Caché SHA-256 TTL 30s. Estrategia: >500KB → local first; confianza < 60 → Vision.
- **`perception/accessibility.py`** — `get_frontmost_app()`, `get_active_window()`, `get_focused_element()`, `get_window_tree()`, `get_browser_url()`, `get_browser_page_title()`, `get_selected_text()`, `is_app_running()`, `wait_for_element()`. Dataclasses: `AppInfo`, `WindowInfo`, `ElementInfo`, `Bounds`, `ElementTree`. Permiso AX verificado en cada llamada; devuelve None si no está concedido.
- **`perception/system_state.py`** — `SystemState` (13 campos), `get_system_state()` (recolección paralela), `watch_state()`, `is_busy()`, `context_summary()`. Usa psutil para RAM/CPU/batería; `networksetup` para WiFi; Quartz para pantalla bloqueada; `defaults read` para DnD.
- **`perception/__init__.py`** — Reescrito con todos los exports del módulo.
- **Tests** — `tests/test_perception.py` (7/7 verde). Total suite: **60/60 verde**.
- **Dependencias** — Sin cambios en `requirements.txt`; todo ya estaba listado (psutil, pytesseract, Pillow, pyobjc-framework-*).

---

## 🔄 En progreso

_(nada activo en este momento)_

---

## ⏳ Siguiente a implementar (Fase 3)

Memoria real + bus MCP que conecte el agente con las acciones:

1. **`memory/long_term.py`** — completar la integración con ChromaDB usando `EmbeddingsClient` ya cacheado. Tests con `EphemeralClient`.
2. **`memory/episodic.py` y `memory/procedural.py`** — flujos de guardado de aprendizajes desde el `Reflector` y de skills reutilizables.
3. **Bus MCP en `core/agent.py`** — quitar el `NotImplementedError` de `_ejecutar_paso` y enrutar la herramienta del paso al `mcp_servers/*` correspondiente.
4. **`mcp_servers/server_filesystem.py`** — primer servidor 100 % testeado (lectura/escritura/listar) con tests que prueben el sandbox de raíz.
5. **`security/confirmation.py`** — implementar callbacks reales (notificación nativa macOS y prompt en el WebSocket) en vez del fail-closed por defecto.

Tests mínimos para cerrar la fase:
- `tests/memory/test_long_term.py` — round-trip embed→guardar→buscar.
- `tests/test_agent.py` — flujo end-to-end con MCP mock y confirmación auto-aprobada.

---

## 🧠 Decisiones técnicas registradas

### 2026-05-05 (Fase 1)
- ADR-1: Router como guardián de privacidad (no el agente).
- ADR-2: Side effects solo en `actions/`, expuestos vía MCP servers.
- ADR-3: Embeddings siempre locales (Ollama).
- ADR-4: `core/` no importa `actions/` directamente.
- ADR-5: Confirmación humana fail-closed (timeout = denegado).
- ADR-6: Audit log JSONL append-only, sin rotación automática.

### 2026-05-09 (Fase 3b — Percepción)
- ADR-14: **screencapture CLI en vez de Quartz directo** — en M3 el binding Python→ObjC añade latencia en capturas grandes; el subproceso devuelve PNG comprimido directamente.
- ADR-15: **Rate limiter por asyncio.Lock en screenshot** — 2fps hardcodeado a nivel de módulo para no saturar el pipeline de visión.
- ADR-16: **Caché de OCR por SHA-256 con TTL 30s** — evita reprocesar el mismo frame capturado varias veces seguidas.
- ADR-17: **Estrategia OCR automática por tamaño** — >500KB local primero (evita subir datos grandes); confianza Tesseract < 60 → fallback a Vision API.
- ADR-18: **Permiso AX verificado en cada llamada** — devuelve None silencioso en vez de lanzar; el agente debe comprobar permisos en startup.
- ADR-19: **system_state recolecta en paralelo con asyncio.gather** — CPU, RAM, batería, WiFi, DnD y apps activas se obtienen simultáneamente.

### 2026-05-05 (Fase 2)
- ADR-7: **httpx puro en lugar del SDK de OpenAI** para Kimi/DeepSeek/OpenRouter — control total del cuerpo, una sola ruta de manejo de errores, tests fáciles con `MockTransport`.
- ADR-8: **Caché de embeddings en SQLite con `struct.pack("Nf")`** en lugar de JSON — ~3× menos espacio y deserialización más rápida.
- ADR-9: **`enum.Flag` para `ModelCapability`** — combinable con `|`, comprobable con `cap in capabilities`.
- ADR-10: **Fallback chain como dato, no condicional** — cada destino tiene su lista; local nunca cae a remoto (privacidad first); remoto siempre acaba en local.
- ADR-11: **Detección de internet por TCP a `1.1.1.1:53` cacheada 30 s** — evita un syscall por cada `route()`.
- ADR-12: **`complete_with_thinking()` solo en Kimi**; en DeepSeek el modo thinking se activa con `complejidad>=0.65` en `complete()`. Dos APIs distintas porque son dos comportamientos distintos.
- ADR-13: **Sin tarifas inventadas** — solo DeepSeek expone `cost_usd` real. Kimi/OpenRouter dejan `cost_usd=0.0`.

---

## 📋 Notas y deudas técnicas

### Permisos macOS necesarios (perception/)
- **Accesibilidad** — Sistema → Privacidad → Accesibilidad → añadir el proceso. Sin este permiso todas las funciones de `accessibility.py` devuelven None.
- **Grabación de pantalla** — Sistema → Privacidad → Grabación de pantalla → añadir el proceso. Sin este permiso `screencapture` devuelve imagen negra.
- `main.py` debe llamar a `solicitar_permiso_accesibilidad()` en startup si `verificar_permiso_accesibilidad()` devuelve False.

### Deudas previas
- `core/agent.py::_ejecutar_paso` lanza `NotImplementedError` — bloqueante para Fase 3.
- `actions/comms/mail.py::listar_no_leidos` devuelve `[]` (placeholder explícito).
- `pyobjc-framework-*` solo se importan dentro de los métodos para no romper en Linux/CI.
- Pylance avisa de parámetros sin usar en `__aexit__`; es esperado (firma del protocolo).
- No instalado todavía en el venv del proyecto: dependencias pesadas (chromadb, playwright, fastapi). `make install` las instala todas la primera vez.

---

## 🚀 Cómo retomar

```
1. Lee PROGRESS.md y CLAUDE.md.
2. Si arrancas una sesión nueva con Claude Code, dile:
   "Lee PROGRESS.md y CLAUDE.md y continúa desde donde lo dejamos."
3. Antes de tocar código nuevo:
   - Comprueba que `make test` sigue verde.
   - Si vas a tocar varios paquetes, invoca `@architect` primero.
```
