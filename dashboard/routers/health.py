"""Health check endpoint."""

import logging

from fastapi import APIRouter, Depends, Query
from qdrant_client import QdrantClient

from dashboard.deps import get_graph, get_mcp, get_qdrant
from dashboard.mcp_client import MCPSessionManager
from dashboard.settings import NEO4J_URI, QDRANT_URL
from src.graph_store import GraphStore

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/health")
async def health(
    deep: bool = Query(default=False, description="Also check embedder via MCP check_health tool"),
    qdrant: QdrantClient = Depends(get_qdrant),
    graph: GraphStore = Depends(get_graph),
    mcp: MCPSessionManager = Depends(get_mcp),
):
    result: dict = {}

    # Qdrant
    try:
        qdrant.get_collections()
        result["qdrant"] = {"ok": True, "url": QDRANT_URL}
    except Exception as e:
        result["qdrant"] = {"ok": False, "url": QDRANT_URL, "error": str(e)}

    # Neo4j
    try:
        ok = graph.check_health()
        result["neo4j"] = {"ok": bool(ok), "uri": NEO4J_URI}
    except Exception as e:
        result["neo4j"] = {"ok": False, "uri": NEO4J_URI, "error": str(e)}

    # MCP session
    result["mcp_session"] = {"ok": mcp.is_alive}

    # Embedder (optional deep check — loads the model on first call)
    if deep:
        try:
            detail = await mcp.call_tool("check_health", {})
            result["embedder"] = {"checked": True, "detail": detail}
        except Exception as e:
            result["embedder"] = {"checked": False, "detail": str(e)}

    return result
