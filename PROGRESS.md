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

## ✅ Completado recientemente

### SwiftUI UX — overlay completo P1–P8 (2026-05-20)

**P1 — Hotkey ⌘⌥Space**
- `HotkeyManager.swift` migrado de ⌘Space a ⌘⌥Space (keyCode 49 + maskCommand + maskAlternate).
- Fallback `NSEvent` global monitor en ⌘⇧Space si CGEventTap falla (Accessibility denegada).
- `_notifyTapFailed()` — `UNUserNotificationCenter` notifica al usuario una sola vez cuando el tap falla.
- Eliminado toggle `useAltSpace`; el hotkey es único.

**P2 — Colores semánticos en NotchView**
- `AgentPhase` enum: `thinking` (azul) / `acting` (ámbar) / `completed` (verde) / `error` (rojo).
- `NotchView` recibe `agentPhase`, `currentToolName`, `errorMessage`, `progressFraction`.
- Barra de progreso bajo el notch visible solo durante `.acting`.
- `JARVISState` añade `agentPhase`, `currentToolName`, `errorMessage`.

**P3 — EdgeLogView con spring, timestamps y pin**
- `isHovered || isPinned` controla la expansión del log lateral.
- Animación `.interpolatingSpring(stiffness: 300, damping: 28)`.
- `LogStep` tiene `timestamp: Date` y `elapsed` (ej: "hace 2s").
- `StepRow` muestra `elapsed` alineado a la derecha.
- Botón pin con ícono de chincheta; estado persiste mientras haya interacción.

**P4 — FocusModalView con input inline e historial**
- `replyText: String` con `TextField` para respuestas rápidas.
- `ScrollView` con `MessageBubble` para el historial (`conversationHistory`).
- Footer: modelo, tokens y coste USD.
- Hint actualizado: "Esc · ⌘⌥Space para cerrar".

**P5 — InlineView posición adaptativa y auto-dismiss**
- `WindowManager` define `InlinePosition` y `appPositionPreferences` (11 apps).
- `showInline(content:)` sin `point:` — posición derivada del bundle ID de la app activa.
- Auto-dismiss a los 8 s sin interacción; timer se pausa en `.onHover`.
- `TerminalChip` (esquina inf-izq, verde, monospaced) y `MailChip` (HStack con icono envelope) añadidos.

**P6 — ConfirmationCard mejorada**
- Colores adaptativos vía `@Environment(\.colorScheme)` (dark/light).
- `affectedItems`: botón "Ver N elementos" con `ScrollView` deslizable (máx 20 + "… y N más").
- Barra de expiración animada con `TimelineView(.animation)`, 60 s, rojo al quedar <20 %.
- Botones destructivos: 3 vías — Cancelar / A la papelera / Eliminar definitivo.
- `NSHapticFeedbackManager` en `.onAppear` y al confirmar.

**P7 — Estado de error visible**
- `WebSocketClient` expone `onLongDisconnect: (() -> Void)?` (disparado cuando delay >5 s).
- `AppDelegate` conecta `onLongDisconnect` → `state.isDisconnected = true`.
- `JARVISState.isDisconnected` activa banner de reconexión en `FocusModalView`.
- `NotchView` muestra el `errorMessage` con ícono rojo cuando `agentPhase == .error`.

**P8 — Onboarding de primera ejecución**
- `OnboardingView.swift` (nuevo): 3 pasos, `VisualEffectBlur`, dots de progreso, animación spring.
- Pasos: "Hola, soy JARVIS" / "⌘⌥Space para activarme" / "Siempre te pido permiso".
- `UserDefaults` key `jarvis.onboardingCompleted` — se muestra solo la primera vez.
- `AppDelegate._checkOnboarding()` lanzado en `applicationDidFinishLaunching`.

**Python — ajustes complementarios**
- `security/confirmation.py`: `ConfirmationRequest` añade `action_type`, `affected_items`, `affected_count`. `request_confirmation()` acepta y reenvía estos campos al overlay vía WebSocket.
- `requirements.txt`: `send2trash>=1.8.0` añadido.

**ADR-68** — `onLongDisconnect` como callback en lugar de lógica de UI en `WebSocketClient`:
mantiene el cliente agnóstico del estado de SwiftUI y evita importar `SwiftUI` desde `Core/`.

**ADR-69** — `TerminalChip` y `MailChip` como vistas privadas en `InlineView.swift` en lugar de
ficheros separados: son variantes de presentación, no componentes reutilizables.

**ADR-70** — `appPositionPreferences` como dict en `WindowManager` en lugar de lógica
en `InlineView`: el posicionamiento es responsabilidad del sistema de ventanas, no de la vista.

- **Suite Python: 464/464 verde + 1 skip (fastmcp no instalado).**
- **Swift: SourceKit falsos positivos por análisis aislado de ficheros — se resuelven al compilar.**

---

## ✅ Completado

### Sesión de fixes — auditoría de seguridad y limpieza (2026-05-20)

- **[CRÍTICO RESUELTO] Scoping de confirmaciones en WebSocket** — El handler WS usaba
  `sid` (derivado del payload, manipulable por el cliente) al llamar `resolve()`.
  Corregido: ahora usa siempre `session_id` del URL param de conexión (validado en el
  handshake). Test `test_confirmation_websocket_uses_connection_session_id` verifica el
  comportamiento.
- **[POLICY] anthropic/openai movidos a extras dev** — `requirements.txt` de producción
  ya no incluye ningún SDK de tercero que viole CLAUDE.md. Comentados con explicación.
  `pyproject.toml` añade `[project.optional-dependencies] dev = [...]`.
  `make install-dev` hace `pip install -e ".[dev]"`.
- **[CLEANUP] requirements.txt sin duplicados** — `pytesseract`, `Pillow` y `pyautogui`
  aparecían dos veces (sección OCR + sección Comunicaciones). Eliminados. Capitalización
  normalizada a `Pillow` (nombre oficial PyPI).
- **[DOCS] README y puertos corregidos** — `localhost:8080`/`8081` → `localhost:8765`
  en todo el README. `.env.example` actualizado (`API_PORT=8765`, `WEBSOCKET_PORT`
  eliminado con nota explicativa). STT y TTS marcados como `[planned]` en el diagrama.
  OpenRouter añadido a la tabla de modelos. Sección "Estado actual" con enlace a
  PROGRESS.md.
- **Suite: 464/464 verde + 1 skip (fastmcp no instalado).**

