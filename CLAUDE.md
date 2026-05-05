# JARVIS — Claude Code configuration

## Model strategy
- Use **claude-opus-4** for: architecture decisions, complex problem solving, planning new modules, reviewing security-critical code
- Use **claude-sonnet-4** for: implementing functions, writing tests, refactoring, documentation, repetitive tasks

## Project context
JARVIS is an autonomous macOS AI agent built in Python 3.12.
- **Mac M3 8GB RAM** — be memory-conscious, avoid loading multiple large models simultaneously
- **Primary AI**: Kimi K2.6 API (free) + DeepSeek V3.2 (fallback) + Ollama local (private data)
- **No Claude API in production** — only used during development via Claude Code
- **Language**: all comments, docstrings and logs in Spanish
- All actions touching filesystem, comms or system require explicit confirmation flow

## Code standards
- Python 3.12+ with strict type hints everywhere
- Async/await by default — no blocking calls on the main thread
- Pydantic models for all data structures
- Result types over exceptions where possible
- Every function needs docstring + example in docstring
- Security first: validate all inputs, sanitize paths, never `eval()`, never `shell=True` without sandbox

## Architecture rules
- Models are swappable via `BaseModel` interface — never call Kimi/DeepSeek directly from agent
- Router decides model — agent never decides
- All side effects go through `actions/` — never directly in `core/`
- Memory operations are async — never block on ChromaDB queries
- MCP servers are the only public interface — internal modules stay internal

## Testing
- Write tests alongside implementation, not after
- Use `pytest` + `pytest-asyncio`
- Mock all external API calls
- Test the router logic exhaustively — it's security-critical

## File structure reminders
- `config/settings.py` is the single source of truth for all config
- `.env` is never committed — `.env.example` always stays updated
- `data/` directory is gitignored — contains ChromaDB and n8n volumes

## Sub-agents available
Invoke with `@<name>` in a Claude Code prompt:
- `@architect` — architecture decisions (Opus)
- `@security-reviewer` — security audits (Opus)
- `@test-writer` — pytest test generation (Sonnet)
- `@debugger` — stack-trace analysis and root-cause fixes (Sonnet)
