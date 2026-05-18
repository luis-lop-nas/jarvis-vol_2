# JARVIS — Progreso

> Documento vivo. Se actualiza al final de cada sesión.
> Para retomar: lee `PROGRESS.md` y `CLAUDE.md`, después continúa desde "Siguiente a implementar".

---

## Estado global

- **Fase 1 — Esqueleto del proyecto:** ✅ completada
- **Fase 2 — Sistema de modelos + router:** ✅ completada
- **Fase 3 — Memoria base:** ✅ completada
- **Fase 3b — Sistema de percepción:** ✅ completada
- **Fase 4 — Acciones:** ✅ completada
- **Fase 5 — Loop principal del agente:** ✅ completada
- **Fase 6 — Sistema completo de memoria:** ✅ completada
- **Fase 7 — MCP servers:** ⏳ pendiente

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

### Fase 6 — Sistema completo de memoria (2026-05-18)
- **`memory/short_term.py`** — `Message` Pydantic y `ShortTermMemory` async con buffer en memoria, ventana por tokens, búsqueda keyword, `to_langchain_messages()`, resumen automático al exceder 100 mensajes u 8000 tokens, y alias compatible `MemoriaCortoPlazo`.
- **`memory/long_term.py`** — `MemoryEntry` Pydantic y `LongTermMemory` con ChromaDB HTTP + embeddings locales `nomic-embed-text` vía `EmbeddingsClient`; store/search/search_hybrid/get/update/delete/categorías/recientes/importantes/count/build_context. Metadatos serializados a JSON plano para cumplir restricciones de ChromaDB.
- **Colecciones ChromaDB previstas/creadas por nombre:** `jarvis_memory` (principal), `jarvis_documents` (documentos procesados) y `jarvis_workflows` (patrones aprendidos). La implementación crea la colección usada bajo demanda con `get_or_create_collection`; workflows usan `jarvis_workflows` cuando se instancia el store dedicado.
- **`memory/episodic.py`** — `Episode`, `EpisodicStats` y `EpisodicMemory`: registro de episodios, recuperación semántica, fallos recientes, lecciones con LLM opcional, mejor enfoque histórico y estadísticas.
- **`memory/procedural.py`** — `Workflow` y `ProceduralMemory`: guardado, búsqueda semántica por patrones, aprendizaje desde episodios exitosos, actualización de estadísticas, export YAML y alias `MemoriaProcedural`.
- **`memory/vault.py`** — `VaultItem` y `Vault`: integración async con 1Password CLI (`op`), autorización Face ID inyectable/fail-closed, timeout configurable, listado, login/API key/password y notas seguras. Nunca registra valores secretos y muestra instrucción clara si falta `op`.
- **`memory/__init__.py`** — `MemorySystem` como fachada única: `store_interaction`, `get_context`, `record_episode`, `find_workflow`, `get_secret`, `clear_session`, `health_check`.
- **`core/agent.py`** — Integrado con `MemorySystem`: `AgentState.memory_context`, contexto en `_percibir`, workflow antes de planificar, almacenamiento de interacciones y registro de episodios al completar planes.
- **`config/settings.py`** — Añadidos `chroma_host`, `chroma_port`, `chroma_collection`, `short_term_max_tokens`, `short_term_max_messages`, `memory_importance_threshold`, `vault_timeout_seconds`.
- **`tests/test_memory.py`** — 12 tests con ChromaDB, Ollama y 1Password completamente mockeados: overflow, ventana de contexto, store/search, híbrida deduplicada, episodios, lecciones, workflows, Face ID, `op` ausente, integración de fachada y health check.
- **Suite completa:** 138/138 verde en 13.22 s.

