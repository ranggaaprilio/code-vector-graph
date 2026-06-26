"""Qdrant browse/introspection endpoints."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

from dashboard.deps import get_qdrant
from dashboard.settings import QDRANT_COLLECTION

router = APIRouter(prefix="/qdrant")
logger = logging.getLogger(__name__)


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


@router.get("/points")
def browse_points(
    limit: int = Query(default=50, le=200),
    offset: str | None = Query(default=None, description="Opaque scroll offset from previous response"),
    language: str | None = None,
    file_path: str | None = None,
    node_type: str | None = None,
    qdrant: QdrantClient = Depends(get_qdrant),
):
    conditions = []
    if language:
        conditions.append(FieldCondition(key="language", match=MatchValue(value=language)))
    if file_path:
        conditions.append(FieldCondition(key="file_path", match=MatchValue(value=file_path)))
    if node_type:
        conditions.append(FieldCondition(key="node_type", match=MatchValue(value=node_type)))
    scroll_filter = Filter(must=conditions) if conditions else None

    # offset can be a UUID string (point id) or None for the first page
    scroll_offset = offset if offset else None

    try:
        points, next_offset = qdrant.scroll(
            collection_name=QDRANT_COLLECTION,
            limit=limit,
            offset=scroll_offset,
            scroll_filter=scroll_filter,
            with_payload=True,
            with_vectors=False,
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    return {
        "points": [{"id": str(p.id), "payload": p.payload} for p in points],
        "next_offset": str(next_offset) if next_offset else None,
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
