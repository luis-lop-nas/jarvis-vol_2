"""Fixtures compartidas y configuración de pytest."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Hacer que las importaciones del proyecto resuelvan a la raíz aunque
# se invoque pytest desde otra carpeta.
RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

# Aislar configuraciones para que los tests no toquen .env real ni rutas reales.
os.environ.setdefault("KIMI_API_KEY", "test-kimi-key")
os.environ.setdefault("DEEPSEEK_API_KEY", "test-deepseek-key")
os.environ.setdefault("OPENROUTER_API_KEY", "test-openrouter-key")
os.environ.setdefault("ROUTER_LOG_DECISIONS", "false")


@pytest.fixture
def tmp_cache_path(tmp_path: Path) -> Path:
    """Ruta temporal para una caché SQLite de embeddings."""
    return tmp_path / "embed_cache.sqlite"
