#!/bin/bash
# Script de instalación completa de JARVIS en macOS
# Ejecutar una sola vez en el Mac de desarrollo
# bash scripts/setup_mac.sh

set -e  # salir si cualquier comando falla

echo "🤖 JARVIS — Setup completo para macOS"
echo "======================================"

# Verificar macOS y chip
if [[ $(uname) != "Darwin" ]]; then
  echo "❌ Este script solo funciona en macOS"
  exit 1
fi

CHIP=$(uname -m)
echo "✓ macOS detectado · Chip: $CHIP"

# Verificar Homebrew
if ! command -v brew &> /dev/null; then
  echo "📦 Instalando Homebrew..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi
echo "✓ Homebrew disponible"

# Dependencias del sistema
echo "📦 Instalando dependencias del sistema..."
brew install python@3.12 tesseract ffmpeg git

# Docker Desktop
if ! command -v docker &> /dev/null; then
  echo "📦 Instala Docker Desktop manualmente:"
  echo "   https://www.docker.com/products/docker-desktop/"
  echo "   Luego vuelve a ejecutar este script"
  exit 1
fi
echo "✓ Docker disponible"

# Ollama
if ! command -v ollama &> /dev/null; then
  echo "📦 Instalando Ollama..."
  brew install ollama
fi
echo "✓ Ollama disponible"

# Python venv
echo "🐍 Configurando entorno Python..."
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# Playwright
echo "🎭 Instalando Playwright..."
playwright install chromium

# 1Password CLI
if ! command -v op &> /dev/null; then
  echo "📦 Instalando 1Password CLI..."
  brew install 1password-cli
fi
echo "✓ 1Password CLI disponible"

# Modelos Ollama
echo "🧠 Descargando modelos Ollama (esto tarda varios minutos)..."
ollama serve &
OLLAMA_PID=$!
sleep 3

ollama pull nomic-embed-text
ollama pull gemma4:4b
echo "⚠ qwen3:8b requiere ~5GB — descargando..."
ollama pull qwen3:8b

kill $OLLAMA_PID
echo "✓ Modelos Ollama descargados"

# Docker services
echo "🐳 Arrancando ChromaDB y n8n..."
docker-compose up -d
sleep 5

# Verificar ChromaDB
if curl -s http://localhost:8000/api/v1/heartbeat > /dev/null; then
  echo "✓ ChromaDB corriendo en :8000"
else
  echo "❌ ChromaDB no responde — verifica Docker"
  exit 1
fi

# Crear .env desde ejemplo si no existe
if [ ! -f .env ]; then
  cp .env.example .env
  echo "📝 Creado .env desde .env.example"
  echo "⚠ IMPORTANTE: edita .env con tus API keys antes de continuar"
fi

# Permisos macOS
echo ""
echo "🔐 Permisos macOS necesarios:"
echo "   Ve a Configuración del Sistema → Privacidad y Seguridad"
echo ""
echo "   1. Accesibilidad → añade Terminal y VS Code"
echo "   2. Grabación de pantalla → añade Terminal y VS Code"
echo "   3. Automatización → permite control de otras apps"
echo ""
echo "   Abre System Settings ahora? (s/n)"
read -r response
if [[ "$response" == "s" ]]; then
  open "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
fi

echo ""
echo "✅ Setup completado"
echo ""
echo "Próximos pasos:"
echo "  1. Edita .env con tus API keys (kimi_api_key, deepseek_api_key)"
echo "  2. Ejecuta: source .venv/bin/activate"
echo "  3. Ejecuta: make test"
echo "  4. Ejecuta: python main.py"
echo ""
echo "🤖 JARVIS listo para arrancar"
