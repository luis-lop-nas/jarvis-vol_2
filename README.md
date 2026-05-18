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

La API REST queda disponible en `http://localhost:8080` y el WebSocket en
`ws://localhost:8081/ws`.

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
STT (Groq)
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
FastAPI + WebSocket  ◄──► SwiftUI overlay (Metal)
    │
    ▼
TTS (Kokoro local)
```

## Modelos de IA

| Rol | Modelo | Uso |
|-----|--------|-----|
| Cerebro principal | Kimi K2.6 (gratis) | Razonamiento, planificación |
| Fallback | DeepSeek V3.2 | Tareas largas, coste reducido |
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

## Targets de make

| Target | Descripción |
|--------|-------------|
| `make setup` | Instalación completa desde cero |
| `make verify` | Verifica que todos los servicios están OK |
| `make first-run` | Primer arranque interactivo guiado |
| `make dev` | Arranca servicios + agente |
| `make test` | Tests unitarios con cobertura |
| `make test-e2e` | Tests end-to-end |
| `make test-perf` | Benchmarks de rendimiento |
| `make lint` | Ruff + mypy |
| `make logs` | Audit log en tiempo real |
| `make clean` | Limpia caches y builds |
| `make reset` | Limpieza total + reinstalación |
