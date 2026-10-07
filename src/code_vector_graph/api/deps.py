"""FastAPI dependency providers."""

from functools import lru_cache

from qdrant_client import QdrantClient

from code_vector_graph.api.mcp_client import MCPSessionManager, get_mcp_manager
from code_vector_graph.api.config import (
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USER,
    QDRANT_COLLECTION,
    QDRANT_DIMENSIONS,
    QDRANT_URL,
)
from code_vector_graph.api.services.apps import ApplicationRegistry
from code_vector_graph.config import CVG_APP_MAP, CVG_APPS_CACHE_TTL, CVG_REPO_MAP, CVG_REPOS_ROOT
from code_vector_graph.repos import parse_json_map
from code_vector_graph.stores.graph_store import GraphStore


@lru_cache(maxsize=1)
def get_qdrant() -> QdrantClient:
    return QdrantClient(url=QDRANT_URL, prefer_grpc=False)


@lru_cache(maxsize=1)
def get_graph() -> GraphStore:
    return GraphStore(uri=NEO4J_URI, user=NEO4J_USER, password=NEO4J_PASSWORD)


def get_mcp() -> MCPSessionManager:
    return get_mcp_manager()


@lru_cache(maxsize=1)
def get_registry() -> ApplicationRegistry:
    """Application/repository registry shared by all routers (cached with CVG_APPS_CACHE_TTL)."""
    return ApplicationRegistry(
        graph=get_graph(),
        qdrant=get_qdrant(),
        collection=QDRANT_COLLECTION,
        ttl=CVG_APPS_CACHE_TTL,
        repos_root=CVG_REPOS_ROOT or None,
        repo_map=parse_json_map(CVG_REPO_MAP),
        app_map=parse_json_map(CVG_APP_MAP),
    )
