import os

SUPPORTED_EXTENSIONS = {
    ".js": {"language": "javascript", "grammar": "javascript"},
    ".jsx": {"language": "javascript", "grammar": "javascript"},
    ".mjs": {"language": "javascript", "grammar": "javascript"},
    ".cjs": {"language": "javascript", "grammar": "javascript"},
    ".ts": {"language": "typescript", "grammar": "typescript"},
    ".tsx": {"language": "tsx", "grammar": "tsx"},
    ".mts": {"language": "typescript", "grammar": "typescript"},
    ".cts": {"language": "typescript", "grammar": "typescript"},
}

COMMENT_NODE_TYPES = ("comment", "line_comment", "block_comment")
DEFAULT_CHUNK_SIZE = 400
DEFAULT_CHUNK_OVERLAP = 64
DEFAULT_QDRANT_URL = "http://localhost:6333"
DEFAULT_COLLECTION_NAME = "code_chunks"
# Base collection name the MCP server / dashboard read from by default (what
# run_mac_mps_24gb.sh indexes into). The final Qdrant collection is derived from
# it plus the model suffix via get_collection_name().
DEFAULT_BASE_COLLECTION = "code_chunks_mac_mps_24gb"

# Qdrant endpoint — env-overridable (QDRANT_URL), defaults to the local docker-compose.
QDRANT_URL = os.getenv("QDRANT_URL", DEFAULT_QDRANT_URL)

MODEL_CONFIGS = {
    "nomic": {
        "model_name": "nomic-ai/nomic-embed-code",
        "dimensions": 3584,
        "tokenizer_name": "nomic-ai/nomic-embed-code",
        "dtype": "float16",
        "prefixes": None,
    },
    "jina": {
        "model_name": "jinaai/jina-code-embeddings-1.5b",
        "dimensions": 1536,
        "tokenizer_name": "jinaai/jina-code-embeddings-1.5b",
        "dtype": "bfloat16",
        "prefixes": {
            "code2code": {
                "query": "Find an equivalent code snippet given the following code snippet:\n",
                "passage": "Candidate code snippet:\n",
            },
            "nl2code": {
                "query": "Find the most relevant code snippet given the following query:\n",
                "passage": "Candidate code snippet:\n",
            },
        },
    },
}

# Active embedding model, selectable via env (e.g. EMBEDDING_MODEL_ID=jina).
# Must match one of the keys in MODEL_CONFIGS above.
DEFAULT_MODEL_ID = os.getenv("EMBEDDING_MODEL_ID", "nomic")
if DEFAULT_MODEL_ID not in MODEL_CONFIGS:
    raise ValueError(
        f"Invalid EMBEDDING_MODEL_ID '{DEFAULT_MODEL_ID}'. Available: {list(MODEL_CONFIGS.keys())}"
    )

DEFAULT_MODEL = MODEL_CONFIGS[DEFAULT_MODEL_ID]["model_name"]
EMBEDDING_DIMENSIONS = MODEL_CONFIGS[DEFAULT_MODEL_ID]["dimensions"]
TOKENIZER_NAME = MODEL_CONFIGS[DEFAULT_MODEL_ID]["tokenizer_name"]

EMBEDDING_PROVIDERS = {
    "huggingface": {
        "model": MODEL_CONFIGS[DEFAULT_MODEL_ID]["model_name"],
        "dimensions": MODEL_CONFIGS[DEFAULT_MODEL_ID]["dimensions"],
    },
}

DEFAULT_PROVIDER = "huggingface"

HF_TOKEN = os.getenv("HF_TOKEN", "")

# Neo4j configuration — env-overridable, defaults match docker-compose.yml.
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "testpassword")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")
# Neo4j's own default (30s) makes a dead server hang every write-retrying query
# (e.g. the dashboard's /api/apps discovery) for 30+ seconds before failing.
# Bound it low enough that "database is down" still degrades quickly.
NEO4J_MAX_RETRY_TIME = float(os.getenv("NEO4J_MAX_RETRY_TIME", "5"))