### Fase 5 — Loop principal del agente (2026-05-18)
- **`core/planner.py`** — Reescrito con Pydantic: `PasoAccion` (reemplaza `PasoPlan`), `PlanEjecucion` (reemplaza `Plan`). Métodos: `plan()`, `replan()`, `validate_plan()` (detecta herramientas inválidas, confirmaciones faltantes, ciclos DFS), `estimate_complexity()` (0.0–1.0), `crear_plan()` (compat.). `frozenset` de herramientas válidas y de confirmación obligatoria.
- **`core/reflector.py`** — Reescrito con `ResultadoPaso` (Pydantic) y `DecisionReflexion` (str Enum: CONTINUAR, REINTENTAR, REPLANIFICAR, ABORTAR, ESPERAR_USUARIO). Reglas deterministas: PermissionError→ABORTAR, FileNotFoundError→REPLANIFICAR, TimeoutError→REINTENTAR/ABORTAR, MAX_REINTENTOS=3→REPLANIFICAR. `evaluate_task_completion()`, `generate_summary()`.
- **`core/agent.py`** — Reescrito con `AgentState(TypedDict)`, `ActualizacionAgente(BaseModel)` para streaming. Loop manual async percibir→pensar→actuar→reflexionar. API: `run()` (AsyncGenerator), `resume()` (WAIT_USER via asyncio.Event), `cancel()` (aborta herramienta activa). Límites: MAX_PASOS=50, MAX_REINTENTOS=3, MAX_REPLANES=3, TIMEOUT_PASO=120s, TIMEOUT_TAREA_GLOBAL=1800s. Herramientas inyectables como dict. `StateGraph` LangGraph compilado en `self._grafo` para arquitectura futura.
- **`config/prompts/planner.md`** — System prompt completo con 28 herramientas, formato JSON, 7 reglas obligatorias, 2 ejemplos.
- **`core/__init__.py`** — Actualizado con exports de `ActualizacionAgente`, `AgentState`, `PasoAccion`, `PlanEjecucion`, `DecisionReflexion`, `ResultadoPaso`.
- **`tests/test_core.py`** — Creado. 21 tests mockeados. Planner (plan, validación, ciclos, complejidad, replan), Reflector (retry, abort, replan, éxito, puede_fallar, completitud), Agente (streaming, max pasos, cancel, wait_user, resume, loop e2e).
- **Suite completa:** 126/126 verde.
- **Fixes de seguridad post-auditoría:** Lock por sesión en resume/cancel; `_PARAMS_PROHIBIDOS` (frozenset) bloquea inyección de kwargs de seguridad; `_ejecutar_herramienta` registra la task para que cancel() pueda abortarla; `except Exception: pass` → `log.exception`; `TIMEOUT_TAREA_GLOBAL=1800s`.

