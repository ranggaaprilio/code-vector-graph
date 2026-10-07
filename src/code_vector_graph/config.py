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
DEFAULT_BASE_COLLECTION = "code_chunks"

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

# --- OKF "LLM wiki" enrichment provider ---------------------------------------
# OKF_LLM_PROVIDER selects which LLM writes the wiki/feature docs:
#   "deepseek" (default) — DeepSeek cloud API (needs DEEPSEEK_API_KEY)
#   "omlx"               — a local oMLX server (Apple Silicon, MLX) or any other
#                          OpenAI-compatible local endpoint; models such as Gemma
#                          or Qwen run fully offline. Needs OMLX_API_KEY unless the
#                          server has API-key verification disabled.
# Both speak the OpenAI chat-completions protocol, so the same `openai` SDK client
# is used; only base URL, key, default models and a few request knobs differ.
OKF_LLM_PROVIDERS = ("deepseek", "omlx")
OKF_LLM_PROVIDER = os.getenv("OKF_LLM_PROVIDER", "deepseek").strip().lower() or "deepseek"
if OKF_LLM_PROVIDER not in OKF_LLM_PROVIDERS:
    raise ValueError(
        f"Invalid OKF_LLM_PROVIDER '{OKF_LLM_PROVIDER}'. Available: {list(OKF_LLM_PROVIDERS)}"
    )

# DeepSeek configuration. DeepSeek is OpenAI-compatible, so the `openai` SDK is
# pointed at this base URL.
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

# oMLX configuration (local). The default port/path match `omlx serve`; the model
# id is the directory name under ~/.omlx/models (see GET /v1/models).
OMLX_API_KEY = os.getenv("OMLX_API_KEY", "")
OMLX_BASE_URL = os.getenv("OMLX_BASE_URL", "http://localhost:8000/v1")
OMLX_MODEL = os.getenv("OMLX_MODEL", "gemma-4-e2b-it-4bit")

# Model tiers for OKF enrichment. `flash` is used for leaf/mid concept pages
# (functions, methods, classes, files); `pro` for module/architecture overviews.
# Defaults depend on the provider: DeepSeek v4 tiers (the legacy `deepseek-chat`/
# `deepseek-reasoner` names are discontinued 2026-07-24), or the single local
# OMLX_MODEL for both tiers.
_OKF_DEFAULT_MODELS = {
    "deepseek": ("deepseek-v4-flash", "deepseek-v4-pro"),
    "omlx": (OMLX_MODEL, OMLX_MODEL),
}
OKF_MODEL_FLASH = os.getenv("OKF_MODEL_FLASH", _OKF_DEFAULT_MODELS[OKF_LLM_PROVIDER][0])
OKF_MODEL_PRO = os.getenv("OKF_MODEL_PRO", _OKF_DEFAULT_MODELS[OKF_LLM_PROVIDER][1])

# Concurrent enrichment requests. A cloud API happily takes 6; a local server
# batches internally and has finite memory, so default lower there.
_OKF_DEFAULT_CONCURRENCY = {"deepseek": 6, "omlx": 2}
OKF_CONCURRENCY = int(
    os.getenv("OKF_CONCURRENCY", "") or _OKF_DEFAULT_CONCURRENCY[OKF_LLM_PROVIDER]
)

# Default output directory for the generated OKF wiki bundle.
OKF_OUT_DIR = os.getenv("OKF_OUT_DIR", "okf-wiki")

# Feature-level docs (see ingestion/okf/features/). Written as WikiPage
# {type:"Feature"} nodes on top of the same OKF bundle/pipeline.
CVG_DOCS_LANGUAGE = os.getenv("CVG_DOCS_LANGUAGE", "en")
OKF_FEATURES_MODEL = os.getenv("OKF_FEATURES_MODEL", OKF_MODEL_PRO)
OKF_FEATURE_MAP_MAX_FILES = int(os.getenv("OKF_FEATURE_MAP_MAX_FILES", "250") or 250)
OKF_FEATURE_MAP_MAX_CHARS = int(os.getenv("OKF_FEATURE_MAP_MAX_CHARS", "60000") or 60000)
OKF_FEATURE_SOURCE_CHARS = int(os.getenv("OKF_FEATURE_SOURCE_CHARS", "24000") or 24000)
OKF_MAX_FEATURES = int(os.getenv("OKF_MAX_FEATURES", "40") or 40)
# "lazy" loads the embedding model in the API process on first save/regenerate
# (needed to keep Qdrant in sync with an edited/regenerated Feature page);
# "off" skips it entirely and marks affected pages `needs_reembed=true` instead
# (safe fallback on memory-constrained hosts — see docs/feature-docs.md).
CVG_API_EMBEDDER = os.getenv("CVG_API_EMBEDDER", "lazy")
CVG_DOCS_BUNDLE_DIR = os.getenv("CVG_DOCS_BUNDLE_DIR", OKF_OUT_DIR)

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


class OkfLLMSettings(dict):
    """Resolved OKF enrichment LLM settings (dict with attribute access).

    Keys: provider, api_key, base_url, key_env, model_flash, model_pro,
    concurrency, local (bool — True for a self-hosted endpoint such as oMLX).
    """

    __getattr__ = dict.__getitem__


def okf_llm_settings() -> OkfLLMSettings:
    """Resolve the enrichment LLM (provider, key, base URL, models) from the env.

    Read at call time — not from the import-time constants above — so the
    dashboard API (which loads .env later) and tests that monkeypatch
    ``os.environ`` see the current values.
    """
    provider = (os.getenv("OKF_LLM_PROVIDER", "deepseek").strip().lower() or "deepseek")
    if provider not in OKF_LLM_PROVIDERS:
        raise ValueError(
            f"Invalid OKF_LLM_PROVIDER '{provider}'. Available: {list(OKF_LLM_PROVIDERS)}"
        )
    if provider == "omlx":
        model = os.getenv("OMLX_MODEL", "gemma-4-e2b-it-4bit")
        api_key = os.getenv("OMLX_API_KEY", "")
        base_url = os.getenv("OMLX_BASE_URL", "http://localhost:8000/v1")
        key_env = "OMLX_API_KEY"
        default_flash, default_pro = model, model
    else:
        api_key = os.getenv("DEEPSEEK_API_KEY", "")
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        key_env = "DEEPSEEK_API_KEY"
        default_flash, default_pro = _OKF_DEFAULT_MODELS["deepseek"]
    return OkfLLMSettings(
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        key_env=key_env,
        model_flash=os.getenv("OKF_MODEL_FLASH", "") or default_flash,
        model_pro=os.getenv("OKF_MODEL_PRO", "") or default_pro,
        concurrency=int(os.getenv("OKF_CONCURRENCY", "") or _OKF_DEFAULT_CONCURRENCY[provider]),
        local=provider == "omlx",
    )
