# JARVIS — Arquitectura

> Documento vivo. Cualquier cambio estructural debe actualizarlo en el mismo PR.

## 1. Visión

JARVIS es un agente autónomo que vive en un Mac (M3, 8GB RAM). Su trabajo es **percibir** el sistema, **decidir** qué hacer con la ayuda de LLMs (locales y remotos), y **actuar** sobre el sistema operativo del usuario, siempre bajo supervisión y con auditoría completa.

Las tres restricciones que dominan el diseño:
1. **Privacidad**: los datos sensibles **nunca** salen de la máquina.
2. **Memoria escasa**: 8 GB de RAM compartidos con el sistema y el navegador.
3. **Reversibilidad**: toda acción destructiva exige confirmación humana y queda registrada.

---

## 2. Diagrama de capas

```
                     ┌────────────────────────────────────────────────┐
                     │              Cliente (CLI / overlay)           │
                     └──────────────────────┬─────────────────────────┘
                                            │ HTTP + WebSocket
                                            ▼
        ┌─────────────────────────────────────────────────────────────────┐
        │                       interface/                                │
        │   FastAPI (api.py)            WebSocket (websocket.py)          │
        └──────────────────────┬──────────────────────────────────────────┘
                               │
                               ▼
        ┌─────────────────────────────────────────────────────────────────┐
        │                          core/                                  │
        │                                                                 │
        │   ┌──────────┐   ┌──────────┐   ┌────────────┐   ┌───────────┐  │
        │   │  agent   │──▶│  router  │──▶│  planner   │──▶│ reflector │  │
        │   └────┬─────┘   └────┬─────┘   └────────────┘   └───────────┘  │
        │        │              │                                         │
        └────────┼──────────────┼─────────────────────────────────────────┘
                 │              │
                 │              ▼ (decide modelo)
                 │      ┌──────────────────────────────────────────────┐
                 │      │                  models/                     │
                 │      │  base • kimi • deepseek • ollama • OR • emb. │
                 │      └──────────────────────────────────────────────┘
                 │
                 ▼  (lee / escribe contexto)
        ┌─────────────────────────────────────────────────────────────┐
        │                          memory/                            │
        │  short_term · episodic · procedural · long_term · vault     │
        │            (long_term y episodic → ChromaDB)                │
        └─────────────────────────────────────────────────────────────┘

                        ▲                            ▲
                        │ (vía MCP servers)          │ (vía MCP servers)
                        │                            │
        ┌───────────────┴─────────────┐  ┌───────────┴────────────────┐
        │         perception/         │  │           actions/         │
        │  screenshot · ocr ·         │  │  filesystem · browser ·    │
        │  accessibility · system     │  │  system · keyboard_mouse · │
        │                             │  │  terminal · comms/*        │
        └─────────────────────────────┘  └────────────────────────────┘

        ┌─────────────────────────────────────────────────────────────┐
        │                       mcp_servers/                          │
        │  filesystem · browser · system · comms · code · memory      │
        │     (única superficie pública para herramientas LLM)        │
        └─────────────────────────────────────────────────────────────┘

        ┌─────────────────────────────────────────────────────────────┐
        │             security/  (transversal a todas las capas)      │
        │      auth · sandbox · confirmation · audit_log              │
        └─────────────────────────────────────────────────────────────┘

        ┌─────────────────────────────────────────────────────────────┐
        │                          config/                            │
        │      settings (pydantic-settings) · models_config · prompts │
        └─────────────────────────────────────────────────────────────┘
```

### Reglas de dependencia (estrictas)

```
interface  ──▶  core
core       ──▶  models, memory, security
core       ──▶  mcp_servers (NO directo a actions/perception)
mcp_servers──▶  actions, memory, perception
memory     ──▶  models.embeddings
actions    ──▶  security
perception ──▶  (sin dependencias de capas superiores)
config     ──▶  (importable desde cualquier capa)
security   ──▶  (importable desde cualquier capa)
```

Nada apunta hacia arriba. Si una clase necesita "subir", se invierte la dependencia (callback, evento, queue).

---

## 3. Flujo de una petición