### Fase 4 — Sistema de acciones (2026-05-18)
- **`actions/filesystem.py`** — `SistemaArchivos` completo: leer/escribir/añadir/mover/copiar/eliminar (con confirmación), listar, buscar. `InfoArchivo` + `PropuestaMover`. Organización proactiva: `clasificar_archivo`, `sugerir_destino`, `organizar_archivo`, `vigilar_downloads` (watchdog). Reglas de clasificación para Luichi (física→Universidad/Física, facturas→Admin, código→Projects, screenshots→Pictures/Screenshots/YYYY-MM). Sandbox de raíz configurable; nunca opera fuera de HOME por defecto.
- **`actions/terminal.py`** — `Terminal` completo: `ejecutar_comando`, `ejecutar_script`, `ejecutar_python`, `transmitir_comando` (AsyncGenerator), `matar_proceso`. `ResultadoComando` con `duracion_ms`. Tres niveles: comandos bloqueados (`mkfs`, `dd`, `halt`...), comandos con confirmación (`rm`, `sudo`, `pip`...), comandos libres (`git`, `pytest`, `ls`...). Detección de `rm -rf /`, `curl|bash`, `git push --force`. Secrets del entorno filtrados con patrón general (`_API_KEY`, `_TOKEN`, `_SECRET`, `_PASSWORD`). Timeout máximo hardcodeado a 120s.
- **`actions/system.py`** — `ControlSistema` completo: apps (abrir/cerrar/ocultar/enfocar/listar), volumen/brillo con validación, bloqueo de pantalla, DnD, batería, Wi-Fi, captura de escritorios, clipboard (pbcopy/pbpaste), notificaciones y alertas nativas. `InfoApp`, `InfoBateria`, `InfoWifi`. AppleScript con timeout 10s.
- **`actions/keyboard_mouse.py`** — `RatonTeclado` completo: Quartz CGEvent (primario en M3) + pyautogui (fallback). Rate limit 10 acciones/s por `asyncio.Lock`. Parada de emergencia en coordenada (0,0). Confirmación para secuencias >20 acciones. Log de cada acción. Mouse: mover/click/doble-click/derecho/arrastrar/scroll. Teclado: escribir/pulsar/atajo/keydown/keyup.
- **`actions/browser.py`** — Dos capas: `ControlSafari` (AppleScript: URL, título, pestañas, navegar, atrás/adelante, recargar) + `Navegador` (Playwright: extraer texto/HTML, click, fill, submit, scroll, esperar elemento, JS con confirmación, descargar, screenshot). `InfoPestana`, `ResultadoExtraccion`. JS arbitrario siempre requiere confirmación.
- **`actions/comms/mail.py`** — `Mail` completo con `MensajeCorreo`. Lectura: contar no leídos, listar, obtener, buscar. Escritura (siempre con confirmación): enviar, responder, mover, marcar leído, eliminar.
- **`actions/comms/imessage.py`** — `IMessage` completo: listar conversaciones, obtener mensajes (contactos desconocidos requieren confirmación), enviar mensaje/archivo (siempre confirmación).
- **`actions/comms/whatsapp.py`** — `WhatsApp` sobre Playwright/WhatsApp Web: inicializar (requiere sesión activa), listar chats no leídos, obtener mensajes, buscar chat, enviar mensaje/archivo (siempre confirmación).
- **`actions/comms/telegram.py`** — `Telegram` bot API: obtener actualizaciones, info de chat, enviar mensaje/archivo (siempre confirmación). Paginación por `update_id`.
- **`tests/test_actions.py`** — 45 tests, todos con mocks completos (sin tocar sistema real). Cubren: sandbox FS, path traversal, clasificación de archivos, comandos bloqueados/confirmados, timeout, filtrado de secrets, volumen fuera de rango, portapapeles, rate limit, emergencia, JS sin sandbox, confirmaciones obligatorias en mail/iMessage.
- **`requirements.txt`** — Añadidos `pytesseract`, `Pillow`, `pyautogui` (ya estaban en specs pero faltaban en el fichero actual; `playwright` y `python-telegram-bot` ya estaban).
- **Suite completa:** 105/105 verde en ~12s.
- **Fixes de seguridad post-auditoría:** `asyncio.get_running_loop()` en watchdog thread; filtrado de secrets por patrón en `_construir_env`.

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

_(nada activo — Fase 6 memoria completada)_

---

## ⏳ Siguiente a implementar (Fase 7 — MCP servers)

Bus MCP que conecte el agente con las acciones:

1. **Bus MCP en `core/agent.py`** — enrutar herramientas inyectables hacia `mcp_servers/*` sin importar `actions/` desde `core/`.
2. **`mcp_servers/server_filesystem.py`** — primer servidor 100 % testeado (lectura/escritura/listar) con tests que prueben el sandbox de raíz.
3. **`mcp_servers/server_memory.py`** — exponer la fachada `MemorySystem` como interfaz pública MCP, manteniendo los módulos internos privados.
4. **`security/confirmation.py`** — implementar callbacks reales (notificación nativa macOS y prompt en el WebSocket) en vez del fail-closed por defecto.
5. **Pruebas e2e** — flujo agente→MCP mock→acción con confirmación auto-aprobada.

Tests mínimos para cerrar la fase:
- `tests/test_mcp_filesystem.py` — round-trip leer/escribir/listar con sandbox.
- `tests/test_agent_mcp.py` — flujo end-to-end con MCP mock y confirmación auto-aprobada.

---

## 🧠 Decisiones técnicas registradas

### 2026-05-05 (Fase 1)
- ADR-1: Router como guardián de privacidad (no el agente).
- ADR-2: Side effects solo en `actions/`, expuestos vía MCP servers.
- ADR-3: Embeddings siempre locales (Ollama).
- ADR-4: `core/` no importa `actions/` directamente.
- ADR-5: Confirmación humana fail-closed (timeout = denegado).
- ADR-6: Audit log JSONL append-only, sin rotación automática.

