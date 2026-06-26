"""FastAPI dependency providers."""

from functools import lru_cache

from qdrant_client import QdrantClient

from dashboard.mcp_client import MCPSessionManager, get_mcp_manager
from dashboard.settings import (
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USER,
    QDRANT_COLLECTION,
    QDRANT_DIMENSIONS,
    QDRANT_URL,
)
from src.graph_store import GraphStore


@lru_cache(maxsize=1)
def get_qdrant() -> QdrantClient:
    return QdrantClient(url=QDRANT_URL, prefer_grpc=False)


@lru_cache(maxsize=1)
def get_graph() -> GraphStore:
    return GraphStore(uri=NEO4J_URI, user=NEO4J_USER, password=NEO4J_PASSWORD)


def get_mcp() -> MCPSessionManager:
    return get_mcp_manager()
