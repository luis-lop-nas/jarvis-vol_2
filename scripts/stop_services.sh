#!/usr/bin/env bash
# Para todos los servicios arrancados por start_services.sh usando los PIDs guardados.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIDS_DIR="$ROOT/data/pids"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
_info() { echo -e "${GREEN}[stop]${NC} $*"; }
_warn() { echo -e "${YELLOW}[warn]${NC}  $*"; }

_stop() {
    local name="$1"
    local pid_file="$PIDS_DIR/$name.pid"

    if [[ ! -f "$pid_file" ]]; then
        _warn "$name — no hay PID guardado"
        return 0
    fi

    local pid
    pid="$(cat "$pid_file")"

    if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" && _info "$name parado (PID $pid)"
    else
        _warn "$name — PID $pid ya no estaba corriendo"
    fi

    rm -f "$pid_file"
}

_stop chromadb
_stop ollama
_stop n8n

echo ""
_info "Servicios parados."
