"""MCP server exposing code search tools from the code-vector-graph project."""

import fnmatch
import json
import logging
from typing import Optional

from mcp.server.fastmcp import FastMCP

from src.config import (
    DEFAULT_COLLECTION_NAME,
    DEFAULT_MODEL_ID,
    DEFAULT_QDRANT_URL,
    get_model_config,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USER,
)
from src.embedder import create_embedder
from src.graph_store import GraphStore
from src.hybrid_retriever import HybridRetriever
from src.store import VectorStore, get_collection_name

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

mcp = FastMCP("code-vector-graph")

# Lazy singletons — model load is expensive, initialize on first use
_embedder = None
_store = None
_graph_store = None


_MODEL_ID = "jina"
_BASE_COLLECTION = "code_chunks_mac_mps_24gb"


def _get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = create_embedder(model_id=_MODEL_ID)
    return _embedder


def _get_store():
    global _store
    if _store is None:
        model_config = get_model_config(_MODEL_ID)
        dimensions = model_config["dimensions"]
        collection_name = get_collection_name(_BASE_COLLECTION, "huggingface", model=model_config["model_name"])
        _store = VectorStore(
            collection_name=collection_name,
            qdrant_url=DEFAULT_QDRANT_URL,
            embedding_dimensions=dimensions,
        )
    return _store


def _get_graph_store():
    global _graph_store
    if _graph_store is None:
        _graph_store = GraphStore(uri=NEO4J_URI, user=NEO4J_USER, password=NEO4J_PASSWORD)
    return _graph_store


def _retrieve(
    query: str,
    mode: str = "hybrid",
    top_k: int = 10,
    language: Optional[str] = None,
    file_pattern: Optional[str] = None,
    min_score: float = 0.0,
    vector_weight: float = 0.7,
    graph_weight: float = 0.3,
) -> list[dict]:
    """Shared retrieval logic used by both search_code and search_code_json."""
    embedder = _get_embedder()
    store = _get_store()
    query_vector = embedder.embed_query(query)

    if mode == "vector":
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        filter_conditions = []
        if language:
            filter_conditions.append(
                FieldCondition(key="language", match=MatchValue(value=language))
            )
        query_filter = Filter(must=filter_conditions) if filter_conditions else None
        raw = store.search(query_vector, top_k=top_k, query_filter=query_filter)
        results = [
            {
                "id": r.get("id"),
                "payload": r.get("payload"),
                "score": r.get("score"),
                "graph_context": None,
            }
            for r in raw
        ]

    elif mode == "graph":
        graph_store = _get_graph_store()
        cypher = (
            "MATCH (n) "
            "WHERE toLower(n.name) CONTAINS toLower($query) "
            "   OR toLower(n.path) CONTAINS toLower($query) "
            "RETURN n.id AS id, n AS node, 1.0 AS score "
            "LIMIT $limit"
        )
        raw = graph_store.query_graph(cypher, {"query": query, "limit": top_k})
        records = raw.records if hasattr(raw, "records") else raw
        results = []
        for rec in records:
            node = rec.get("node") if hasattr(rec, "get") else None
            node_data = dict(node.items()) if node and hasattr(node, "items") else {}
            results.append(
                {
                    "id": rec.get("id") if hasattr(rec, "get") else None,
                    "payload": node_data,
                    "score": rec.get("score", 1.0) if hasattr(rec, "get") else 1.0,
                    "graph_context": None,
                }
            )

    else:  # hybrid
        graph_store = _get_graph_store()
        retriever = HybridRetriever(store, graph_store, embedder)
        results = retriever.search(
            query,
            mode="hybrid",
            top_k=top_k,
            vector_weight=vector_weight,
            graph_weight=graph_weight,
            query_vec=query_vector,
        )

    if file_pattern:
        results = [
            r for r in results
            if fnmatch.fnmatch((r.get("payload") or {}).get("file_path", ""), file_pattern)
        ]
    if min_score > 0:
        results = [r for r in results if r.get("score", 0) >= min_score]

    return results


def _format_results(results: list[dict]) -> str:
    if not results:
        return "No relevant code found."

    parts = []
    for i, r in enumerate(results, 1):
        payload = r.get("payload") or {}
        score = r.get("score", 0.0)
        file_path = payload.get("file_path", "unknown")
        start_line = payload.get("start_line", "")
        end_line = payload.get("end_line", "")
        language = payload.get("language", "")
        text = payload.get("text_content", "")
        func_name = payload.get("function_name", "")
        class_name = payload.get("class_name", "")

        location = f"{file_path}:{start_line}-{end_line}" if start_line and end_line else file_path
        symbol = func_name or class_name
        header = f"[{i}] {location}{f' ({symbol})' if symbol else ''} | score: {score:.4f}"

        parts.append(f"{header}\n```{language}\n{text}\n```")

        graph_ctx = r.get("graph_context")
        if graph_ctx:
            if hasattr(graph_ctx, "records"):
                records = list(graph_ctx.records)
                if records:
                    parts.append(f"[graph context: {records}]")
            elif graph_ctx:
                parts.append(f"[graph context: {graph_ctx}]")

    return "\n\n".join(parts)


