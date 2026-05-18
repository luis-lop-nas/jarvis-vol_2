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
- **Fase 7 — MCP servers:** ✅ completada
- **Fase 8 — Interfaz completa (FastAPI + WebSocket + SwiftUI overlay):** ✅ completada
- **Fase 9 — Seguridad completa (auth, sandbox, confirmation, audit_log, permissions):** ✅ completada

---

## ✅ Completado

### Migración FastMCP + mejoras MCP (2026-05-19)
- **`mcp_servers/fastmcp_server.py`** (nuevo) — Servidor FastMCP sobre el bus interno. `_make_handler()` usa `inspect.Signature` para derivar la firma Python del `inputSchema` de cada herramienta sin `exec()`; `_build_server()` registra todas las herramientas vía `mcp.add_tool()`. Fallback automático a `stdio_server.py` si fastmcp no está instalado.
- **OTel condicional** — `_otel_wrap()` activo solo si `mcp_otel_enabled=True` y `fastmcp>=3.0.0`. Emite spans JSON Lines a stderr (no interfiere con el protocolo stdio en stdout). Campos: `tool_name`, `session_id`, `duration_ms`, `success`. Sin parámetros (datos potencialmente sensibles).
- **`mcp_servers/__main__.py`** — Actualizado para usar `fastmcp_server.main()`. `stdio_server.py` se mantiene como fallback compatible.
- **`core/mcp_bus.py`** — Scoping de herramientas por sesión: `allow_tool(tool_name, session_id)`, `restrict_session(session_id, tools)`, `_session_restrictions: dict[str, set[str]]`. `execute()` verifica `allow_tool()` antes de ejecutar → MCPResult con error "no autorizada". También `health_check()` → `dict[str, bool]` llamando `herramientas()` en cada servidor.
- **`interface/api.py`** — `crear_servidor()` acepta `bus: MCPBus | None`. GET `/status` llama `bus.health_check()` e incluye `mcp_health: dict[str, bool]` en la respuesta.
- **`interface/api_models.py`** — `SystemStatus` añade `mcp_health: dict[str, bool] = {}`.
- **`config/settings.py`** — `mcp_otel_enabled: bool = False`.
- **`requirements.txt`** — `fastmcp>=2.0.0`.
- **ADRs**: ADR-72 (FastMCP como transporte, MCPBus intacto), ADR-73 (OTel a stderr, no stdout, para compatibilidad con stdio MCP), ADR-74 (scoping sesión con dict[session_id, set[tool_name]]), ADR-75 (health_check llama herramientas() — falla = servidor no disponible).
- **Tests añadidos**: `test_mcp_bus_tool_allowed_default`, `test_mcp_bus_tool_restricted`, `test_mcp_bus_restriction_does_not_affect_other_sessions`, `test_mcp_bus_health_all_ok`, `test_mcp_bus_health_partial_failure` (en `test_mcp_bus.py`); `test_fastmcp_server_can_be_built`, `test_fastmcp_handler_executes_via_bus`, `test_fastmcp_handler_signature_matches_schema` (en `test_mcp_stdio.py`).
- **Suite completa: 266/266 verde (+ 1 skip fastmcp no instalado) en ~20s**.

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

