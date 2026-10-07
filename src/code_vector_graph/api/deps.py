"""FastAPI dependency providers."""

import logging
from functools import lru_cache

from qdrant_client import QdrantClient

from code_vector_graph.api.mcp_client import MCPSessionManager, get_mcp_manager
from code_vector_graph.api.config import (
    MODEL_ID,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USER,
    QDRANT_COLLECTION,
    QDRANT_DIMENSIONS,
    QDRANT_URL,
)
from code_vector_graph.api.services.apps import ApplicationRegistry
from code_vector_graph.config import (
    CVG_API_EMBEDDER,
    CVG_APP_MAP,
    CVG_APPS_CACHE_TTL,
    CVG_REPO_MAP,
    CVG_REPOS_ROOT,
    okf_llm_settings,
)
from code_vector_graph.repos import parse_json_map
from code_vector_graph.stores.graph_store import GraphStore
from code_vector_graph.stores.vector_store import VectorStore

logger = logging.getLogger(__name__)


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


@lru_cache(maxsize=1)
def get_vector_store() -> VectorStore:
    return VectorStore(collection_name=QDRANT_COLLECTION, qdrant_url=QDRANT_URL, embedding_dimensions=QDRANT_DIMENSIONS)


@lru_cache(maxsize=1)
def get_embedder():
    """Embedding model for re-embedding an edited/regenerated Feature page.

    Lazy (nothing loads until the first call) and never raises: ``None`` when
    disabled (``CVG_API_EMBEDDER=off``) or unavailable, in which case the
    caller must mark the page ``needs_reembed=true`` instead of failing the
    save — the next ``cvg-docs-build`` run catches it up.
    """
    if CVG_API_EMBEDDER == "off":
        return None
    try:
        from code_vector_graph.embeddings.embedder import create_embedder

        return create_embedder(model_id=MODEL_ID)
    except Exception:
        logger.warning("Embedder unavailable for Feature-doc re-embedding", exc_info=True)
        return None


@lru_cache(maxsize=1)
def get_llm_client():
    """LLM client for Feature-doc generation/regeneration (DeepSeek or a local
    oMLX server, per ``OKF_LLM_PROVIDER``); ``None`` if it is not configured or
    the local server cannot be reached (never raises)."""
    try:
        s = okf_llm_settings()
    except ValueError as exc:
        logger.warning("Feature-doc LLM disabled: %s", exc)
        return None
    if not s.api_key and not s.local:
        return None
    from code_vector_graph.ingestion.okf.enricher import make_client

    try:
        return make_client()
    except ValueError as exc:
        logger.warning("Feature-doc LLM disabled: %s", exc)
        return None


@lru_cache(maxsize=1)
def get_docs_jobs():
    from code_vector_graph.api.services.docs_jobs import DocsJobManager

    return DocsJobManager()