### Máquina de estados + trazabilidad en core/agent.py (2026-05-19)
- **`AgentFase` (StrEnum)** — 11 estados explícitos: `INIT → PERCEIVE → PLAN → WAIT_CONFIRMATION → EXECUTE_TOOL → VERIFY → REFLECT → REPLAN → DONE / ERROR / CANCELLED`.
- **`TrazaPaso` (Pydantic)** — Registro por transición: `ts`, `fase`, `paso_id`, `herramienta`, `memoria_tokens`, `razon`, `resultado_exito`, `duracion_ms`.
- **`AgentState`** — Nuevos campos `fase: str` y `traza: list[dict]` (pre-serializados). Compatibles con `total=False` — no rompen código existente.
- **`ActualizacionAgente`** — Nuevos campos `fase: str` (visible en streaming SSE/WS) y `traza: list[dict] | None` (poblado en el update final `"listo"`).
- **`_transicion(estado, fase, **kw)`** — Helper que actualiza `fase` y appenda `TrazaPaso` en una operación atómica. Usado en todos los puntos de transición del loop.
- **`estado_a_dict(estado)`** — Serialización completa a JSON-compatible; maneja Pydantic (`model_dump`) y dataclasses (`dataclasses.asdict`). Exportada para uso en `SessionStore`.
- **Persistencia mejorada** — `run(initial_state=...)` preserva `fase` y `traza` al reanudar; si `initial_state.fase == "wait_confirmation"`, SessionStore puede reconocer dónde pausar.
- **8 tests nuevos** en `TestAgenteFaseYTraza`: transiciones happy-path, traza en update final, fase ERROR en timeout, fase CANCELLED al cancelar, reintentos agotados abortan, traza con entrada REPLAN, `estado_a_dict` serializable, reanudación desde `initial_state` con plan existente.
- **Suite: 462/462 verde + 1 skip** (telegram no instalado, preexistente).

### Sistema de skills modular (2026-05-19)
- **`skills/registry.py`** — `ToolDecl` (Pydantic): declaración de herramienta con nivel_riesgo, confirmación, capacidades, permisos macOS. `to_policy()` convierte a `ToolPolicy`. `SkillManifest` (Pydantic): manifiesto completo leído de `permissions.yaml`. `SkillRegistry.cargar_directorio()` descubre y carga skills; `_importar_tools()` usa `importlib` para cargar callables de `tools.py`. Métodos: `registrar_en_permission_manager()`, `herramientas_validas()`, `herramientas_confirmacion()`, `tools_adicionales()`, `listar()`, `get()`.
- **`skills/__init__.py`** — Exporta `Skill`, `SkillManifest`, `SkillRegistry`, `ToolDecl`.
- **5 skills integrados**: `browser/`, `files/`, `email/`, `terminal/` (tools via MCPBus), `calendar/` (tools en `tools.py` con osascript macOS — `calendar.listar`, `calendar.crear`, `calendar.eliminar`).
- **Cada skill declara**: `SKILL.md` (docs legibles), `permissions.yaml` (manifiesto declarativo), `examples.yaml` (ejemplos), `tools.py` (callables Python), `tests/` (tests del skill).
- **`core/planner.py`** — `Planner.__init__` acepta `skill_registry: Any | None`. Métodos `_herramientas_validas()` y `_herramientas_confirmacion()` combinan frozensets estáticos con los del registry. `validate_plan()` usa los métodos de instancia (no las constantes del módulo).
- **`core/agent.py`** — Constructor acepta `skill_registry: Any | None`. `__init__` llama `skill_registry.tools_adicionales()` y los incorpora a `self._herramientas` automáticamente.
- **`interface/api.py`** — `crear_servidor()` acepta `skill_registry`. Nuevo endpoint `GET /skills` (sin auth) devuelve `SkillsResponse`.
- **`interface/api_models.py`** — `SkillInfo(BaseModel)` + `SkillsResponse(BaseModel)` añadidos.
- **ADRs implícitos**: skills como capa declarativa sobre MCPBus (no reemplazo), calendar como skill con implementación propia (osascript), registry combina herramientas estáticas + skills (backward compat), GET /skills sin auth (info pública, no sensible).
- **Tests**: `tests/test_skills.py` (35 tests), más tests en `skills/*/tests/` (15 tests adicionales). **50/50 verde en 0.76s**. Suite completa: **425/429 verde + 1 skip** (3 fallos pre-existentes: telegram no instalado).

### PermissionManager — sistema de permisos por herramienta (2026-05-19)
- **`security/permission_manager.py`** (nuevo) — `ToolPolicy` (Pydantic): cada herramienta declara `nivel_riesgo`, `requiere_confirmacion`, `requiere_biometria`, `puede_modificar_archivos`, `puede_usar_red`, `puede_leer_pantalla`, `puede_acceder_credenciales`, `permisos_requeridos`. `PermissionManager.verificar()` es el único punto de decisión: default-deny si no hay política, modo read-only, modo dry-run, verificación macOS, autenticación biométrica (CRITICAL siempre), confirmación humana. `verificar_inyeccion()` detecta 14 patrones de prompt injection y sanitiza el contenido. Políticas por defecto para las 43 herramientas registradas.
- **`core/mcp_bus.py`** — Constructor acepta `permission_manager: PermissionManager | None`. `execute()` llama `verificar()` antes de ejecutar; si `dry_run=True` devuelve `MCPResult(success=True, data={"dry_run": True, ...})` sin tocar el servidor.
- **`core/agent.py`** — Constructor acepta `permission_manager`. `_EXTERNAL_CONTENT_TOOLS` (8 herramientas: browser, filesystem, mail, comms). `_ejecutar_herramienta()` llama `verificar_inyeccion()` sobre el resultado de herramientas externas y sustituye el contenido sanitizado si hay inyección.
- **`security/__init__.py`** — Exporta `PermissionManager`, `PermissionResult`, `ToolPolicy`, `RiskLevel`, `InjectionResult`, singleton `permission_manager`.
- **ADRs**: ADR-109 (default-deny sin política), ADR-110 (dry-run en MCPBus, no en servidor), ADR-111 (injection detection en _ejecutar_herramienta, no en percibir), ADR-112 (CRITICAL siempre biometría aunque requiere_confirmacion=False).
- **Tests**: `tests/test_permission_manager.py` — 42 tests: 6 políticas por defecto, 5 permitidas, 6 denegadas, 4 readonly, 5 dry-run, 13 injection, 3 integración MCPBus. **42/42 verde**.
- **Suite completa: 319/319 verde + 1 skip (fastmcp no instalado)**.

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

