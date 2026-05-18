#!/usr/bin/env bash
# build.sh — Compila el overlay JARVIS y lo copia a ~/Applications/
# Requiere: Xcode 15+, macOS 14+
# Uso: ./build.sh [release|debug]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCHEME="JARVIS"
CONFIGURATION="${1:-release}"
CONFIGURATION_CAP="$(tr '[:lower:]' '[:upper:]' <<< "${CONFIGURATION:0:1}")${CONFIGURATION:1}"
DEST_DIR="$HOME/Applications"

echo "→ Compilando JARVIS overlay (${CONFIGURATION_CAP})…"

# Generar xcodeproj si no existe
if [ ! -d "$SCRIPT_DIR/JARVIS.xcodeproj" ]; then
    echo "→ Generando JARVIS.xcodeproj…"
    cd "$SCRIPT_DIR"
    xcodebuild -project JARVIS.xcodeproj -list > /dev/null 2>&1 || {
        echo "   No se encontró JARVIS.xcodeproj. Ábrelo en Xcode primero:"
        echo "   open -a Xcode '$SCRIPT_DIR/Package.swift'"
        echo "   Luego genera el xcodeproj desde Xcode → File → Generate Xcode Project"
        exit 1
    }
fi

# Compilar
xcodebuild \
    -project "$SCRIPT_DIR/JARVIS.xcodeproj" \
    -scheme "$SCHEME" \
    -configuration "$CONFIGURATION_CAP" \
    -derivedDataPath "$SCRIPT_DIR/.build" \
    clean build \
    DEVELOPMENT_TEAM="" \
    CODE_SIGN_IDENTITY="-" \
    CODE_SIGNING_REQUIRED=NO \
    CODE_SIGNING_ALLOWED=NO \
    | xcpretty 2>/dev/null || cat

# Localizar el .app compilado
APP_PATH=$(find "$SCRIPT_DIR/.build" -name "JARVIS.app" -type d | head -1)

if [ -z "$APP_PATH" ]; then
    echo "✗ No se encontró JARVIS.app tras la compilación."
    exit 1
fi

# Copiar a ~/Applications/
mkdir -p "$DEST_DIR"
rm -rf "$DEST_DIR/JARVIS.app"
cp -R "$APP_PATH" "$DEST_DIR/JARVIS.app"

echo "✓ JARVIS.app instalado en $DEST_DIR/JARVIS.app"
echo "  Para arrancarlo: open '$DEST_DIR/JARVIS.app'"
