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

DEFAULT_MODEL_ID = "nomic"

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

# Neo4j configuration
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "testpassword"
NEO4J_DATABASE = "neo4j"


def get_model_config(model_id: str) -> dict:
    """Resolve model config by ID (e.g., 'nomic' or 'jina')."""
    if model_id not in MODEL_CONFIGS:
        raise ValueError(f"Unknown model_id '{model_id}'. Available: {list(MODEL_CONFIGS.keys())}")
    return MODEL_CONFIGS[model_id]