### Mejoras de robustez core/ (2026-05-19)

- **`requirements.txt`** — `langgraph>=0.2.31` (antes `>=0.2.0`). Habilita `langgraph.types.interrupt()` nativo.
- **`config/settings.py`** — `agent_step_timeout_seconds: int = 120`. `TIMEOUT_PASO` ya no está hardcodeado en `agent.py`.
- **`core/planner.py`** — `PasoAccion` añade `timeout_override: int | None = None` para pasos con latencia atípica (ej. `browser.navegar`). `estimate_complexity()` añade 4 señales nuevas: keywords masivos (`todos`, `todos los archivos`, `todo el proyecto`) +0.15; plan con >4 herramientas distintas +0.2; plan con herramientas destructivas (`filesystem.eliminar`, `terminal.ejecutar`) +0.15; historial >20 mensajes +0.1. Parámetros opcionales `historial` y `plan` mantienen compatibilidad hacia atrás.
- **`core/agent.py`**:
  - `TIMEOUT_PASO` eliminado; reemplazado por `settings.agent_step_timeout_seconds`. `_ejecutar_herramienta` usa `paso.timeout_override` si está presente (ADR-87).
  - `_esperar_usuario(sid, evento) → (cancelado, aprobado)`: helper que encapsula el patrón asyncio.Event + Lock (ADR-27), elimina duplicación de los dos bloques WAIT_USER y prepara la interfaz para `graph.interrupt()` (ADR-84).
  - **Runaway guard** (patrón OpenHands): `_RUNAWAY_VENTANA=6`, `_RUNAWAY_UMBRAL=3`. Antes de ejecutar cada paso se acumula `(herramienta, _hash_params(params))` en `AgentState.tool_call_history` (lista circular maxlen=6). Si la misma tupla aparece ≥3 veces: `tipo=error` "Loop detectado" + return inmediato sin ejecutar (ADR-85).
  - `_hash_params()`: fingerprint MD5 reproducible de parámetros para el guard (sin use for security).
  - `AgentState` añade `tool_call_history: list[tuple[str, str]]`.
- **`tests/test_core.py`** — `test_agent_runaway_guard`: plan con 4 pasos idénticos (misma herramienta, mismos params); el 3er dispara el guard antes de ejecutar y emite `tipo=error` con "Loop detectado".
- **ADRs**: ADR-84 (WAIT_USER → _esperar_usuario() helper; interfaz preparada para graph.interrupt() cuando el loop use graph.astream()), ADR-85 (runaway guard con list circular maxlen=6 en AgentState — lista en lugar de deque para compatibilidad con serialización JSON del SessionStore), ADR-86 (estimate_complexity() con 4 señales adicionales — parámetros opcionales para no romper router.py), ADR-87 (agent_step_timeout_seconds en settings; timeout_override por paso).
- **Suite: 274/274 verde (+ 1 skip fastmcp) en ~20s** (antes 266).

### Persistencia de sesiones + Dashboard + WebSocket state + Distribución overlay (2026-05-19)

- **`interface/session_store.py`** (nuevo) — `SessionStore`: serializa `AgentState` a JSON en `~/.jarvis/sessions/{session_id}.json` tras cada `ActualizacionAgente`. Al restaurar: si `waiting_for_user=True` con paso pendiente → se marca como fallido + `waiting_for_user=False` para forzar replanificación. `load()` verifica TTL y elimina expiradas. `cleanup_expired()` (async) escanea el directorio, elimina expiradas y corruptas. `list_sessions()` devuelve metadatos para el dashboard.
- **`interface/dashboard.py`** (nuevo) — HTML+JS vanilla: `build_dashboard_html()` genera el panel. Sin dependencias frontend externas. Muestra sesiones persistidas (task, estado, cuándo), audit log (últimas 50 entradas vía GET /audit), estado del sistema (ChromaDB, Ollama, RAM, MCP), botón cancelar (POST /cancel/{session_id}). Auto-refresh cada 5s con fetch().
- **`interface/api.py`** — `crear_servidor()` acepta `session_store: SessionStore | None`. Startup lifespan lanza `cleanup_expired()` como tarea background (migrado de `@app.on_event` a `lifespan`). `POST /chat` carga estado desde disco si existe y no hay tarea activa. `_run_agent_task()` acepta `initial_state` y guarda estado tras cada update. Nuevas rutas: `GET /` (dashboard HTML), `GET /sessions` (metadatos para el dashboard). WS `/ws`: tras `manager.connect()` envía `{"type":"session_state", "session_state":"idle|thinking|acting|waiting|done|error", "current_step": ..., "pending_confirmation": ... | null}`.
- **`core/agent.py`** — `self._estados: dict[str, AgentState]` para tracking por sesión. `get_state(session_id)` expone el último estado. `run()` acepta `initial_state: AgentState | None`; si se provee, reutiliza el estado previo y añade el nuevo mensaje. `self._estados[sid]` se actualiza tras cada mutación del estado dentro del loop. Limpieza en `finally`.
- **`config/settings.py`** — `session_ttl_hours: int = 24`.
- **`interface/swiftui/build.sh`** — Soporte de firma y notarización: si `APPLE_DEVELOPER_ID` está vacío → build sin firma (desarrollo local). Si está presente → `codesign --options runtime`, `xcrun notarytool submit --wait`, `xcrun stapler staple`. Carga `.env` automáticamente.
- **`Makefile`** — `make overlay` (release firmado), `make overlay-debug` (sin firma).
- **`.env.example`** — `SESSION_TTL_HOURS`, `APPLE_DEVELOPER_ID`, `APPLE_NOTARY_PROFILE`, `APPLE_BUNDLE_ID` con instrucciones.
- **`README.md`** — Sección "Overlay SwiftUI — instalación en macOS": desarrollo local, distribución paso a paso, notarización manual. Sección "Dashboard web". Tabla `make` actualizada.
- **ADRs**: ADR-80 (session_state WS message enviado al connect — permite al overlay sincronizar estado sin esperar al siguiente update del agente), ADR-81 (SessionStore best-effort — errores de I/O se loggean sin propagar, la persistencia nunca bloquea al agente), ADR-82 (lifespan en lugar de on_event deprecated — cleanup_expired() como create_task en startup), ADR-83 (system_context no se persiste — contiene datos de sistema que caducan; se repuebla en el siguiente ciclo percibir).
- **Tests nuevos** (14): `test_session_persists_across_restart`, `test_session_restores_agent_state`, `test_session_restores_messages`, `test_session_waiting_for_user_marked_failed`, `test_session_ttl_cleanup`, `test_session_load_returns_none_if_expired`, `test_session_load_returns_none_if_not_found`, `test_session_delete_removes_file`, `test_session_cleanup_removes_corrupt_files`, `test_list_sessions_returns_metadata`, `test_websocket_reconnect_sends_state`, `test_websocket_reconnect_sends_last_known_state`, `test_websocket_reconnect_pending_confirmation`, `test_dashboard_devuelve_html`, `test_sessions_sin_store_devuelve_lista_vacia`.
- **Suite completa: 291/291 verde (+ 1 skip fastmcp) en ~21s**.



