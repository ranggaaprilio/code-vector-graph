"""Dashboard configuration — resolve paths and load env."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Project root is the parent of this dashboard/ package
PROJECT_ROOT = Path(__file__).resolve().parent.parent
MCP_SERVER_SCRIPT = PROJECT_ROOT / "mcp_server.py"

# Python interpreter: use the running interpreter (venv python when launched correctly),
# falling back to <root>/.venv/bin/python, and allowing an env override.
_default_venv_python = str(PROJECT_ROOT / ".venv" / "bin" / "python")
MCP_PYTHON = os.getenv("CVG_MCP_PYTHON") or (
    sys.executable if Path(sys.executable).exists() else _default_venv_python
)

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# Reuse src config constants (no embedder import)
from src.config import (  # noqa: E402
    DEFAULT_COLLECTION_NAME,
    DEFAULT_MODEL_ID,
    DEFAULT_QDRANT_URL,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USER,
    get_model_config,
)
from src.store import get_collection_name  # noqa: E402

_MODEL_ID = "jina"
_BASE_COLLECTION = "code_chunks_mac_mps_24gb"

_model_cfg = get_model_config(_MODEL_ID)
QDRANT_URL = os.getenv("QDRANT_URL", DEFAULT_QDRANT_URL)
QDRANT_COLLECTION = get_collection_name(
    _BASE_COLLECTION, "huggingface", model=_model_cfg["model_name"]
)
QDRANT_DIMENSIONS = _model_cfg["dimensions"]
