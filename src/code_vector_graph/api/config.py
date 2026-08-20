"""Dashboard configuration — how to launch the MCP server, plus chat settings."""

import os
import shutil
import sys

from dotenv import load_dotenv

load_dotenv()

# How to spawn the MCP server the dashboard talks to. Prefer the installed
# `cvg-mcp` console script; fall back to `python -m` on the *running* interpreter
# so a dev checkout works without an entry-point rebuild. CVG_MCP_PYTHON still
# overrides the interpreter, as documented in .env.example.
_MCP_MODULE = "code_vector_graph.mcp_server.server"
_console_script = shutil.which("cvg-mcp")
_python_override = os.getenv("CVG_MCP_PYTHON")

if _python_override:
    MCP_COMMAND = _python_override
    MCP_ARGS = ["-m", _MCP_MODULE]
elif _console_script:
    MCP_COMMAND = _console_script
    MCP_ARGS = []
else:
    MCP_COMMAND = sys.executable
    MCP_ARGS = ["-m", _MCP_MODULE]

# Anthropic
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# Reuse src config constants (no embedder import)
from code_vector_graph.config import (  # noqa: E402
    DEFAULT_COLLECTION_NAME,
    DEFAULT_MODEL_ID,
    DEFAULT_QDRANT_URL,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USER,
    get_model_config,
)
from code_vector_graph.stores.vector_store import get_collection_name  # noqa: E402

_MODEL_ID = "jina"
_BASE_COLLECTION = "code_chunks_mac_mps_24gb"

_model_cfg = get_model_config(_MODEL_ID)
QDRANT_URL = os.getenv("QDRANT_URL", DEFAULT_QDRANT_URL)
QDRANT_COLLECTION = get_collection_name(
    _BASE_COLLECTION, "huggingface", model=_model_cfg["model_name"]
)
QDRANT_DIMENSIONS = _model_cfg["dimensions"]
