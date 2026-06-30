#!/usr/bin/env bash
# build.sh — Compila el overlay JARVIS y lo copia a ~/Applications/
# Requiere: Xcode 15+, macOS 14+
#
# Uso: ./build.sh [release|debug]
#
# Firma y notarización (distribución):
#   Configura APPLE_DEVELOPER_ID en .env o como variable de entorno.
#   Si está vacía: build sin firma (solo desarrollo local).
#   Si está presente: codesign + xcrun notarytool automáticos.
#
# Variables de entorno:
#   APPLE_DEVELOPER_ID  — e.g. "Developer ID Application: Tu Nombre (TEAMID)"
#   APPLE_NOTARY_PROFILE — nombre del perfil de notarytool (default: "jarvis-notary")
#   APPLE_BUNDLE_ID      — bundle ID de la app (default: "com.jarvis.overlay")

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCHEME="JARVIS"
CONFIGURATION="${1:-release}"
CONFIGURATION_CAP="$(tr '[:lower:]' '[:upper:]' <<< "${CONFIGURATION:0:1}")${CONFIGURATION:1}"
DEST_DIR="$HOME/Applications"

# Cargar .env si existe (para APPLE_DEVELOPER_ID)
ROOT_ENV="$(cd "$SCRIPT_DIR/../.." && pwd)/.env"
if [ -f "$ROOT_ENV" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$ROOT_ENV"
    set +a
fi

APPLE_DEVELOPER_ID="${APPLE_DEVELOPER_ID:-}"
APPLE_NOTARY_PROFILE="${APPLE_NOTARY_PROFILE:-jarvis-notary}"
APPLE_BUNDLE_ID="${APPLE_BUNDLE_ID:-com.jarvis.overlay}"

if [ -n "$APPLE_DEVELOPER_ID" ]; then
    echo "→ Modo distribución: firma con '$APPLE_DEVELOPER_ID'"
    CODE_SIGN_IDENTITY="$APPLE_DEVELOPER_ID"
    CODE_SIGNING_REQUIRED="YES"
    CODE_SIGNING_ALLOWED="YES"
else
    echo "→ Modo desarrollo local: sin firma (APPLE_DEVELOPER_ID no configurado)"
    CODE_SIGN_IDENTITY="-"
    CODE_SIGNING_REQUIRED="NO"
    CODE_SIGNING_ALLOWED="NO"
fi

echo "→ Compilando JARVIS overlay (${CONFIGURATION_CAP})…"

# Generar xcodeproj si no existe
if [ ! -d "$SCRIPT_DIR/JARVIS.xcodeproj" ]; then
    echo "→ No se encontró JARVIS.xcodeproj."
    echo "   Ábrelo en Xcode primero:"
    echo "   open -a Xcode '$SCRIPT_DIR/Package.swift'"
    echo "   Luego: Xcode → File → Generate Xcode Project"
    exit 1
fi

# Compilar. Nota: con `| xcpretty` el exit code de xcodebuild se perdía y el
# script reportaba éxito aunque el build fallara. Usamos PIPESTATUS para abortar
# si la compilación falla de verdad.
if command -v xcpretty >/dev/null 2>&1; then
    xcodebuild \
        -project "$SCRIPT_DIR/JARVIS.xcodeproj" \
        -scheme "$SCHEME" \
        -configuration "$CONFIGURATION_CAP" \
        -derivedDataPath "$SCRIPT_DIR/.build" \
        clean build \
        DEVELOPMENT_TEAM="" \
        CODE_SIGN_IDENTITY="$CODE_SIGN_IDENTITY" \
        CODE_SIGNING_REQUIRED="$CODE_SIGNING_REQUIRED" \
        CODE_SIGNING_ALLOWED="$CODE_SIGNING_ALLOWED" \
        | xcpretty
    BUILD_STATUS=${PIPESTATUS[0]}
else
    xcodebuild \
        -project "$SCRIPT_DIR/JARVIS.xcodeproj" \
        -scheme "$SCHEME" \
        -configuration "$CONFIGURATION_CAP" \
        -derivedDataPath "$SCRIPT_DIR/.build" \
        clean build \
        DEVELOPMENT_TEAM="" \
        CODE_SIGN_IDENTITY="$CODE_SIGN_IDENTITY" \
        CODE_SIGNING_REQUIRED="$CODE_SIGNING_REQUIRED" \
        CODE_SIGNING_ALLOWED="$CODE_SIGNING_ALLOWED"
    BUILD_STATUS=$?
fi

if [ "$BUILD_STATUS" -ne 0 ]; then
    echo "✗ La compilación falló (xcodebuild exit ${BUILD_STATUS})."
    exit "$BUILD_STATUS"
fi

# Localizar el .app compilado
APP_PATH=$(find "$SCRIPT_DIR/.build" -name "JARVIS.app" -type d | head -1)

if [ -z "$APP_PATH" ]; then
    echo "✗ No se encontró JARVIS.app tras la compilación."
    exit 1
fi

echo "✓ Build completado: $APP_PATH"

# Firma y notarización (solo si APPLE_DEVELOPER_ID está configurado)
if [ -n "$APPLE_DEVELOPER_ID" ]; then
    echo "→ Firmando con codesign…"
    codesign \
        --force \
        --deep \
        --sign "$APPLE_DEVELOPER_ID" \
        --options runtime \
        --entitlements "$SCRIPT_DIR/Resources/JARVIS.entitlements" \
        "$APP_PATH" 2>/dev/null || \
    codesign \
        --force \
        --deep \
        --sign "$APPLE_DEVELOPER_ID" \
        --options runtime \
        "$APP_PATH"
    echo "✓ Firma completada"

    echo "→ Creando ZIP para notarización…"
    ZIP_PATH="$SCRIPT_DIR/.build/JARVIS.zip"
    ditto -c -k --keepParent "$APP_PATH" "$ZIP_PATH"

    echo "→ Enviando a Apple Notary Service (puede tardar varios minutos)…"
    echo "   Perfil de credenciales: $APPLE_NOTARY_PROFILE"
    echo "   Si no tienes el perfil configurado, ejecuta:"
    echo "   xcrun notarytool store-credentials $APPLE_NOTARY_PROFILE \\"
    echo "       --apple-id TU_APPLE_ID \\"
    echo "       --team-id TU_TEAM_ID \\"
    echo "       --password TU_APP_PASSWORD"
    echo ""

    xcrun notarytool submit "$ZIP_PATH" \
        --keychain-profile "$APPLE_NOTARY_PROFILE" \
        --wait

    echo "→ Aplicando staple…"
    xcrun stapler staple "$APP_PATH"
    echo "✓ Notarización y staple completados"

    rm -f "$ZIP_PATH"
fi

# Copiar a ~/Applications/
mkdir -p "$DEST_DIR"
rm -rf "$DEST_DIR/JARVIS.app"
cp -R "$APP_PATH" "$DEST_DIR/JARVIS.app"

echo "✓ JARVIS.app instalado en $DEST_DIR/JARVIS.app"
echo "  Para arrancarlo: open '$DEST_DIR/JARVIS.app'"
