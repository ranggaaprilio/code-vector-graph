"""Qdrant browse/introspection endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

from code_vector_graph.api.config import QDRANT_COLLECTION
from code_vector_graph.api.deps import get_qdrant, get_registry
from code_vector_graph.api.services.apps import WIKI_SOURCE, ApplicationRegistry, AppScope

router = APIRouter(prefix="/qdrant")
logger = logging.getLogger(__name__)

# How many scroll pages to walk when the scope has to be applied client-side.
_MAX_CLIENT_FILTER_PAGES = 3


@router.get("/collections")
def list_collections(qdrant: QdrantClient = Depends(get_qdrant)):
    resp = qdrant.get_collections()
    return {"collections": [c.name for c in resp.collections]}


@router.get("/collection")
def collection_info(qdrant: QdrantClient = Depends(get_qdrant)):
    try:
        info = qdrant.get_collection(QDRANT_COLLECTION)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Qdrant error: {e}") from e
    cfg = info.config
    params = cfg.params if cfg else None
    vectors = params.vectors if params else None
    if hasattr(vectors, "size"):
        vector_size = vectors.size
        distance = str(vectors.distance)
    else:
        vector_size = None
        distance = None
    return {
        "collection": QDRANT_COLLECTION,
        "points_count": info.points_count,
        "indexed_vectors_count": info.indexed_vectors_count,
        "vector_size": vector_size,
        "distance": distance,
        "status": str(info.status),
    }


def _resolve_scope(registry: ApplicationRegistry, app: str | None, repo: str | None) -> AppScope | None:
    """Scope from `app`/`repo`; a bare `repo` is looked up across all applications."""
    if not app and not repo:
        return None
    try:
        if app:
            return registry.scope(app, repo or None)
        for info in registry.list():
            if any(r.name == repo for r in info.repos):
                return registry.scope(info.name, repo)
        raise KeyError(f"Unknown repository '{repo}'")
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.get("/points")
def browse_points(
    limit: int = Query(default=50, le=200),
    offset: str | None = Query(default=None, description="Opaque scroll offset from previous response"),
    language: str | None = None,
    file_path: str | None = None,
    node_type: str | None = None,
    app: str | None = None,
    repo: str | None = None,
    source: str | None = Query(default=None, description="'code' | 'wiki' | None for both"),
    file_prefix: str | None = Query(default=None, description="Keep points whose file_path starts with this"),
    qdrant: QdrantClient = Depends(get_qdrant),
    registry: ApplicationRegistry = Depends(get_registry),
):
    must = []
    must_not = []
    if language:
        must.append(FieldCondition(key="language", match=MatchValue(value=language)))
    if file_path:
        must.append(FieldCondition(key="file_path", match=MatchValue(value=file_path)))
    if node_type:
        must.append(FieldCondition(key="node_type", match=MatchValue(value=node_type)))
    if source == "code":
        must_not.append(FieldCondition(key="source", match=MatchValue(value=WIKI_SOURCE)))
    elif source == "wiki":
        must.append(FieldCondition(key="source", match=MatchValue(value=WIKI_SOURCE)))

    scope = _resolve_scope(registry, app, repo)
    client_side_scope = False
    if scope is not None:
        if scope.all_recorded:
            names = scope.repo_names
            must.append(
                FieldCondition(key="repo", match=MatchValue(value=names[0]) if len(names) == 1 else MatchAny(any=names))
            )
        else:
            client_side_scope = True

    scroll_filter = Filter(must=must or None, must_not=must_not or None) if (must or must_not) else None
    needs_client_filter = client_side_scope or bool(file_prefix)
    scroll_offset = offset if offset else None

    def keep(payload: dict) -> bool:
        fp = payload.get("file_path") or ""
        if file_prefix and not fp.startswith(file_prefix):
            return False
        if client_side_scope:
            if payload.get("source") == WIKI_SOURCE:
                prepo = payload.get("repo")
                return prepo is None or prepo in scope.repo_names
            return scope.matches_path(fp, payload.get("repo"))
        return True

    kept = []
    next_offset = scroll_offset
    pages = _MAX_CLIENT_FILTER_PAGES if needs_client_filter else 1
    try:
        for _ in range(pages):
            points, next_offset = qdrant.scroll(
                collection_name=QDRANT_COLLECTION,
                limit=limit,
                offset=next_offset,
                scroll_filter=scroll_filter,
                with_payload=True,
                with_vectors=False,
            )
            for p in points:
                if not needs_client_filter or keep(p.payload or {}):
                    kept.append({"id": str(p.id), "payload": p.payload})
            if next_offset is None or len(kept) >= limit:
                break
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    return {
        "points": kept[:limit],
        "next_offset": str(next_offset) if next_offset else None,
        "scope": scope.label if scope else None,
    }


@router.get("/points/{point_id}")
def get_point(point_id: str, qdrant: QdrantClient = Depends(get_qdrant)):
    try:
        results = qdrant.retrieve(
            collection_name=QDRANT_COLLECTION,
            ids=[point_id],
            with_payload=True,
            with_vectors=False,
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    if not results:
        raise HTTPException(status_code=404, detail="Point not found")
    p = results[0]
    return {"id": str(p.id), "payload": p.payload}
