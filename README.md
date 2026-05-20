# JARVIS — Agente IA Autónomo para macOS

Agente de IA personal que controla tu Mac de forma autónoma. Percepción visual, control
del sistema, memoria persistente e integración con tus apps — inspirado en el JARVIS de
Iron Man.

## Requisitos

- macOS 14.0+ · chip M1/M2/M3/M4
- Python 3.12+
- Docker Desktop
- Ollama
- 1Password CLI (opcional)

## Instalación

```bash
git clone https://github.com/luichi/jarvis
cd jarvis
bash scripts/setup_mac.sh
```

El script instala todas las dependencias del sistema, descarga los modelos Ollama y
arranca los servicios Docker. Al terminar te pide configurar los permisos de macOS.

## Primer arranque

```bash
source .venv/bin/activate
python scripts/first_run.py
```

El asistente interactivo:
1. Verifica que todos los componentes están listos
2. Configura las API keys si faltan
3. Prueba Kimi K2.6, DeepSeek y Ollama con llamadas reales
4. Comprueba los permisos de macOS (Accessibility + Screen Recording)
5. Verifica la memoria ChromaDB
6. Pregunta tu nombre y carpeta de proyectos
7. Lanza JARVIS

## Uso diario

```bash
source .venv/bin/activate
make dev          # arranca servicios Docker + agente
```

La API REST queda disponible en `http://localhost:8765` y el WebSocket en
`ws://localhost:8765/ws`.

## Tests

```bash
make test         # suite unitaria con cobertura
make test-e2e     # tests end-to-end (requiere ChromaDB + Ollama)
make test-perf    # benchmarks de rendimiento para M3 8 GB
make test-all     # todo junto
make coverage     # informe HTML de cobertura
```

## Lint y formato

```bash
make lint         # ruff + mypy estricto
make format       # autoformato con ruff
```

## Arquitectura

```
Usuario (voz / texto)
    │
    ▼
STT (Groq) [planned]
    │
    ▼
Daemon Python · LangGraph
    ├── ModelRouter  ──► Kimi K2.6 / DeepSeek V3.2 / Ollama local
    ├── Planner / Reflector
    ├── MemorySystem ──► ChromaDB (episódica) + MemoriaCortoPlazo
    ├── Actions      ──► filesystem · shell · browser · calendario · Spotify
    ├── Perception   ──► visión · OCR · audio
    └── Security     ──► Sandbox · ConfirmationManager · AuditLog
    │
    ▼
FastAPI + WebSocket (:8765)  ◄──► SwiftUI overlay (Metal)
    │
    ▼
TTS (Kokoro local) [planned]
```

## Modelos de IA

| Rol | Modelo | Uso |
|-----|--------|-----|
| Cerebro principal | Kimi K2.6 (gratis) | Razonamiento, planificación |
| Fallback | DeepSeek V3.2 | Tareas largas, coste reducido |
| Fallback gratuito | OpenRouter free tier | Modelos variados sin coste |
| Local / privado | Ollama gemma4:4b | Datos sensibles, sin internet |
| Embeddings | nomic-embed-text | Memoria semántica en ChromaDB |

El `ModelRouter` decide qué modelo usar según la tarea, la privacidad de los datos y la
disponibilidad de internet — el agente nunca llama a los modelos directamente.

## Variables de entorno

Copia `.env.example` a `.env` y rellena:

| Variable | Descripción |
|----------|-------------|
| `KIMI_API_KEY` | API key de Moonshot (platform.moonshot.cn) |
| `DEEPSEEK_API_KEY` | API key de DeepSeek (opcional) |
| `USUARIO_NOMBRE` | Nombre con el que JARVIS te llamará |

El resto de variables tienen valores por defecto razonables para desarrollo local.

## Overlay SwiftUI — instalación en macOS

El overlay nativo JARVIS se muestra en la barra de notificaciones y reacciona
al estado del agente en tiempo real. Requiere macOS 14+ y Xcode 15+.

### Desarrollo local (sin firma)

```bash
make overlay          # compila y copia JARVIS.app a ~/Applications/
open ~/Applications/JARVIS.app
```

Si Xcode no encuentra el proyecto, ábrelo primero:
```bash
open -a Xcode interface/swiftui/JARVIS.xcodeproj
```

### Distribución (firma + notarización Apple)

1. Consigue un certificado **Developer ID Application** en
   [developer.apple.com/account](https://developer.apple.com/account).

2. Configura las credenciales de notarización (solo una vez):
   ```bash
   xcrun notarytool store-credentials jarvis-notary \
       --apple-id tu@email.com \
       --team-id XXXXXXXXXX \
       --password "xxxx-xxxx-xxxx-xxxx"   # App-Specific Password
   ```

3. Añade tu Developer ID a `.env`:
   ```
   APPLE_DEVELOPER_ID=Developer ID Application: Tu Nombre (XXXXXXXXXX)
   APPLE_NOTARY_PROFILE=jarvis-notary
   ```

4. Compila, firma y notariza:
   ```bash
   make overlay
   ```
   El script ejecuta automáticamente `codesign`, `notarytool submit --wait` y
   `stapler staple`. Al terminar, `JARVIS.app` está lista para distribuir.

> La notarización no está configurada en CI — solo se ejecuta manualmente cuando
> se quiere preparar una versión para distribuir.

## Dashboard web

Con el servidor en marcha, abre `http://localhost:8765` para ver:

- Sesiones persistidas en disco (última tarea, estado, cuándo se guardó)
- Últimas 50 entradas del audit log
- Estado de ChromaDB, Ollama, RAM y MCP servers
- Botón "Cancelar" por sesión

El dashboard se actualiza automáticamente cada 5 segundos.

## Targets de make

| Target | Descripción |
|--------|-------------|
| `make setup` | Instalación completa desde cero |
| `make verify` | Verifica que todos los servicios están OK |
| `make first-run` | Primer arranque interactivo guiado |
| `make dev` | Arranca servicios + agente |
| `make overlay` | Compila y firma el overlay SwiftUI |
| `make overlay-debug` | Compila overlay en modo debug (sin firma) |
| `make test` | Tests unitarios con cobertura |
| `make test-e2e` | Tests end-to-end |
| `make test-perf` | Benchmarks de rendimiento |
| `make lint` | Ruff + mypy |
| `make logs` | Audit log en tiempo real |
| `make clean` | Limpia caches y builds |
| `make reset` | Limpieza total + reinstalación |
| `make install-dev` | Instala entorno de desarrollo (anthropic + openai SDKs) |

## Estado actual

Ver [PROGRESS.md](./PROGRESS.md) para el estado detallado de cada módulo y las
decisiones de arquitectura (ADRs) registradas.

Suite de tests: 464/464 verde (+ 1 skip fastmcp no instalado).