### Fase 9 — Seguridad completa (2026-05-18)
- **`security/auth.py`** — `AuthManager` con Face ID via pyobjc LocalAuthentication. `AuthResult/AuthError`. Caché 60s, timeout 30s, `asyncio.to_thread`. Single-flight pattern para evitar doble diálogo. Fallback automático a contraseña. `get_auth_policy()`.
- **`security/sandbox.py`** — `Sandbox` con `CommandRisk` enum (SAFE/MODERATE/DANGEROUS/BLOCKED). Listas compiladas: `_BLOCKED_PATTERNS`, `_DANGEROUS_PATTERNS`, `_MODERATE_PATTERNS`. Normalización de binarios (detecta `/bin/rm` igual que `rm`). Fail-closed: sin `ConfirmationManager` → SandboxError. `sanitize_path()` y `sanitize_env()`.
- **`security/confirmation.py`** — `ConfirmationManager` con `asyncio.Event` para pausar el agente. `ws_sender` callback inyectable. `resolve()` idempotente con verificación de expiración. Timeout 60s → confirmed=False.
- **`security/audit_log.py`** — `AuditEntry(BaseModel)` 13 campos. Rotación diaria JSONL en `~/Library/Logs/JARVIS/`. Cola async fire-and-forget. Sanitización de secrets. `_append_sync` con `O_APPEND|O_CREAT` y permisos 0o600. Compat `registrar()`.
- **`security/permissions.py`** — `PermissionsManager.verify_critical()` → `sys.exit(1)` si falta ACCESSIBILITY o SCREEN_RECORDING. `wait_for_permission()` polling async. `request()` abre System Settings.
- **`security/__init__.py`** — Exports + globals module-level `auth_manager`, `sandbox`, `confirmation_manager`, `audit_log`, `permissions_manager`.
- **Integraciones:** `filesystem.py` (auth para delete_dir), `terminal.py` (sandbox delegation), `mail.py`/`imessage.py` (auth para send), `interface/api.py` (confirmation_manager.resolve en POST /confirm), `main.py` (inicializa stack completo, verify_critical al arrancar).
- **`tests/test_security.py`** — 54 tests (10 auth, 18 sandbox, 8 confirmation, 6 audit_log, 8 permissions). Mock completo de LocalAuthentication.
- **Fixes post-auditoría @security-reviewer:** sandbox fail-closed, normalización binarios, resolve() idempotente, audit log O_APPEND+0o600, single-flight auth.
- **Suite completa:** 230/230 verde en 16.88 s.