### 2026-05-18 (Fase 5 — Loop principal)
- ADR-26: **Loop manual en lugar de LangGraph astream** — las funciones de nodo se llaman directamente, sin `graph.astream`. Esto permite control total sobre streaming y pausa/reanudación sin depender de `interrupt()` (requiere langgraph>=0.2.31). El `StateGraph` compilado existe en `self._grafo` para documentación y uso futuro cuando la API esté más estabilizada.
- ADR-27: **asyncio.Event + Lock por sesión para WAIT_USER** — `run()` hace `await evento.wait()` (suspende sin bloquear). `resume()` y `cancel()` adquieren el lock antes de mutar `_respuestas_resume` o llamar `evento.set()`. Evita la race: "leer pop antes de set" que haría actuar con la respuesta equivocada.
- ADR-28: **Herramientas inyectables como `dict[str, Callable]`** — El agente no construye los action objects; se inyectan desde fuera. Facilita tests con mocks directos y permite al bus MCP (Fase 3) reemplazar las funciones sin cambiar el agente.
- ADR-29: **`_PARAMS_PROHIBIDOS` como frozenset** — `_ejecutar_herramienta` rechaza kwargs que podrían sobreescribir defaults de seguridad (`shell`, `raiz_permitida`, `timeout`, etc.) antes de hacer `fn(**paso.parametros)`. El LLM no puede inyectar parámetros de seguridad.

### 2026-05-18 (Fase 6 — Memoria)
- ADR-30: **`MemorySystem` como única fachada importable por `core/agent.py`** — el agente no importa submódulos de memoria para operaciones reales; coordina corto plazo, largo plazo, episodios, workflows y vault desde un punto.
- ADR-31: **Metadatos ChromaDB serializados a JSON plano** — Chroma solo acepta tipos primitivos en `metadatas`; listas/dicts/fechas se empaquetan en `metadata_json` y se reconstruyen al leer.
- ADR-32: **Embeddings siempre locales** — `LongTermMemory` usa `models.embeddings.EmbeddingsClient`; no hay envío de memoria a APIs cloud para embeddings.
- ADR-33: **ChromaDB degradable en tests/CI** — si el servidor no está disponible, la inicialización no rompe imports ni tests del agente; las operaciones de largo plazo fallan de forma explícita y la fachada las registra sin tumbar el loop.
- ADR-34: **Vault fail-closed con autorización inyectable** — todo `get_*` exige autorización previa; en producción se conectará a Face ID, en tests se mockea sin tocar secretos reales.

### 2026-05-18 (Fase 4 — Acciones)
- ADR-20: **Callback de confirmación inyectable en cada clase de acción** — en lugar de depender del `GestorConfirmacion` de `security/` (que requiere `PasoPlan`), cada clase acepta un `CallbackConfirmacion: Callable[[str], Future[bool]]`. Evita el ciclo de importación `actions/ → core/planner.py`. Default fail-closed.
- ADR-21: **Tres niveles de permiso en Terminal** — bloqueados (nunca), confirmación (siempre pide), libres (git, pytest, ls...). Separación clara en `frozenset` permite auditoría fácil.
- ADR-22: **Quartz CGEvent como primario en M3, pyautogui como fallback** — Quartz es más fiable en Retina; pyautogui cubre CI/Linux donde Quartz no está disponible.
- ADR-23: **Secrets filtrados por patrón en `_construir_env`** — en lugar de lista explícita, se filtran variables con sufijos `_API_KEY`, `_TOKEN`, `_SECRET`, `_PASSWORD`. Más robusto ante nuevas integraciones.
- ADR-24: **`asyncio.get_running_loop()` en watchdog thread** — en Python 3.12+, `get_event_loop()` desde un thread auxiliar puede no devolver el loop correcto. Se captura el loop en el momento de crear la tarea asyncio.
- ADR-25: **Dos capas en browser** — `ControlSafari` (AppleScript, sin proceso externo) para operaciones básicas de UI; `Navegador` (Playwright/Chromium) para interacción web compleja. Playwright solo cuando se necesita, para ahorrar RAM en M3 8GB.

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
