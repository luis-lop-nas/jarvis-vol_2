# =====================================================================
# JARVIS — Makefile
# Uso: `make <objetivo>`. Ejecuta `make help` para ver la lista completa.
# =====================================================================

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

PYTHON := python3
VENV := .venv
PIP := $(VENV)/bin/pip
PY := $(VENV)/bin/python
PYTEST := $(VENV)/bin/pytest
RUFF := $(VENV)/bin/ruff
MYPY := $(VENV)/bin/mypy

OLLAMA_MODELS := gemma3:4b qwen3:8b qwen3-coder:8b nomic-embed-text

# ---------------------------------------------------------------------
# Ayuda
# ---------------------------------------------------------------------

.PHONY: help
help: ## Muestra esta ayuda.
	@awk 'BEGIN {FS = ":.*?## "; printf "Objetivos disponibles:\n"} \
		/^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# ---------------------------------------------------------------------
# Entorno
# ---------------------------------------------------------------------

.PHONY: install
install: $(VENV)/bin/activate ## Crea venv e instala requirements + Playwright.
	$(PIP) install --upgrade pip wheel
	$(PIP) install -r requirements.txt
	$(VENV)/bin/playwright install chromium
	@echo "✅ Entorno listo. Activa con: source $(VENV)/bin/activate"

$(VENV)/bin/activate:
	$(PYTHON) -m venv $(VENV)

.PHONY: env
env: ## Copia .env.example a .env si no existe.
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "✅ .env creado. Edítalo con tus claves."; \
	else \
		echo "⚠️  .env ya existe — no se sobrescribe."; \
	fi

# ---------------------------------------------------------------------
# Servicios y desarrollo
# ---------------------------------------------------------------------

.PHONY: services-up
services-up: ## Arranca ChromaDB y n8n vía docker compose.
	docker compose up -d
	@echo "✅ Servicios arrancados (ChromaDB:8000, n8n:5678)"

.PHONY: services-down
services-down: ## Detiene los servicios docker.
	docker compose down

.PHONY: services-logs
services-logs: ## Muestra logs en vivo de los servicios.
	docker compose logs -f

.PHONY: dev
dev: services-up ## Arranca servicios + agente principal.
	$(PY) main.py

# ---------------------------------------------------------------------
# Tests y calidad
# ---------------------------------------------------------------------

.PHONY: test
test: ## Ejecuta pytest con cobertura.
	$(PYTEST) -v --tb=short \
		--cov=core --cov=models --cov=memory --cov=actions --cov=security \
		--cov-report=term-missing --cov-report=html

.PHONY: test-fast
test-fast: ## Ejecuta tests sin cobertura (más rápido).
	$(PYTEST) -v --tb=short -x

.PHONY: lint
lint: ## Ruff + mypy (chequeo estricto).
	$(RUFF) check .
	$(RUFF) format --check .
	$(MYPY) --strict core models memory actions security perception interface

.PHONY: format
format: ## Formatea el código con ruff.
	$(RUFF) check --fix .
	$(RUFF) format .

# ---------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------

.PHONY: ollama-setup
ollama-setup: ## Descarga los modelos locales necesarios.
	@command -v ollama >/dev/null 2>&1 || { \
		echo "❌ Ollama no está instalado. Descárgalo desde https://ollama.com"; exit 1; }
	@for modelo in $(OLLAMA_MODELS); do \
		echo "⬇️  Descargando $$modelo ..."; \
		ollama pull $$modelo; \
	done
	@echo "✅ Modelos listos. Lista actual:"
	@ollama list

.PHONY: ollama-status
ollama-status: ## Lista los modelos instalados localmente.
	ollama list

# ---------------------------------------------------------------------
# Limpieza
# ---------------------------------------------------------------------

.PHONY: clean
clean: ## Elimina caches, .pyc, builds y logs temporales.
	find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	find . -type d -name ".pytest_cache" -prune -exec rm -rf {} +
	find . -type d -name ".mypy_cache" -prune -exec rm -rf {} +
	find . -type d -name ".ruff_cache" -prune -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	rm -rf htmlcov .coverage
	rm -rf build dist *.egg-info
	@echo "🧹 Limpieza completa."

.PHONY: clean-data
clean-data: ## ⚠️ Elimina volúmenes de ChromaDB y n8n. Pide confirmación.
	@read -p "Esto borra ./data/. ¿Seguro? [y/N] " ans; \
	if [ "$$ans" = "y" ] || [ "$$ans" = "Y" ]; then \
		rm -rf data/; \
		echo "🗑️  data/ eliminado."; \
	else \
		echo "Cancelado."; \
	fi

.PHONY: clean-all
clean-all: clean ## Limpia caches + venv.
	rm -rf $(VENV)
	@echo "🧹 venv eliminado."