### Fase 8 — Interfaz completa (2026-05-18)
- **`interface/api_models.py`** — Pydantic: `ChatRequest`, `ChatResponse`, `ConfirmRequest`, `AgentUpdate`, `ConfirmationRequest`, `SystemStatus`.
- **`interface/api.py`** — FastAPI en puerto 8765: POST `/chat` (async, devuelve inmediatamente), GET `/stream/{session_id}` (SSE con cola por sesión), POST `/confirm` (desbloquea agente via `agente.resume()`), POST `/cancel`, GET `/status` (ChromaDB + Ollama + RAM + 1Password), GET `/history`, POST `/screenshot`. WS `/ws` integrado con protocolo message/confirm/cancel/ping. CORS localhost-only, rate limiting 10 req/s por session_id (ventana deslizante), máx 500 sesiones activas, validación de session_id, error handler global sin stack traces.
- **`interface/websocket.py`** — `ConnectionManager`: connect/disconnect/send/broadcast con buffer `deque(maxlen=50)` por sesión para reconexión automática.
- **`main.py`** — Reescrito: checks paralelos (permisos macOS + Ollama + ChromaDB), tabla rich de estado de arranque, inicialización correcta del `Agente` (sin referencias rotas), arranque en `settings.api_port` (8765).
- **`config/settings.py`** — `api_port` default actualizado de 8080 a 8765.
- **`interface/swiftui/`** — Overlay nativo macOS completo:
  - `JARVISApp.swift` — Menu bar app (LSUIElement), auto-lanza backend Python.
  - `AppDelegate.swift` — Orquestador: status bar, permisos, WebSocket, hotkey, sync de ventanas al estado.
  - `JARVISState.swift` — `@Observable`, `UIState` enum (silent/notchPulse/edgeLog/focusModal/inline), `applyUpdate()` con transiciones animadas spring.
  - `WebSocketClient.swift` — URLSessionWebSocketTask, reconexión exponential backoff (1s→2s→4s→8s→30s).
  - `PermissionsManager.swift` — Accessibility + Screen Recording, abre System Settings.
  - `NotchView.swift` — Panel notch 120×22→240×38px, dot pulsante.
  - `EdgeLogView.swift` — Strip 3px borde derecho, expande 200px al hover, lista de pasos con íconos.
  - `FocusModalView.swift` — Panel central 480px, NSVisualEffectView vibrancy, streaming text, Esc/⌘↵.
  - `InlineView.swift` — Contextual: VS Code / Finder / Safari / generic.
  - `ConfirmationCard.swift` — Card ámbar (#3d2800) con botones Cancelar/Confirmar.
  - `WindowManager.swift` — Ventanas sin titlebar en niveles statusBar/floating/modalPanel.
  - `HotkeyManager.swift` — CGEventTap ⌘Space, fallback ⌘⌥Space + NSEvent global monitor.
  - `AppContextDetector.swift` — AXUIElement polling 0.5s, AppContext.
  - `Resources/Info.plist` — LSUIElement, permisos, deployment target macOS 14.0+, bundle com.jarvis.overlay.
  - `JARVIS.xcodeproj/project.pbxproj` — Proyecto Xcode mínimo válido.
  - `build.sh` — xcodebuild Release/Debug, copia .app a ~/Applications/.
- **`tests/test_interface.py`** — 19 tests: todos los endpoints REST + WebSocket (ping/pong/buffer/json-inválido) + rate limit. Fixture autouse limpia estado módulo entre tests. Agente completamente mockeado.
- **Suite completa:** 176/176 verde en 14.77s (157 preexistentes + 19 nuevos).

### Fase 7 — MCP servers (2026-05-18)
- **`mcp_servers/base.py`** — Contrato MCP interno con `MCPRequest`, `MCPResult`, `MCPTool`, protocolo `MCPServer`, conversión a formato `tools/list`, helpers de JSON Schema, validación de parámetros y `serializar_dato()` para dataclasses, Pydantic, `Path`, fechas y bytes.
- **`core/mcp_bus.py`** — `MCPBus`: registro de servidores, listado de herramientas, dispatch async con timeout, validación de `input_schema`, resultados normalizados, auditoría centralizada, sanitización de secretos (`api_key`, token, password, etc.) y bloqueo fail-closed de herramientas sensibles sin confirmación explícita.
- **`mcp_servers/server_filesystem.py`** — Adaptador sobre `SistemaArchivos` con nombres canónicos del planner: `filesystem.leer`, `filesystem.escribir`, `filesystem.listar`, `filesystem.buscar`, `filesystem.mover`, `filesystem.copiar`, `filesystem.eliminar`. Respeta sandbox y confirmaciones de acciones destructivas.
- **`mcp_servers/server_memory.py`** — Adaptador sobre la fachada pública `MemorySystem`: `memory.contexto`, `memory.guardar`, `memory.buscar`, `memory.workflow`, `memory.episodio`, `memory.health`.
- **`mcp_servers/server_code.py`** — Adaptador sobre `Terminal`: `terminal.ejecutar`, `terminal.python`, `terminal.transmitir`.
- **`mcp_servers/server_system.py`** — Adaptador sobre `ControlSistema`: apps, volumen, brillo, clipboard y notificaciones.
- **`mcp_servers/server_browser.py`** — Adaptador sobre `Navegador` + `ControlSafari`: lectura/abrir URL, lectura de pestaña activa, click, fill, JS con confirmación y screenshot/descarga.
- **`mcp_servers/server_comms.py`** — Adaptador sobre Mail, iMessage, Telegram y WhatsApp Web inyectado; acepta los aliases del prompt (`destinatario`, `mensaje`, `nombre_chat`) y falla claro si Telegram/WhatsApp no están configurados.
- **`mcp_servers/server_input.py`** — Adaptador sobre `RatonTeclado`: escribir, atajos, clicks, doble click y scroll.
- **`mcp_servers/server_perception.py`** — Adaptador sobre percepción: screenshot y accesibilidad.
- **`mcp_servers/stdio_server.py`** — Servidor MCP stdio real sobre el bus interno: soporta `initialize`, `tools/list`, `tools/call` y notificaciones `notifications/*`; arranca con `python -m mcp_servers` sin añadir dependencia runtime al SDK externo.
- **`mcp_servers/__init__.py`** — Factory `crear_bus_mcp()` con servidores por defecto y sin ciclos de importación.
- **`core/agent.py`** — Integración con `MCPBus`: mantiene herramientas inyectadas para tests, y si no existe callable local ejecuta vía MCP. Los `MCPResult` se convierten a `ResultadoPaso` y las llamadas MCP activas son cancelables por sesión.
- **Schemas MCP:** todas las herramientas reales exponen `inputSchema` tipo objeto con propiedades, requeridos y `additionalProperties`; `MCPBus` rechaza llamadas inválidas antes de tocar `actions/`.
- **Tests añadidos:** `tests/test_mcp_bus.py`, `tests/test_mcp_filesystem.py`, `tests/test_mcp_memory.py`, `tests/test_mcp_comms.py`, `tests/test_mcp_stdio.py`, `tests/test_agent_mcp.py`.
- **Debug profundo post-fase:** verificación planner↔MCP OK (`pedir_aclaracion` queda como pseudoacción conversacional; `memory.*` son extras del bus), confirmaciones sensibles reforzadas, WhatsApp sin placeholder roto, aliases de parámetros alineados con el prompt y cobertura de `teclado.*`/`percepcion.*`.
- **Verificación:** `python3 -m compileall -q mcp_servers core tests` OK; `python3 -m compileall -q actions config core memory mcp_servers models perception security tests main.py` OK; suite completa: **157/157 verde en 13.86 s**.

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

## ✅ Completado recientemente

### Hallazgo crítico del auditor resuelto (2026-05-19)
- **[CRÍTICO] Scoping de confirmaciones por session_id** — `ConfirmationManager.resolve()` ahora acepta `session_id: str` y verifica que el `request_id` pertenece a esa sesión antes de resolver. Si no coincide lanza `SecurityError` y registra la violación en el audit log con `action_type="security_violation"`. `interface/api.py` y `interface/websocket.py` pasan el session_id del request/conexión.
- **Rate limiting de confirmaciones por sesión** — máx 10 confirmaciones en 60s por `session_id`. Implementado con `deque(maxlen=10)` de timestamps en `ConfirmationManager`. Exceder el límite devuelve `ConfirmationResult(request_id="rate-limited", confirmed=False)`.
- **Sandbox Docker opcional** — `security/docker_sandbox.py` con clase `DockerSandbox`. Para comandos DANGEROUS con Docker disponible y `security_docker_sandbox_enabled=True` en settings: contenedor Alpine temporal, `--network none`, directorio montado read-only, destrucción garantizada en `finally` (fail-closed). `config/settings.py` añade `security_docker_sandbox_enabled: bool = False`.
- **Audit log con query y estadísticas** — `AuditLog.query(action_type, since, limit)` y `AuditLog.stats(since)` que devuelve `AuditStats` (total, por tipo, fallidas, violaciones, avg_duration_ms). Expuesto en `GET /audit?action_type=X&hours=24`.
- **ADRs**: ADR-68 (scoping por session_id en confirmaciones), ADR-69 (rate limiting con deque en ConfirmationManager), ADR-70 (Docker sandbox fail-closed en finally), ADR-71 (query/stats en audit log como método async no bloqueante).
- **Suite completa: 259/259 verde en 24.45s** (248 previos + 11 nuevos).

### Fase 10 — Tests e2e + Benchmarks (2026-05-18)
- **`tests/e2e/test_full_system.py`** — 12 tests end-to-end completos:
  - `test_e2e_simple_file_read`: lectura de archivo real con herramienta inyectada
  - `test_e2e_file_organize`: plan con confirmación → agente pausa en `esperando`
  - `test_e2e_terminal_safe_command`: sandbox permite `python3 --version` (returncode 0)
  - `test_e2e_terminal_blocked_command`: sandbox bloquea `rm -rf /` con `SandboxError(BLOCKED)`
  - `test_e2e_memory_persistence`: `store_interaction` llamado ≥2 veces por ciclo
  - `test_e2e_router_privacy`: texto con "contraseña" → `ModeloDestino.LOCAL_DEFAULT`, razón `datos_sensibles`
  - `test_e2e_agent_max_steps`: agente para a MAX_PASOS=3, emite `tipo=error` con "Límite"
  - `test_e2e_agent_streaming`: agente emite `pensando → actuando → listo` con progreso monotónico
  - `test_e2e_websocket_protocol`: WebSocket responde ping→pong, cierra con 1008 ante session_id inválido
  - `test_e2e_confirmation_flow`: agente pausa en `esperando`, `resume('si')` desbloquea y completa
  - `test_e2e_full_conversation`: 5 turnos consecutivos, `store_interaction` ≥10 llamadas
  - `test_e2e_confirmation_via_http`: POST /confirm desbloquea agente vía HTTP API
- **`tests/e2e/test_performance.py`** — 6 benchmarks de rendimiento:
  - `test_perf_router_decision`: 100 decisiones < 50ms media, P99 < 150ms
  - `test_perf_screenshot_encode`: encode imagen 1080p < 200ms media
  - `test_perf_embedding_overhead`: overhead EmbeddingsClient (sin red) < 50ms
  - `test_perf_short_term_memory`: add_message < 5ms, get_context_window < 10ms
  - `test_perf_memory_usage`: imports del sistema < 100MB RAM adicional
  - `test_perf_sandbox_analysis`: check_command media < 1ms, P98 < 5ms
- **`pyproject.toml`** — registrados markers `e2e` y `perf` (`--strict-markers`)
- **Suite completa: 248/248 verde en 18.63s**

---

## 🔄 En progreso

_(nada activo — Fase 10 completada 2026-05-18)_

---

## ⏳ Siguientes candidatos

1. **Persistencia de sesiones** — guardar/restaurar sesiones activas en disco para sobrevivir reinicios del servidor.
2. **Distribución del overlay** — `interface/swiftui/build.sh` ya preparado. Firma y notarización. Auto-update system.
3. **Dashboard web** — panel `http://localhost:8765` con historial de sesiones, logs y estado del sistema.
4. ~~**Scoping de confirmaciones por sesión**~~ — resuelto 2026-05-19 (hallazgo crítico del auditor).
5. ~~**Migración FastMCP + scoping herramientas + health check**~~ — resuelto 2026-05-19.

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

### 2026-05-18 (Debug completo del sistema)
- ADR-57: **`validate_command()` extraído en Sandbox** — permite que `transmitir_comando` y `ejecutar_script` (antes bypasseaban el sandbox) pasen por la misma verificación de riesgo, autenticación y confirmación que `execute_safe`. El audit log usa `log_action()` con `risk_level` real en vez de `registrar()` legacy.
- ADR-58: **`_session_history` usa `deque(maxlen=MAX_HISTORY)`** — `del hist[0]` era O(n); `deque` lo hace O(1) y elimina la condición de longitud.
- ADR-59: **`subprocess.run` en `/status` → `asyncio.create_subprocess_exec`** — la llamada bloqueante a `op --version` podía bloquear el event loop 2s; ahora es completamente async.
- ADR-60: **WebSocket `confirm` resuelve confirmaciones de seguridad** — el handler WS ahora también llama `confirmation_manager.resolve()` si el payload incluye `request_id`, igual que el endpoint REST. Evitaba que confirmaciones desde el overlay quedaran colgadas.
- ADR-61: **Validación de `session_id` en WebSocket** — tanto el parámetro de query como el `session_id` del payload se validan contra `_SESSION_ID_RE`; conexiones inválidas se cierran con código 1008.
- ADR-62: **`get_event_loop()` → `get_running_loop()` en `wait_for_permission`** — en Python 3.12 `get_event_loop()` desde coroutine emite DeprecationWarning; `get_running_loop()` es la API correcta.
- ADR-63: **`_resolve_lock` eliminado en `ConfirmationManager`** — se creaba en `__init__` pero nunca se usaba; su presencia era engañosa. La seguridad de `resolve()` la garantiza el modelo single-threaded de asyncio.
- ADR-64: **`tmp_path` inicializado antes del try en `_check_screen_recording`** — evita `NameError` en el bloque `finally` si `NamedTemporaryFile` falla antes de asignar la variable.
- ADR-65: **LangGraph conditional corregido en `_construir_grafo_langgraph`** — el lambda devolvía siempre "responder" independientemente de la condición; ahora distingue entre "responder" (tarea completa) y "pensar" (continuar loop).
- ADR-66: **`datetime.fromtimestamp` con `tz=timezone.utc` en `filesystem.py`** — evita datetimes naive inconsistentes con el resto del sistema que usa UTC.
- ADR-67: **`CallbackConfirmacion` usa `Awaitable[bool]`** — el tipo `asyncio.coroutines.CoroType` no existe en Python 3.12; `Awaitable[bool]` es el tipo correcto.

### 2026-05-18 (Fase 9 — Seguridad)
- ADR-51: **Instancias globales en `security/__init__.py`** — inicializadas en `main.py` y accesibles en todo el proyecto. Evita pasar security objects por toda la cadena de llamadas; los módulos comprueban `is None` antes de usar.
- ADR-52: **Sandbox fail-closed** — DANGEROUS/MODERATE sin `ConfirmationManager` configurado → `SandboxError` inmediato. Nunca ejecución silenciosa sin confirmación.
- ADR-53: **Normalización de binarios en sandbox** — `_normalize_command()` reemplaza paths absolutos por nombre base antes de evaluar patrones. Evita bypass con `/bin/rm -rf /`.
- ADR-54: **`resolve()` idempotente en ConfirmationManager** — verifica `expires_at` y `event.is_set()` antes de mutar `result_box`. Evita sobreescritura tardía de confirmaciones expiradas.
- ADR-55: **Audit log con `O_APPEND` + `0o600`** — `_append_sync` usa `os.open()` con flags atómicos y permisos restrictivos para privacidad del log.
- ADR-56: **Single-flight en AuthManager** — `_in_flight: Future` evita dos diálogos Face ID simultáneos; `finally` siempre resuelve el future y limpia el estado aunque la corutina sea cancelada.

### 2026-05-19 (Hallazgo crítico del auditor)
- ADR-68: **Scoping de confirmaciones por session_id** — `ConfirmationRequest.session_id` y `resolve(request_id, confirmed, session_id)`. Si ambos son no-vacíos y no coinciden → `SecurityError` + audit `security_violation`. Compatibilidad hacia atrás: `session_id=""` desactiva el scoping.
- ADR-69: **Rate limiting en ConfirmationManager con deque(maxlen=10)** — mismo patrón que el rate limit de la API (ADR-45). La ventana es 60s porque las confirmaciones son acciones lentas del usuario, no peticiones HTTP.
- ADR-70: **Docker sandbox fail-closed con `finally`** — el contenedor se destruye siempre en el bloque `finally` de `DockerSandbox.run()`. Si `_force_remove` falla, la excepción se suprime (el propio `--rm` de Docker lo habría destruido). `is_available()` cachea el resultado para no llamar a Docker en cada ejecución.
- ADR-71: **`query()` y `stats()` leen JSONL con `asyncio.to_thread`** — mismo patrón que `get_entries()` ya existente (ADR-55). `stats()` delega en `query()` para no duplicar el código de lectura de fichero.

### 2026-05-18 (Fase 8 — Interfaz)
- ADR-44: **Estado de sesiones module-level compartido** — `_session_queues/history/tasks` son dicts module-level; `crear_servidor()` inyecta agente/manager pero comparte el estado de sesión, lo que permite que SSE y WS accedan a la misma cola sin coordinación extra.
- ADR-45: **Rate limiting con ventana deslizante de deque** — cada `session_id` tiene un `deque(maxlen=20)` de timestamps; se purgan los >1s en cada check. Sin dependencias externas.
- ADR-46: **SSE con sentinel `None`** — `_run_agent_task` pone `None` en la cola al terminar; el generador SSE lo interpreta como señal de cierre y rompe el bucle sin polling.
- ADR-47: **WebSocket buffer circular** — `ConnectionManager` usa `deque(maxlen=50)` por sesión; al reconectar, el cliente recibe los últimos 50 mensajes perdidos antes de entrar en el bucle normal.
- ADR-48: **Overlay SwiftUI `@Observable`** — `JARVISState` usa el macro `@Observable` de Swift 5.9+ (macOS 14+); `applyUpdate()` aplica `withAnimation(.spring)` para transiciones suaves entre estados UI.
- ADR-49: **xcodeproj con identificadores cortos** — `project.pbxproj` usa IDs cortos legibles (PROOT, TTARGET, etc.) en lugar de UUIDs de 24 hex; válido para Xcode. Si hay conflictos, regenerar con `open -a Xcode Package.swift` → File → Generate Xcode Project.
- ADR-50: **Límite de 500 sesiones activas** — previene DoS por acumulación de sesiones; `POST /chat` devuelve 503 si se supera. Session-ids validados con regex `^[a-zA-Z0-9_-]{1,64}$`.

### 2026-05-18 (Fase 7 — MCP)
- ADR-35: **Nombres canónicos iguales al planner** — el bus MCP expone `filesystem.leer`, `terminal.ejecutar`, etc.; se eliminan nombres paralelos tipo `fs_leer` para evitar traducciones frágiles.
- ADR-36: **Bus MCP como frontera de ejecución** — `core/agent.py` conserva herramientas inyectables para tests, pero en runtime puede delegar en `MCPBus` sin importar `actions/`.
- ADR-37: **Auditoría centralizada en MCPBus** — cada llamada y resultado registra herramienta, parámetros sanitizados, duración, error y efectos secundarios. Secretos nunca se escriben en logs.
- ADR-38: **Servidores como adaptadores finos** — `mcp_servers/*` no reimplementan lógica; solo traducen nombres/params hacia `actions/` o `MemorySystem`.
- ADR-39: **Resultados MCP normalizados** — toda ejecución devuelve `MCPResult`; el agente lo convierte a `ResultadoPaso`, manteniendo el loop de reflexión igual.
- ADR-40: **Confirmación sensible también en el bus** — aunque el planner marque `requiere_confirmacion`, el `MCPBus` vuelve a validar `MCPTool.requires_confirmation`. Si falta la confirmación explícita, la ejecución no llega al adaptador.
- ADR-41: **WhatsApp MCP por inyección de sesión** — el servidor no crea Playwright ni fuerza login; usa un objeto `WhatsApp` ya inicializado por runtime. Sin sesión, devuelve `RuntimeError("WhatsApp no configurado")`.
- ADR-42: **Schemas antes de side effects** — cada herramienta declara `inputSchema` y el `MCPBus` valida requeridos/tipos básicos antes de ejecutar. Los errores de parámetros son `ValidationError` normalizados, no `KeyError` tardíos dentro de `actions/`.
- ADR-43: **MCP stdio sin dependencia dura al SDK** — se implementa el subconjunto necesario de JSON-RPC/MCP (`initialize`, `tools/list`, `tools/call`) sobre el bus existente. Esto permite usar `python -m mcp_servers` incluso si el SDK `mcp` no está instalado; si más adelante se adopta FastMCP, la frontera pública ya está testeada.

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

### 2026-05-19 (Migración FastMCP + mejoras MCP)
- ADR-72: **FastMCP como transporte, MCPBus intacto** — `fastmcp_server.py` reemplaza solo la capa stdio. El bus, la auditoría, el scoping de confirmaciones y la sanitización de secretos no cambian. `stdio_server.py` se mantiene como fallback si `fastmcp` no está instalado.
- ADR-73: **OTel a stderr, no stdout** — en modo stdio MCP, stdout es el canal de protocolo JSON-RPC. Los spans OTel se emiten a stderr en formato JSON Lines. Solo activo con `mcp_otel_enabled=True` y `fastmcp>=3.0.0`.
- ADR-74: **Scoping de sesión con `dict[session_id, set[tool_name]]`** — `_session_restrictions` en MCPBus. Por defecto vacío (sin restricciones). `restrict_session()` añade; no hay método de eliminar restricciones (las sesiones son efímeras). `allow_tool()` con `session_id=""` devuelve siempre True (compatibilidad con callers sin sesión).
- ADR-75: **`health_check()` llama `herramientas()` por servidor** — es una llamada inofensiva (solo introspección). Si lanza excepción → `False`. Si devuelve lista vacía → `False`. Sin timeout adicional porque `herramientas()` es síncrono y no hace I/O.

---

## 📋 Notas y deudas técnicas

### Permisos macOS necesarios (perception/)
- **Accesibilidad** — Sistema → Privacidad → Accesibilidad → añadir el proceso. Sin este permiso todas las funciones de `accessibility.py` devuelven None.
- **Grabación de pantalla** — Sistema → Privacidad → Grabación de pantalla → añadir el proceso. Sin este permiso `screencapture` devuelve imagen negra.
- `main.py` debe llamar a `solicitar_permiso_accesibilidad()` en startup si `verificar_permiso_accesibilidad()` devuelve False.

### Deudas previas
- WhatsApp MCP requiere que el runtime inyecte una sesión Playwright ya inicializada; el servidor no la crea por defecto.
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