```
Usuario ──"resume mis correos no leídos"──▶ FastAPI /chat
                                              │
                                              ▼
                                   Agente.procesar(texto)
                                              │
                ┌─────────────────────────────┼──────────────────────────┐
                │                             │                          │
                ▼                             ▼                          ▼
       Memoria corto plazo          Router.decidir()            AuditLog.registrar
       (añade el mensaje)           ├─ ¿hay PII? → LOCAL        ("peticion_recibida")
                                    ├─ ¿largo? → KIMI
                                    └─ ¿complejo? → DEEPSEEK
                                              │
                                              ▼
                                   Planner.crear_plan(texto)
                                              │
                                              ▼
                                          ┌──────┐
                                  ┌──────▶│ Plan │──────┐
                                  │       └──────┘      │
                                  ▼                     ▼
                       (paso destructivo)       (paso seguro)
                                  │                     │
                                  ▼                     │
                  GestorConfirmacion.solicitar          │
                                  │                     │
                                  ▼                     ▼
                         ¿aprobado?         MCP server.ejecutar(herramienta, args)
                            │ │                         │
                       sí ──┘ └── no  ──▶ STOP          ▼
                                              actions/* o memory/*
                                                        │
                                                        ▼
                                            Resultado del paso
                                                        │
                                                        ▼
                                       Reflector.reflexionar(plan, resultados)
                                                        │
                                                        ▼
                                          Si "aprendizaje" → memoria episódica
                                                        │
                                                        ▼
                                                  Respuesta al usuario
                                                        │
                                                        ▼
                                            AuditLog.registrar("reflexion")
```

---

## 4. Modelo de privacidad y enrutado

El **Router** (`core/router.py`) es la pieza más sensible: decide a qué modelo va cada mensaje. Cualquier fuga aquí es una fuga al exterior.

| Condición                              | Decisión                |
|----------------------------------------|--------------------------|
| Detecta PII (DNI, IBAN, TC, secrets)   | `LOCAL` (Ollama)         |
| Marcadores de razonamiento profundo    | `DEEPSEEK_REASONER`      |
| Contexto > 32k tokens estimados        | `KIMI` (128k)            |
| Petición compleja sin PII              | `DEEPSEEK`               |
| Resto                                   | `LOCAL`                  |

Las regex viven en `core/router.py` y deben tener cobertura al 100% en tests parametrizados.

---

## 5. Modelo de memoria

Cuatro capas con propósitos distintos:

| Capa                | Backend         | Vida útil          | Propósito                                          |
|---------------------|-----------------|--------------------|----------------------------------------------------|
| `MemoriaCortoPlazo` | deque en RAM    | sesión             | Ventana de conversación que se manda al modelo     |
| `MemoriaEpisodica`  | ChromaDB        | persistente        | Sesiones, eventos, aprendizajes del reflector      |
| `MemoriaProcedural` | ChromaDB + dict | persistente        | Skills/recetas reutilizables                       |
| `MemoriaLargoPlazo` | ChromaDB        | persistente        | Hechos sueltos, búsqueda semántica                 |
| `Vault`             | filesystem MD   | persistente        | Notas markdown del usuario (Obsidian-style)        |

Embeddings: **siempre** locales vía Ollama (`nomic-embed-text`). Nunca embeddings remotos.

---

## 6. Seguridad

### Capas de defensa
1. **Auth** (`security/auth.py`): tokens efímeros con HMAC; sesiones con expiración.
2. **Sandbox** (`security/sandbox.py`): rutas R/W permitidas, lista blanca de binarios.
3. **Validación**: todo input externo → Pydantic. Todo path → `_validar()`.
4. **Confirmación** (`security/confirmation.py`): timeout fail-closed sobre acciones destructivas.
5. **Auditoría** (`security/audit_log.py`): JSONL append-only, una línea por evento.

### Invariantes
- Las API keys solo aparecen como `SecretStr` y se obtienen con `.get_secret_value()` justo en el punto de uso.
- El audit log nunca recibe el contenido bruto de un token o secret (filtrar antes de loggear).
- `.env` está en `.gitignore`. `.env.example` siempre presente y al día.

---

## 7. Despliegue local

```
docker compose up -d         # ChromaDB :8000  +  n8n :5678
ollama serve                 # modelos locales :11434
make ollama-setup            # primera vez: descarga modelos
make dev                     # FastAPI :8080  +  WS :8081
```

Volúmenes persistentes en `./data/` (gitignored): `chromadb/`, `n8n/`, `vault/`, `audit.log`.

---

## 8. Decisiones de arquitectura registradas

| ID    | Decisión                                                    | Fecha       |
|-------|-------------------------------------------------------------|-------------|
| ADR-1 | Router como guardián de privacidad (no el agente)           | 2026-05-05  |
| ADR-2 | Side effects solo en `actions/`, expuestos vía MCP servers  | 2026-05-05  |
| ADR-3 | Embeddings siempre locales (Ollama)                         | 2026-05-05  |
| ADR-4 | `core/` no importa `actions/` directamente                  | 2026-05-05  |
| ADR-5 | Confirmación humana fail-closed (timeout = denegado)        | 2026-05-05  |
| ADR-6 | Audit log JSONL append-only, sin rotación automática        | 2026-05-05  |

Las decisiones futuras se añaden a esta tabla con un nuevo ID y se documentan en `docs/adr/<id>.md` si requieren explicación larga.