### Mejoras de memoria — Mem0 + Zep + LangMem (2026-05-19)

- **`memory/long_term.py`** — Deduplicación activa en `store()`: antes de insertar, busca entradas similares en la misma categoría con `_search_with_scores()`. Si sim ≥ 0.99 → skip silencioso; sim ≥ `memory_dedup_threshold` (0.92) + Jaccard alto → complement (merge de contenidos + update); Jaccard bajo → contradict (expire la entrada antigua con `valid_until = ahora` + crea nueva). `MemoryEntry` añade `updated_at`, `version: int`, `valid_from: datetime | None`, `valid_until: datetime | None`. `search()` y `search_hybrid()` filtran expiradas por defecto (`include_expired: bool = False`). `count_expired()` cuenta entradas con `valid_until` pasado. Dedup loggea con `rich` a stderr.
- **`memory/procedural.py`** — `update_agent_instructions(feedback, confirm_callback)`: guarda instrucciones aprendidas en colección `jarvis_instructions`, requiere confirmación del usuario, archiva la más antigua si se supera el límite de 10 activas (`valid_until = ahora`). `get_agent_instructions()` devuelve hasta 10 instrucciones activas.
- **`memory/__init__.py`** — `HealthStatus(BaseModel)` con `status: Literal["healthy","degraded","down"]` y `details: dict`. `health_check()` ahora devuelve `HealthStatus` con: total entradas, entradas expiradas, latencia real de query (embed + search, umbral 500ms), estado de vault. Expone `get_agent_instructions()` y `update_agent_instructions()` en la fachada.
- **`mcp_servers/server_memory.py`** — `memory.health` serializa `HealthStatus.model_dump()`.
- **`core/agent.py`** — `_percibir()` carga instrucciones aprendidas del procedural y las añade al `memory_context` como sección "Instrucciones aprendidas".
- **`config/settings.py`** — `memory_dedup_threshold: float = 0.92`.
- **ADRs**: ADR-76 (dedup solo dentro de la misma categoría para evitar falsos positivos cross-category), ADR-77 (valid_until serializado como ISO string en metadata_json — compatible con ADR-31), ADR-78 (instrucciones aprendidas en colección `jarvis_instructions` separada — sin interferir con workflows), ADR-79 (health_check mide latencia con query real, umbral 500ms para "degraded").
- **Tests nuevos** (10): `test_memory_dedup_skip`, `test_memory_dedup_complement`, `test_memory_dedup_update_version`, `test_temporal_validity_filtering`, `test_search_hybrid_excludes_expired`, `test_count_expired`, `test_procedural_update_instructions`, `test_procedural_update_instructions_rejected`, `test_procedural_instructions_max_limit`, `test_agent_loads_learned_instructions`.
- **`test_memory_health_check`** actualizado a `HealthStatus`.
- **Suite completa: 276/276 verde (+ 1 skip fastmcp) en ~21s**.

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

## ✅ Completado recientemente

### Mejoras de percepción — Verifier + Grounding + Runaway Guard + OCR adaptativo (2026-05-19)

Basadas en patrones de clawdcursor, Self-Operating Computer y el paper Screen2AX (2025).