@mcp.tool()
def search_code(
    query: str,
    mode: str = "hybrid",
    top_k: int = 10,
    language: Optional[str] = None,
    file_pattern: Optional[str] = None,
    min_score: float = 0.0,
    vector_weight: float = 0.7,
    graph_weight: float = 0.3,
) -> str:
    """Search indexed code using vector embeddings and/or graph relationships.

    Args:
        query: Natural language or code search query (e.g. "how does auth work", "getUserById")
        mode: Retrieval mode — "vector" (semantic similarity), "hybrid" (vector + graph, recommended), "graph" (Neo4j traversal only)
        top_k: Number of code chunks to return (default 10)
        language: Filter by language — "javascript", "typescript", or "tsx"
        file_pattern: Filter by file path glob pattern, e.g. "src/components/*" or "*.service.ts"
        min_score: Minimum similarity score 0.0–1.0 (higher = stricter relevance)
        vector_weight: Weight for vector results in hybrid mode (default 0.7)
        graph_weight: Weight for graph results in hybrid mode (default 0.3)

    Returns:
        Formatted code chunks with file paths, line numbers, and relevance scores
    """
    try:
        results = _retrieve(query, mode, top_k, language, file_pattern, min_score, vector_weight, graph_weight)
        return _format_results(results)
    except Exception as e:
        logger.exception("search_code failed")
        return f"Error: {e}"


@mcp.tool()
def search_code_json(
    query: str,
    mode: str = "hybrid",
    top_k: int = 10,
    language: Optional[str] = None,
    file_pattern: Optional[str] = None,
    min_score: float = 0.0,
    vector_weight: float = 0.7,
    graph_weight: float = 0.3,
) -> str:
    """Search indexed code and return structured JSON results for programmatic use.

    Args:
        query: Natural language or code search query (e.g. "how does auth work", "getUserById")
        mode: Retrieval mode — "vector" (semantic similarity), "hybrid" (vector + graph, recommended), "graph" (Neo4j traversal only)
        top_k: Number of code chunks to return (default 10)
        language: Filter by language — "javascript", "typescript", or "tsx"
        file_pattern: Filter by file path glob pattern, e.g. "src/components/*" or "*.service.ts"
        min_score: Minimum similarity score 0.0–1.0 (higher = stricter relevance)
        vector_weight: Weight for vector results in hybrid mode (default 0.7)
        graph_weight: Weight for graph results in hybrid mode (default 0.3)

    Returns:
        JSON string with structured results including file paths, line numbers, code content, and metadata
    """
    try:
        results = _retrieve(query, mode, top_k, language, file_pattern, min_score, vector_weight, graph_weight)
        structured = []
        for r in results:
            payload = r.get("payload") or {}
            structured.append({
                "id": str(r.get("id", "")),
                "score": round(float(r.get("score", 0.0)), 4),
                "file_path": payload.get("file_path", ""),
                "language": payload.get("language", ""),
                "start_line": payload.get("start_line"),
                "end_line": payload.get("end_line"),
                "function_name": payload.get("function_name"),
                "class_name": payload.get("class_name"),
                "node_type": payload.get("node_type"),
                "text_content": payload.get("text_content", ""),
                "imports": payload.get("imports", []),
                "exports": payload.get("exports", []),
                "symbols_defined": payload.get("symbols_defined", []),
                "call_sites": payload.get("call_sites", []),
                "token_count": payload.get("token_count"),
            })
        return json.dumps({"results": structured})
    except Exception as e:
        logger.exception("search_code_json failed")
        return json.dumps({"error": str(e), "results": []})


@mcp.tool()
def check_health() -> str:
    """Check connectivity and readiness of all components: embedder, Qdrant, and Neo4j.

    Returns:
        Status of each component with device and connection details
    """
    lines = []

    try:
        embedder = _get_embedder()
        ok = embedder.check_health()
        lines.append(f"Embedder ({embedder.model_name} on {embedder.device}): {'OK' if ok else 'FAIL'}")
    except Exception as e:
        lines.append(f"Embedder: FAIL — {e}")

    try:
        store = _get_store()
        ok = store.check_health()
        lines.append(f"Qdrant ({DEFAULT_QDRANT_URL}): {'OK' if ok else 'FAIL'}")
    except Exception as e:
        lines.append(f"Qdrant: FAIL — {e}")

    try:
        graph_store = _get_graph_store()
        ok = graph_store.check_health()
        lines.append(f"Neo4j ({NEO4J_URI}): {'OK' if ok else 'FAIL'}")
    except Exception as e:
        lines.append(f"Neo4j: FAIL — {e}")

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run(transport="stdio")
