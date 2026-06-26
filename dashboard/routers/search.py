"""Semantic search endpoint — routes through MCP search_code_json."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from dashboard.deps import get_mcp
from dashboard.mcp_client import MCPSessionManager
from dashboard.schemas import SearchRequest, SearchResponse, SearchResult

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/search", response_model=SearchResponse)
async def semantic_search(req: SearchRequest, mcp: MCPSessionManager = Depends(get_mcp)):
    if not mcp.is_alive:
        raise HTTPException(status_code=503, detail="MCP session is not running")
    try:
        data = await mcp.call_tool_json(
            "search_code_json",
            {
                "query": req.query,
                "mode": req.mode,
                "top_k": req.top_k,
                "language": req.language,
                "file_pattern": req.file_pattern,
                "min_score": req.min_score,
                "vector_weight": req.vector_weight,
                "graph_weight": req.graph_weight,
            },
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    if "error" in data and not data.get("results"):
        raise HTTPException(status_code=500, detail=data["error"])

    results = [SearchResult(**r) for r in data.get("results", [])]
    return SearchResponse(results=results, query=req.query)