- **`perception/verifier.py`** (nuevo) — `ActionVerifier` con `snapshot_before()` y `verify_action_result()`. 4 señales: `pixel_diff` (PIL ImageChops), `ocr_delta` (palabras nuevas en OCR), `window_state` (app activa + título), `accessibility_change` (rol/valor del elemento focalizado). `VerificationResult` con `success: bool`, `signals_passed: int`, `signals_total: int`, `details: dict[str, bool]`. Umbral: ≥2 señales → success=True.
- **`perception/accessibility.py`** — `Bounds` añade `center_x: float` y `center_y: float` calculados en `__post_init__` (compatibles con `slots=True`). Nueva función `get_element_coordinates(app_name, element_description) → Bounds | None`: AX primero (recorre árbol por label/value/role), fallback OCR (pytesseract `image_to_data` + coincidencia textual). Helpers internos: `_buscar_por_ax`, `_buscar_en_arbol`, `_buscar_por_ocr`.
- **`perception/screenshot.py`** — Runaway guard module-level: `_CAPTURAS_IDENTICAS`, `_ULTIMO_HASH_CAPTURA`, `ALERTA_PANTALLA_ESTATICA` (asyncio.Event). `_actualizar_runaway_guard()` calcula hash MD5 de cada captura; 5 consecutivas idénticas → WARNING + reduce rate a 0.5fps (`_INTERVALO_MINIMO = 2.0`); 10+ → ERROR + `ALERTA_PANTALLA_ESTATICA.set()`. Captura diferente → reset automático de todo el estado.
- **`perception/ocr.py`** — Detección de tipo de contenido: `_detectar_psm()` devuelve PSM 6 (código: `def`, `class`, `import`…) o PSM 4 (tablas: caracteres `│`, `─`…) o PSM 3 (texto corrido por defecto). `_tesseract_con_psm_sync()` ejecuta Tesseract con el PSM seleccionado. `extract_text()` usa PSM adaptativo para imágenes >500KB cuando Tesseract supera el umbral de confianza. `_umbral_confianza()` lee `settings.ocr_confidence_threshold * 100` (0-100) con fallback a 60.0.
- **`actions/keyboard_mouse.py`** — `click_elemento(descripcion: str, app_name: str = "") → bool`: localiza el elemento con `get_element_coordinates()` y hace click en `bounds.center_x`, `bounds.center_y`.
- **`config/settings.py`** — `ocr_confidence_threshold: float = 0.60` y `verifier_pixel_diff_threshold: float = 0.01`.
- **`core/agent.py`** — `ActionVerifier` importado. `_COMPUTER_ACTION_TOOLS` frozenset con 13 herramientas (teclado.*, browser.navegar, browser.click, browser.fill, browser.submit). `verifier: ActionVerifier | None = None` en `__init__`. En el loop: snapshot_before antes de computer_action tools → verify_action_result después → si `success=False and signals_passed < 2`, sobreescribe `resultado.exito=False` con mensaje de verificación para que el reflector decida REINTENTAR.
- **`perception/__init__.py`** — Exports añadidos: `get_element_coordinates`, `ALERTA_PANTALLA_ESTATICA`, `ActionVerifier`, `VerificationResult`.
- **ADRs**: ADR-88 (ActionVerifier — snapshot paralelo con gather; falls back graceful si screenshot/AX falla), ADR-89 (get_element_coordinates — AX primero, OCR fallback; Screen2AX 2025: 46% metadata pobre), ADR-90 (runaway guard en screenshot.py — hash MD5 exacto como proxy de pixel_diff=0%; Event module-level para señal al agente), ADR-91 (PSM adaptativo por tipo de contenido — detección con primera pasada PSM 3; código→6, tabla→4, texto→3), ADR-92 (verifier en agent.py — solo para _COMPUTER_ACTION_TOOLS; override resultado si <2 señales para que reflector propague REINTENTAR).
- **Fix preexistente**: `test_e2e_agent_max_steps` aceptaba solo "Límite" pero el runaway guard (umbral=3) dispara antes de MAX_PASOS=3 cuando los pasos son idénticos. El test ahora acepta ambas condiciones de parada ("Límite" o "Loop detectado") — ambas son mecanismos válidos de seguridad.
- **Tests añadidos** (12): `test_bounds_calcula_center_automaticamente`, `test_verify_action_success_dos_señales`, `test_verify_action_failure_sin_cambios`, `test_verify_fallback_snapshot_falla`, `test_capturas_distintas_no_acumulan_contador`, `test_cinco_identicas_reduce_rate`, `test_diez_identicas_emite_alerta`, `test_captura_diferente_resetea_alerta`, `test_ocr_strategy_code_region`, `test_ocr_strategy_form_region`, `test_grounding_via_ax`, `test_grounding_via_ocr_fallback`.
- **Suite completa: 304/304 verde (+ 1 skip fastmcp) en ~21s**.

## ✅ Completado recientemente

### Mejoras de robustez actions/ — OpenHands CodeAct + MacOS-Agent patterns (2026-05-19)

- **`actions/system.py`** — `AppleScriptError(Exception)` con campos `error_code: int`, `app_name: str`, `suggestion: str`. `_parsear_error_as()` extrae el código de error de stderr con regex `\((-?\d+)\)` y construye la sugerencia desde un dict tipado. `_applescript()` modificado: captura stderr, reintenta 1 vez con delay 0.5s para código -1708 ("event not handled", timing transitorio), loggea `WARNING` en fallos no-transitorios. Nuevo método público `ejecutar_applescript_estricto()` que lanza `AppleScriptError` si el script falla. `_extraer_app()` extrae el nombre de app del script para el error.
- **`actions/filesystem.py`** — `DryRunResult(dataclass)` y `ActionVerificationError(Exception)` exportados públicamente (importables en terminal/mail/imessage). `eliminar_archivo()`, `eliminar_directorio()` y `mover_archivo()` añaden parámetro `dry_run: bool = False`: si True, devuelven `DryRunResult` sin ejecutar. Verificación post-acción: eliminar verifica `not objetivo.exists()`, mover verifica `not src.exists() and dst.exists()`. Viola → `ActionVerificationError(accion, esperado, actual)`.
- **`actions/terminal.py`** — `dry_run: bool = False` en `ejecutar_comando()`: si True devuelve `DryRunResult` sin lanzar el subproceso (con descripción del riesgo: BLOCKED/confirmación requerida/libre). Log `WARNING` automático cuando `returncode != 0` con los primeros 300 chars de stderr. Importa `DryRunResult` de `actions.filesystem`.
- **`actions/comms/whatsapp.py`** — Refactor: `pagina` ahora es opcional (`pagina: Any | None = None`). Nuevo classmethod `initialize_session(session_dir, timeout_qr_s=60)`: lanza Playwright con `launch_persistent_context` (Chromium no-headless, session_dir persistente en `~/.jarvis/whatsapp_session/`), navega a WhatsApp Web, verifica sesión en 5s, si no hay QR espera hasta `timeout_qr_s`. Nuevo método `cerrar_sesion()` para cleanup de `_playwright_propio`/`_context_propio`. Soluciona la deuda "WhatsApp MCP requiere sesión inyectada".
- **`actions/comms/telegram.py`** — `TelegramNotConfiguredError(Exception)` con mensaje de ayuda completo (paso a paso: BotFather + .env). Validación en `__init__`: si `token` vacío o solo espacios → lanza `TelegramNotConfiguredError` antes de instanciar `Bot`.
- **`actions/comms/mail.py`** — `dry_run: bool = False` en `enviar_mensaje()`. Importa `DryRunResult` de `actions.filesystem`.
- **`actions/comms/imessage.py`** — `dry_run: bool = False` en `enviar_mensaje()`. Importa `DryRunResult` de `actions.filesystem`.
- **`config/settings.py`** — `agent_dry_run_mode: bool = False` para activar dry_run globalmente desde configuración.
- **ADRs**: ADR-93 (AppleScriptError con retry -1708 — -1708 es "event not handled", fallo de timing al enviar evento AppleScript a app no lista; único reintento tras 0.5s), ADR-94 (DryRunResult y ActionVerificationError en filesystem.py como tipos compartidos — evita módulo _types.py sin necesidad; terminal/mail/imessage importan desde allí sin ciclos), ADR-95 (initialize_session usa launch_persistent_context — la API nativa de Playwright para sesiones con perfil de usuario persistente; evita gestionar cookies manualmente), ADR-96 (dry_run en capa de acción, no en el agente — permite que el planner simule planes antes de ejecutarlos sin cambiar la lógica del loop).
- **Tests añadidos** (19): `test_applescript_app_not_running`, `test_applescript_retry_on_transient`, `test_applescript_error_strict_raises`, `test_applescript_error_fields`, `test_whatsapp_session_init_no_session`, `test_whatsapp_session_reutiliza_sesion_existente`, `test_telegram_missing_token_raises`, `test_telegram_whitespace_token_raises`, `test_telegram_valid_token_does_not_raise`, `test_filesystem_delete_verification`, `test_filesystem_move_verification_origen_persiste`, `test_filesystem_delete_ok_no_verification_error`, `test_filesystem_move_ok_no_verification_error`, `test_filesystem_dry_run_delete`, `test_filesystem_dry_run_move`, `test_terminal_dry_run_dangerous`, `test_terminal_dry_run_safe_command`, `test_mail_dry_run_enviar`, `test_imessage_dry_run_enviar`.
- **Suite completa: 323/323 verde (+ 1 skip fastmcp) en ~23s** (antes 304).

