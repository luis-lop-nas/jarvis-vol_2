#!/usr/bin/env bash
# Lanza el TUI de JARVIS como panel lateral derecho (38% del ancho de pantalla).
# Soporta iTerm2 (preferido) y Terminal.app como fallback.
#
# Uso:
#   bash interface/tui/launch.sh
#   JARVIS_WIDTH=500 bash interface/tui/launch.sh  # ancho personalizado

set -euo pipefail

JARVIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${PYTHON:-python3}"
WS_URL="${JARVIS_URL:-ws://127.0.0.1:8765/ws}"

# --- Dimensiones de pantalla -------------------------------------------------

read -r screen_w screen_h < <(python3 -c "
import subprocess, re, sys
r = subprocess.run(['system_profiler','SPDisplaysDataType'], capture_output=True, text=True)
m = re.search(r'Resolution: (\d+) x (\d+)', r.stdout)
if m:
    # Dividir por factor de escala (Retina)
    w, h = int(m.group(1)), int(m.group(2))
    print(w // 2, h // 2)
else:
    print(1440, 900)
")

# Panel derecho: 38% del ancho, pantalla completa de alto
panel_w="${JARVIS_WIDTH:-$(( screen_w * 38 / 100 ))}"
panel_x=$(( screen_w - panel_w ))
panel_y=0
panel_h="${screen_h}"

# Ajuste por barra de menú macOS (~25px en coordenadas lógicas)
panel_y=25
panel_h=$(( screen_h - 25 ))

CMD_ITERM="export JARVIS_TERMINAL_APP=iTerm2; cd \"${JARVIS_DIR}\" && ${PYTHON} -m interface.tui --url ${WS_URL}"
CMD_TERM="export JARVIS_TERMINAL_APP=Terminal; cd \"${JARVIS_DIR}\" && ${PYTHON} -m interface.tui --url ${WS_URL}"

# --- Lanzar en iTerm2 --------------------------------------------------------

if osascript -e 'tell application "iTerm2" to return name' &>/dev/null; then
    osascript << SCRIPT
tell application "iTerm2"
    activate
    set newWindow to (create window with default profile)
    tell newWindow
        set bounds to {${panel_x}, ${panel_y}, ${screen_w}, $(( panel_y + panel_h ))}
    end tell
    tell current session of newWindow
        write text "${CMD_ITERM}"
    end tell
end tell
SCRIPT
    echo "JARVIS TUI lanzado en iTerm2 — panel derecho ${panel_w}×${panel_h}px"
    exit 0
fi

# --- Fallback: Terminal.app --------------------------------------------------

osascript << SCRIPT
tell application "Terminal"
    activate
    do script "${CMD_TERM}"
    delay 0.3
    set bounds of front window to {${panel_x}, ${panel_y}, ${screen_w}, $(( panel_y + panel_h ))}
end tell
SCRIPT
echo "JARVIS TUI lanzado en Terminal.app — panel derecho ${panel_w}×${panel_h}px"
