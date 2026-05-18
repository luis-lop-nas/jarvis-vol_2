#!/usr/bin/env bash
# Arranca ChromaDB, Ollama y n8n (si está disponible) sin Docker.
# PIDs en data/pids/, logs en data/logs/.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIDS_DIR="$ROOT/data/pids"
LOGS_DIR="$ROOT/data/logs"
CHROMA_DATA="$ROOT/data/chromadb"
VENV="$ROOT/.venv"
CHROMA="$VENV/bin/chroma"

mkdir -p "$PIDS_DIR" "$LOGS_DIR" "$CHROMA_DATA"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
_info()  { echo -e "${GREEN}[start]${NC} $*"; }
_warn()  { echo -e "${YELLOW}[warn]${NC}  $*"; }
_error() { echo -e "${RED}[error]${NC} $*"; }

_is_running() {
    local pid_file="$PIDS_DIR/$1.pid"
    [[ -f "$pid_file" ]] && kill -0 "$(cat "$pid_file")" 2>/dev/null
}

_start() {
    local name="$1"; shift
    local pid_file="$PIDS_DIR/$name.pid"
    local log_file="$LOGS_DIR/$name.log"

    if _is_running "$name"; then
        _info "$name ya está corriendo (PID $(cat "$pid_file"))"
        return 0
    fi

    "$@" >> "$log_file" 2>&1 &
    echo $! > "$pid_file"
    _info "$name arrancado (PID $!, log: $log_file)"
}

# ── ChromaDB ──────────────────────────────────────────────────────────────────
if [[ -x "$CHROMA" ]]; then
    _start chromadb "$CHROMA" run \
        --path "$CHROMA_DATA" \
        --host 0.0.0.0 \
        --port 8000
    sleep 1  # dar tiempo al servidor para que abra el socket
else
    _error "chroma CLI no encontrado en $CHROMA — ejecuta: make install"
fi

# ── Ollama ────────────────────────────────────────────────────────────────────
if command -v ollama >/dev/null 2>&1; then
    if curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
        _info "Ollama ya está corriendo"
    else
        _start ollama ollama serve
        sleep 1
    fi
else
    _warn "Ollama no instalado — omitido"
fi

# ── n8n ───────────────────────────────────────────────────────────────────────
if command -v n8n >/dev/null 2>&1; then
    _start n8n n8n start
else
    _warn "n8n no instalado — omitido (opcional, instala con: npm install -g n8n)"
fi

echo ""
_info "Servicios arrancados. Para parar: make services-stop"