### Mejoras de observabilidad models/ — LiteLLM + RouteLLM patterns (2026-05-19)

- **`config/settings.py`** — `ollama_cost_per_second: float = 0.0001` y `litellm_enabled: bool = False`.
- **`models/_common.py`** — `EstadoCircuito(StrEnum)` (CLOSED/OPEN/HALF_OPEN) + `CircuitBreaker`: 3 fallos en 60s → OPEN 5min → HALF_OPEN (una petición de prueba). `registrar_fallo()`, `registrar_exito()`, `is_open()`, `estado()`. `log_model_call()` async: registra métricas en audit_log con `action_type="model_call"` sin contenido (privacidad por diseño) — `modelo`, `tokens_input`, `tokens_output`, `cost_usd`, `cache_hit`, `session_id`.
- **`models/kimi.py`** — `TARIFAS_USD = {"kimi-k2.6": {"input": 0.15, "output": 0.15}, ...}`. `_coste_usd()` estático. `audit_log` param en `__init__`. Calcula `cost_usd` y llama `log_model_call()` en `complete()`. Import diferido `security.audit_log`.
- **`models/openrouter.py`** — `audit_log` param. Parsea `float(uso.get("cost", 0.0))` desde la respuesta de OpenRouter (ya en USD). Llama `log_model_call()`. Import diferido.
- **`models/ollama_client.py`** — `audit_log` param. `cost_usd = (duration_ms / 1000) * settings.ollama_cost_per_second`. Llama `log_model_call()`. Import diferido.
- **`models/deepseek.py`** — `audit_log` param (ya tenía cálculo de coste). Llama `log_model_call()` con `cache_hit=bool(tokens_cached)`. Import diferido.
- **`core/router.py`** — `circuit_open: bool = False` en `ModelSelection`. `ModelRouter` añade `_circuitos: dict[ModeloDestino, CircuitBreaker]` y `_total_cost_usd: float`. Si el destino elegido tiene el circuito OPEN: escala automáticamente al primer fallback y marca `circuit_open=True` y prefija la razón con `"circuit_open→"`. Métodos: `registrar_coste(cost_usd)`, `total_cost_usd` (property), `registrar_fallo_modelo(destino)`, `registrar_exito_modelo(destino)`, `_circuito(destino)` (lazy init).
- **`interface/api_models.py`** — `total_cost_usd: float = 0.0` en `SystemStatus`.
- **`interface/api.py`** — `router: ModelRouter | None = None` en `crear_servidor()`. `GET /status` expone `router.total_cost_usd`.
- **`models/litellm_adapter.py`** (nuevo) — `LiteLLMAdapter(BaseModel)` sobre `litellm.acompletion()`. Solo activo con `LITELLM_ENABLED=true`. `LiteLLMNotEnabledError` con mensaje de ayuda. Parsea `response._hidden_params.response_cost`. Soporta `complete()` y `stream()`.
- **`requirements.txt`** — Comentario con instrucción opcional: `litellm>=1.40.0`.
- **ADRs**: ADR-97 (CircuitBreaker por proveedor en ModelRouter — lazy init, 3/60s→OPEN, 5min→HALF_OPEN), ADR-98 (log_model_call sin contenido — privacidad primero; solo métricas en audit_log), ADR-99 (total_cost_usd acumulado en ModelRouter, no en settings — el router ya es singleton por sesión; exposición en /status), ADR-100 (LiteLLMAdapter guard con litellm_enabled=False — no añade importación de litellm en el bundle principal; solo carga si habilitado).
- **Tests añadidos** (17): `TestCircuitBreaker` (5: estado_inicial, abre_tras_max_fallos, exito_cierra, half_open_tras_recuperacion, fallos_fuera_de_ventana), `TestLogModelCall` (2: sin_audit_no_falla, llama_log_action), `TestCostesModelos` (3: kimi_calcula_coste, openrouter_usa_usage_cost, ollama_coste_por_duracion), `TestLiteLLMAdapter` (1: error_cuando_deshabilitado), `TestCircuitBreakerRouter` (3: circuit_open_false_defecto, escala_a_fallback, exito_cierra_circuito), `TestCostesRouter` (3: total_cost_inicial, registrar_coste_acumula, property).
- **Suite completa: 340/340 verde (+ 1 skip fastmcp) en ~22s** (antes 323).

## 🔄 En progreso

### Goals de cierre de integración (2026-06-30)

Goals G1–G8 definidos por el usuario. Estado:

- ✅ **G3 — Reconexión WS con session_id correcto** — `WebSocketClient` guarda el `sessionId`
  real y lo reusa en `_scheduleReconnect`; antes usaba el literal `"reconnect"` y perdía el
  buffer (deque 50) y el scoping de confirmaciones. Commit `f56f7fe`.
- ✅ **G4 — Sync de estado al reconectar (ADR-80)** — `_receiveLoop` ahora distingue
  `type=="session_state"` (sonda `MessageTypeProbe`) y lo decodifica con `SessionStateMessage`;
  antes solo decodificaba `AgentUpdate` y lo descartaba. `applySessionState()` reconstruye una
  confirmación pendiente. Commit `f56f7fe`.
- ✅ **G5 — Wiring de arranque** — `_seleccionar_modelo()` (Kimi→DeepSeek→OpenRouter→Ollama),
  carga de skills, `ModelRouter` y health check ChromaDB v2/v1. Commit `28a62d9`. Suite 466 verde.
- ✅ **G6 — Elementos afectados en ConfirmationCard** — el overlay descartaba el broadcast de
  `ConfirmationManager` (`type=waiting` con `data`, que trae `confirmation_id` real y
  `affected_items`). Nuevo `ConfirmationBroadcast` + `applyConfirmation()`. Commit `f56f7fe`.
