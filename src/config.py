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
DEFAULT_CHUNK_SIZE = 512
DEFAULT_CHUNK_OVERLAP = 64
DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_QDRANT_URL = "http://localhost:6333"
DEFAULT_COLLECTION_NAME = "code_chunks"
DEFAULT_MODEL = "nomic-embed-text:latest"
EMBEDDING_DIMENSIONS = 768
EMBEDDING_PREFIX = "search_document: "
TOKENIZER_NAME = "bert-base-uncased"

# Embedding provider configuration
EMBEDDING_PROVIDERS = {
    "ollama": {
        "model": "nomic-embed-text:latest",
        "dimensions": 768,
        "prefix": "search_document: ",
        "query_prefix": "search_query: ",
    },
    "huggingface": {
        "model": "Salesforce/codet5p-110m-embedding",
        "dimensions": 256,
        "prefix": "",  # No prefix for HuggingFace
        "query_prefix": "",
    },
}
DEFAULT_PROVIDER = "ollama"

HF_TOKEN = os.getenv("HF_TOKEN", "")
