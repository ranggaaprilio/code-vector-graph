"""Semantic search endpoint — routes through MCP search_code_json, scoped to an app/repo."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from code_vector_graph.api.deps import get_mcp, get_registry
from code_vector_graph.api.mcp_client import MCPSessionManager
from code_vector_graph.api.schemas import SearchRequest, SearchResponse, SearchResult
from code_vector_graph.api.services.apps import ApplicationRegistry, AppScope

router = APIRouter()
logger = logging.getLogger(__name__)


def _in_scope(item: dict, scope: AppScope) -> bool:
    """Code hits must live in a scoped repo; wiki hits pass when their repo matches or is unknown."""
    repo = item.get("repo")
    if item.get("source") == "wiki":
        return repo is None or repo in scope.repo_names
    return scope.matches_path(item.get("file_path"), repo)


@router.post("/search", response_model=SearchResponse)
async def semantic_search(
    req: SearchRequest,
    mcp: MCPSessionManager = Depends(get_mcp),
    registry: ApplicationRegistry = Depends(get_registry),
):
    if not mcp.is_alive:
        raise HTTPException(status_code=503, detail="MCP session is not running")

    scope: AppScope | None = None
    if req.app:
        try:
            scope = registry.scope(req.app, req.repo or None)
        except KeyError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    args = {
        "query": req.query,
        "mode": req.mode,
        "top_k": req.top_k,
        "language": req.language,
        "file_pattern": req.file_pattern,
        "min_score": req.min_score,
        "vector_weight": req.vector_weight,
        "graph_weight": req.graph_weight,
        "source": req.source,
        "include_wiki": req.include_wiki,
    }
    if scope is not None:
        args["repos"] = scope.repo_names
        args["repo_roots"] = scope.repo_roots

    try:
        data = await mcp.call_tool_json("search_code_json", args)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    if "error" in data and not data.get("results"):
        raise HTTPException(status_code=500, detail=data["error"])

    results = []
    for raw in data.get("results", []):
        if scope is not None:
            if not _in_scope(raw, scope):
                continue
            raw = dict(raw)
            # `raw` already carries "app"/"rel_path" keys with a None value for
            # legacy data (the MCP item always includes them) — `setdefault`
            # would see the key present and never fill them in, so check the
            # value instead.
            raw["app"] = raw.get("app") or scope.app
            if not raw.get("repo") and raw.get("source") != "wiki":
                repo = scope.repo_for(raw.get("file_path"))
                if repo is not None:
                    raw["repo"] = repo.name
                    raw["rel_path"] = raw.get("rel_path") or repo.rel_path(raw.get("file_path") or "")
        if raw.get("source") == "wiki" and not raw.get("concept_id") and raw.get("symbol_id"):
            raw["concept_id"] = raw["symbol_id"]
        results.append(SearchResult(**raw))
    return SearchResponse(results=results, query=req.query)