- ✅ **G7 — Auto-init de WhatsApp** — `ServidorComms(auto_init_whatsapp=True)` +
  `_asegurar_whatsapp()` llama `WhatsApp.initialize_session()` bajo demanda. Test añadido.
  Commit `f69d3a4`.
- ✅ **G8 — Deadlock de auth bajo cancelación** — `AuthManager.authenticate()` resuelve el
  future de forma síncrona en el `finally` (sin `async with self._lock`, cuyo await podía ser
  interrumpido por `CancelledError` y colgar a los followers). Test de cancelación. Commit `f69d3a4`.
- ✅ **G1 — Humo e2e real (DoD cumplido)** — Ejecutado un `/chat` de principio a fin contra la
  app FastAPI **real** (no `Agente.run()` directo): `POST /chat` → `200 {status: started}`,
  `GET /stream/{sid}` → stream SSE `thinking → done`, con `Agente` real, `Planner`/`Reflector`
  reales, modelo real (`qwen2.5:0.5b`), MCP bus real y ChromaDB degradado (Docker apagado,
  ADR-33). `main.py` importa sin errores y `_seleccionar_modelo()` recorre los 4 proveedores.
  El sistema funcionó fuera de los mocks por primera vez. Modelo `qwen2.5:0.5b` (único que cabe
  en ~1.6 GB libres; cloud fuera: Kimi 429, DeepSeek 402, OpenRouter 401).
  `models/ollama_client.py`: añadidos modelos pequeños a `RAM_APROXIMADA_GB`.
  **Pendiente (calidad, no bloqueante):** Docker→ChromaDB + un modelo capaz o creds cloud con
  saldo. Suite: 466 verde + 1 skip.
- ⛔ **G2 — Build del overlay** — BLOQUEADO: solo hay Command Line Tools, no Xcode completo,
  así que `xcodebuild` no puede correr. `swiftc -typecheck` confirma que todos los tipos
  cross-file resuelven (los errores de SourceKit eran falsos positivos) y que los cambios de
  G3/G4/G6 no introducen ninguna clase nueva de error respecto a HEAD.

---

## ✅ Completado recientemente

### Debug línea a línea — bugs encontrados y corregidos (2026-05-19)

Auditoría exhaustiva del código fuente completo (todos los archivos de `core/`, `memory/`, `security/`, `models/`, `actions/`, `perception/`, `mcp_servers/`, `interface/`, `main.py`).

**Bugs MEDIO corregidos:**

- **`memory/short_term.py`** — Race condition async en `_ensure_capacity()`: los mensajes se extraen del buffer antes del `await self.summarize()` (LLM call), pero los lectores (`get_messages`, `get_context_window`, `get_last_n`, `search`) leían `self._buffer` sin lock, viendo un estado intermedio sin los mensajes eliminados y sin el resumen. **Fix**: (1) todos los lectores ahora adquieren `self._lock` y trabajan sobre un snapshot local; (2) `_ensure_capacity` libera el lock antes de `await self.summarize()` y lo reacquiere en `finally`, evitando bloquear lectores durante el LLM call. ADR-105.
- **`actions/keyboard_mouse.py`** — `self._pyag` nunca inicializado cuando Quartz disponible: `_inicializar_pyautogui()` solo se llamaba si `not _quartz_disponible`, pero `arrastrar`, `scroll`, `escribir_texto`, `pulsar_tecla`, `atajo`, `tecla_abajo`, `tecla_arriba` accedían a `self._pyag` sin comprobación → `AttributeError` en producción con Quartz disponible. **Fix**: `_inicializar_pyautogui()` se llama siempre (Quartz cubre mouse, pyautogui cubre teclado y drag/scroll). ADR-106.
- **`interface/api.py`** — `GET /sessions` llamaba `session_store.list_sessions()` de forma síncrona en el event loop, con I/O de disco (`path.stat()`, `path.read_bytes()`) → bloqueo del loop. **Fix**: `await asyncio.to_thread(session_store.list_sessions)`. ADR-107.

**Bugs BAJO corregidos:**

- **`perception/ocr.py`** — `_INDICADORES_CODIGO` definida dos veces: `frozenset` en línea 52 (rica, 18 keywords) y `set` en línea 284 (reducida, 9 keywords). Python usa la última → `_detectar_psm` perdía keywords `fn`, `func`, `var`, `let`, `const`, `//`, `/*`, `#include`, `public`, `private`. **Fix**: eliminada la definición duplicada de línea 284; `_inferir_tipo` reutiliza la `frozenset` global. ADR-108.

**Bugs identificados (sin fix — aceptados o complejidad baja justificación):**

- **`security/auth.py`** — Si la tarea líder de Face ID es cancelada durante `asyncio.to_thread`, el `async with self._lock` en el bloque `finally` puede ser interrumpido por `CancelledError`, dejando `self._in_flight` sin resolver y bloqueando followers indefinidamente. El comentario en línea 100 ya describe este riesgo. Severidad baja en producción (cancellación de biometría es rara). Se documenta como deuda técnica.
- **`models/openrouter.py`** — `_elegir_free()` sin single-flight: dos llamadas concurrentes antes de cachear pueden hacer doble petición a `/models`. Inofensivo (la segunda escritura sobreescribe la primera con el mismo resultado).
- **`models/ollama_client.py`** — Variable `respuesta` reutilizada para `httpx.Response` y `ModelResponse` en `complete()`. Confuso pero funcional.

**ADRs**: ADR-105 (ShortTermMemory lock — lectores con snapshot + release durante LLM call), ADR-106 (pyautogui siempre inicializado — Quartz para mouse, pyautogui para teclado y drag; sin atributo condicional), ADR-107 (list_sessions con asyncio.to_thread — I/O disco siempre offloaded), ADR-108 (_INDICADORES_CODIGO única definición — eliminar redefinición que sobreescribía la frozenset rica).

- **Suite: 348/353 verde** (348 = 281 en non-actions + 67 en actions sin playwright/telegram; los 5 deselected son preexistentes: playwright no instalado + telegram). Sin regresiones.

---

### Mejoras core/actions/ — patrones JARVIS-1, SWE-agent e Instructor (2026-05-19)

Basadas en análisis comparativo con Agent-Zero, JARVIS-1, SWE-agent, Letta/MemGPT, Zep/Graphiti, Devon, AgentBench e Instructor.