# DeepSeek configuration (OKF "LLM wiki" enrichment).
# DeepSeek is OpenAI-compatible, so the `openai` SDK is pointed at this base URL.
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

# Model tiers for OKF enrichment. `flash` is used for leaf/mid concept pages
# (functions, methods, classes, files); `pro` for module/architecture overviews.
# Note: the legacy `deepseek-chat`/`deepseek-reasoner` names are discontinued
# 2026-07-24 — use the v4 names.
OKF_MODEL_FLASH = os.getenv("OKF_MODEL_FLASH", "deepseek-v4-flash")
OKF_MODEL_PRO = os.getenv("OKF_MODEL_PRO", "deepseek-v4-pro")

# Default output directory for the generated OKF wiki bundle.
OKF_OUT_DIR = os.getenv("OKF_OUT_DIR", "okf-wiki")

# Dashboard chat (LLM) settings. CVG_CHAT_PROVIDER selects "anthropic" | "openai" |
# "deepseek"; empty means auto-detect from whichever API key is configured.
CVG_CHAT_PROVIDER = os.getenv("CVG_CHAT_PROVIDER", "")
CVG_CHAT_MODEL = os.getenv("CVG_CHAT_MODEL", "")
CVG_CHAT_BASE_URL = os.getenv("CVG_CHAT_BASE_URL", "")
CVG_CHAT_API_KEY = os.getenv("CVG_CHAT_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# Application / repository identity (see repos.py). CVG_REPOS_ROOT is the directory
# whose first child component names the application (e.g. /Users/me/Repository →
# "onebid"). CVG_REPO_MAP / CVG_APP_MAP are raw JSON strings, parsed by consumers.
CVG_REPOS_ROOT = os.getenv("CVG_REPOS_ROOT", "")
CVG_REPO_MAP = os.getenv("CVG_REPO_MAP", "")
CVG_APP_MAP = os.getenv("CVG_APP_MAP", "")
CVG_APPS_CACHE_TTL = int(os.getenv("CVG_APPS_CACHE_TTL", "300") or 300)


def active_model_id() -> str:
    """Embedding model the MCP server / dashboard should read with (CVG_MODEL_ID).

    Reads both env vars at call time rather than falling back to the
    import-time-frozen ``DEFAULT_MODEL_ID`` — otherwise whichever module
    happens to import this one *first* in the process decides the default,
    which is exactly the kind of divergence this function exists to prevent.
    """
    model_id = os.getenv("CVG_MODEL_ID") or os.getenv("EMBEDDING_MODEL_ID", "nomic")
    if model_id not in MODEL_CONFIGS:
        raise ValueError(f"Invalid CVG_MODEL_ID '{model_id}'. Available: {list(MODEL_CONFIGS.keys())}")
    return model_id


def active_base_collection() -> str:
    """Base Qdrant collection name to read from (CVG_COLLECTION_NAME), before the model suffix."""
    return os.getenv("CVG_COLLECTION_NAME", DEFAULT_BASE_COLLECTION)


def active_collection() -> tuple[str, int, str]:
    """Resolve the (collection_name, dimensions, model_id) the read side should use.

    Reads env at call time so the dashboard and the MCP server it spawns agree.
    `get_collection_name` is imported lazily: stores.vector_store imports this module.
    """
    from code_vector_graph.stores.vector_store import get_collection_name

    model_id = active_model_id()
    cfg = MODEL_CONFIGS[model_id]
    name = get_collection_name(active_base_collection(), "huggingface", model=cfg["model_name"])
    return name, cfg["dimensions"], model_id


def get_model_config(model_id: str) -> dict:
    """Resolve model config by ID (e.g., 'nomic' or 'jina')."""
    if model_id not in MODEL_CONFIGS:
        raise ValueError(f"Unknown model_id '{model_id}'. Available: {list(MODEL_CONFIGS.keys())}")
    return MODEL_CONFIGS[model_id]
