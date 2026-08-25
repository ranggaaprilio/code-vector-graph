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

# Reuse src config constants (no embedder import). Imported after load_dotenv() so
# .env values are visible when code_vector_graph.config resolves its env-backed settings.
from code_vector_graph.config import (  # noqa: E402
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    CVG_CHAT_MODEL,
    CVG_CHAT_PROVIDER,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USER,
    QDRANT_URL,
    active_base_collection,
    active_collection,
)

# Model + collection the dashboard reads. Resolved from CVG_MODEL_ID /
# CVG_COLLECTION_NAME — the same knobs the MCP server uses — so both sides agree.
QDRANT_COLLECTION, QDRANT_DIMENSIONS, MODEL_ID = active_collection()

# Environment handed to the spawned MCP server so it reads the same stores/collection
# as the dashboard, regardless of how the parent process was configured.
MCP_ENV_OVERRIDES = {
    "CVG_MODEL_ID": MODEL_ID,
    "CVG_COLLECTION_NAME": active_base_collection(),
    "QDRANT_URL": QDRANT_URL,
    "NEO4J_URI": NEO4J_URI,
    "NEO4J_USER": NEO4J_USER,
    "NEO4J_PASSWORD": NEO4J_PASSWORD,
}

__all__ = [
    "MCP_COMMAND", "MCP_ARGS", "MCP_ENV_OVERRIDES",
    "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "CVG_CHAT_PROVIDER", "CVG_CHAT_MODEL",
    "QDRANT_URL", "QDRANT_COLLECTION", "QDRANT_DIMENSIONS", "MODEL_ID",
    "NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD",
]