- **`core/reflector.py`** — `explain_failure(paso, resultado, contexto_sistema)`: genera en lenguaje natural una explicación del por qué falló el paso y qué debe evitar el planificador. Patrón JARVIS-1 Self-Explain. Fallback: si el modelo falla, devuelve el error original sin propagar excepción. Prompt en `_PROMPT_EXPLAIN` (constante módulo).
- **`core/agent.py`** — En el bloque `REPLANIFICAR`: llama `reflector.explain_failure()` antes de `planner.replan()` e inyecta el análisis como `error_enriquecido = f"{error}\n\nAnálisis del fallo: {explicacion}"`. El planificador recibe contexto rico para generar alternativas más precisas.
- **`core/planner.py`** — `validate_plan()` añade validación de orden topológico: si un paso B aparece antes que el paso A del que depende, reporta `"violación de orden topológico"`. Implementado con `id_a_indice` dict O(n). Compatible con la detección de ciclos existente.
- **`core/planner.py`** — `plan()` añade fallback resiliente (patrón Instructor): si `_parsear()` lanza excepción (JSON inválido), loggea WARNING y devuelve un `PlanEjecucion` con un único paso `pedir_aclaracion`. La tarea no se aborta — el agente pregunta al usuario en lugar de crashear.
- **`actions/terminal.py`** — `ResultadoComando` añade `lineas_stdout: int` (property) y `formato_acotado(max_lineas: int = 100) -> str`: header estructurado `[Comando: X | Dir: Y | Cód: Z | N líneas | Tms]`, cuerpo truncado si excede `max_lineas`, footer `[... N líneas más omitidas]` o `[Fin]`. Patrón SWE-agent bounded observations — da contexto posicional al LLM sobre el output.
- **ADRs**: ADR-101 (explain_failure en reflector — el replan recibe análisis LLM del fallo, no solo el error crudo; fallback fail-safe devuelve error original), ADR-102 (orden topológico en validate_plan — detección O(n) de forward-references en depende_de; complementa la detección de ciclos existente), ADR-103 (fallback a pedir_aclaracion en plan() — JSON inválido nunca aborta la sesión; el agente sigue vivo y puede recuperarse), ADR-104 (formato_acotado en ResultadoComando — el header da al LLM contexto sin prompt adicional; max_lineas=100 por defecto, ajustable por herramienta).
- **Tests añadidos** (13): `test_planner_validate_topological_order_invalido`, `test_planner_validate_topological_order_valido`, `test_planner_json_invalido_devuelve_aclaracion`, `test_reflector_explain_failure_usa_modelo`, `test_reflector_explain_failure_fallback_si_error`, `test_lineas_stdout_vacio`, `test_lineas_stdout_una_linea`, `test_lineas_stdout_sin_newline_final`, `test_lineas_stdout_multiple`, `test_formato_acotado_header_presente`, `test_formato_acotado_trunca_si_excede`, `test_formato_acotado_sin_truncar`, `test_formato_acotado_codigo_error`.
- **Suite: 353/353 verde (+ 1 skip fastmcp) en ~21s** (antes 340).

---

## ⏳ Siguientes candidatos

1. ~~**Persistencia de sesiones**~~ — resuelto 2026-05-19 (`interface/session_store.py`).
2. ~~**Distribución del overlay**~~ — resuelto 2026-05-19 (`build.sh` con firma/notarización, `make overlay`).
3. ~~**Dashboard web**~~ — resuelto 2026-05-19 (`interface/dashboard.py`, `GET /`, `GET /sessions`).
4. ~~**Scoping de confirmaciones por sesión**~~ — resuelto 2026-05-19 (hallazgo crítico del auditor).
5. ~~**Migración FastMCP + scoping herramientas + health check**~~ — resuelto 2026-05-19.
6. ~~**Mejoras de memoria (Mem0 + Zep + LangMem)**~~ — resuelto 2026-05-19.
7. ~~**Mejoras robustez core/ (LangGraph interrupt, runaway guard, estimate_complexity, timeout configurable)**~~ — resuelto 2026-05-19.
8. ~~**Patrones JARVIS-1 + SWE-agent + Instructor en core/ y actions/**~~ — resuelto 2026-05-19.
9. **Auto-update del overlay** — sistema de versionado + actualización automática desde servidor de distribución. (Pendiente: requiere servidor externo.)
10. **STT/TTS** — integración Groq Whisper + Kokoro local para interacción por voz.
11. **Integración n8n** — workflows para notificaciones proactivas y tareas programadas.
12. **Zep/Graphiti bi-temporal** — complementar ChromaDB con grafo de conocimiento temporal (bi-temporal edges, retrieval φ→ρ→χ). Patrón documentado en ADR candidato.
13. **Letta `request_heartbeat`** — el agente señaliza explícitamente si necesita continuar en lugar de que el loop asuma continuación. Cambio en `ActualizacionAgente` + loop de agent.py.

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

### 2026-05-19 (Mejoras models/ — observabilidad)
- ADR-97: **CircuitBreaker por proveedor en ModelRouter** — lazy init con `_circuito(destino)`. Si OPEN al momento de `route()`, escala al primer fallback de la cadena y marca `circuit_open=True`. El caller (core/agent.py) debe llamar `registrar_fallo_modelo` y `registrar_exito_modelo` según el resultado de la llamada real.
- ADR-98: **log_model_call sin contenido** — privacidad primero: solo se registran métricas (tokens, latencia, coste, cache_hit) en el audit_log con `action_type="model_call"`. El contenido de los mensajes nunca llega al log.
- ADR-99: **total_cost_usd en ModelRouter** — el router es singleton por sesión y es el punto natural de acumulación de costes. Se expone en `/status` para el dashboard. No se persiste (se acumula desde el arranque del proceso, como un contador de sesión).
- ADR-100: **LiteLLMAdapter solo carga litellm si LITELLM_ENABLED=true** — `import litellm` está dentro del `__init__` y de cada método, nunca en el módulo. Evita añadir litellm (~10 MB) al bundle principal. El `LiteLLMNotEnabledError` da instrucciones claras de activación.

### Deudas previas
- WhatsApp MCP: ~~requiere sesión inyectada~~ → resuelto 2026-05-19 (`initialize_session()`). El servidor MCP en `server_comms.py` puede llamar a `initialize_session()` en lugar de esperar inyección; pendiente actualizar el adaptador.
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
