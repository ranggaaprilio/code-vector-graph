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
DEFAULT_MODEL = "nomic-ai/nomic-embed-code"
EMBEDDING_DIMENSIONS = 3584
TOKENIZER_NAME = "nomic-ai/nomic-embed-code"

EMBEDDING_PROVIDERS = {
    "huggingface": {
        "model": "nomic-ai/nomic-embed-code",
        "dimensions": 3584,
    },
}
DEFAULT_PROVIDER = "huggingface"

HF_TOKEN = os.getenv("HF_TOKEN", "")

# Neo4j configuration
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "testpassword"
NEO4J_DATABASE = "neo4j"
