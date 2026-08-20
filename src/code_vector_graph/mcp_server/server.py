"""MCP server exposing code search tools from the code-vector-graph project."""

import fnmatch
import json
import logging
import os
from typing import Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Load .env before importing code_vector_graph.config: config resolves DEFAULT_MODEL_ID (and the
# CVG_* overrides below) from the environment at import time.
load_dotenv()

from code_vector_graph.config import (  # noqa: E402
    DEFAULT_COLLECTION_NAME,
    DEFAULT_MODEL_ID,
    DEFAULT_QDRANT_URL,
    get_model_config,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USER,
)
from code_vector_graph.embeddings.embedder import create_embedder  # noqa: E402
from code_vector_graph.stores.graph_store import GraphStore  # noqa: E402
from code_vector_graph.retrieval.hybrid import HybridRetriever  # noqa: E402
from code_vector_graph.stores.vector_store import VectorStore, get_collection_name  # noqa: E402

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

mcp = FastMCP("code-vector-graph")

# Lazy singletons — model load is expensive, initialize on first use
_embedder = None
_store = None
_graph_store = None


# Which embedding model + Qdrant collection the server reads. Configurable via env
# so the MCP can point at whatever `cvg-ingest` / run_mac_mps_24gb.sh indexed into
# (e.g. CVG_COLLECTION_NAME=whiteboard). Defaults preserve prior behaviour.
_MODEL_ID = os.getenv("CVG_MODEL_ID", DEFAULT_MODEL_ID)
_BASE_COLLECTION = os.getenv("CVG_COLLECTION_NAME", "code_chunks_mac_mps_24gb")

# OKF wiki prose is stored in the SAME collection as code, tagged source="okf_wiki".
_WIKI_SOURCE = "okf_wiki"


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


def _is_wiki(payload: dict) -> bool:
    """True if a result is OKF wiki prose (Qdrant chunk) or a WikiPage graph node."""
    payload = payload or {}
    return payload.get("source") == _WIKI_SOURCE or "concept_id" in payload


def _wiki_context(file_path: str, symbol: str) -> Optional[dict]:
    """Best-effort OKF wiki explanation for a code hit, via the shared Neo4j graph.

    Code chunks carry no graph node id, so we join by path: a WikiPage's `resource`
    is a suffix of the code chunk's absolute file_path. Prefer a page whose title
    matches the hit's symbol (function/class), else the File-level page. Returns
    None (silently) if Neo4j is unreachable or nothing matches — never fatal.
    """
    if not file_path:
        return None
    try:
        graph_store = _get_graph_store()
        cypher = (
            "MATCH (w:WikiPage) "
            "WHERE w.resource <> '' AND $fp ENDS WITH ('/' + split(w.resource, '#')[0]) "
            "RETURN w.title AS title, w.summary AS summary, w.type AS type, w.path AS path "
            "ORDER BY CASE WHEN $sym <> '' AND w.title = $sym THEN 0 "
            "              WHEN w.type = 'File' THEN 1 ELSE 2 END "
            "LIMIT 1"
        )
        raw = graph_store.query_graph(cypher, {"fp": file_path, "sym": symbol or ""})
        records = raw.records if hasattr(raw, "records") else raw
        for rec in records:
            get = rec.get if hasattr(rec, "get") else (lambda k, d=None: d)
            title, summary = get("title"), get("summary")
            if title or summary:
                return {"title": title, "summary": summary, "type": get("type"), "path": get("path")}
    except Exception:
        logger.debug("wiki_context lookup failed for %s", file_path, exc_info=True)
    return None


def _retrieve(
    query: str,
    mode: str = "hybrid",
    top_k: int = 10,
    language: Optional[str] = None,
    file_pattern: Optional[str] = None,
    min_score: float = 0.0,
    vector_weight: float = 0.7,
    graph_weight: float = 0.3,
    source: str = "all",
) -> list[dict]:
    """Shared retrieval logic used by both search_code and search_code_json."""
    embedder = _get_embedder()
    store = _get_store()
    query_vector = embedder.embed_query(query)
    source = (source or "all").lower()

    if mode == "vector":
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        must = []
        must_not = []
        if language:
            must.append(FieldCondition(key="language", match=MatchValue(value=language)))
        if source == "wiki":
            must.append(FieldCondition(key="source", match=MatchValue(value=_WIKI_SOURCE)))
        elif source == "code":
            must_not.append(FieldCondition(key="source", match=MatchValue(value=_WIKI_SOURCE)))
        query_filter = Filter(must=must or None, must_not=must_not or None) if (must or must_not) else None
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
    # Source filter — universal so it also covers hybrid/graph modes (vector mode
    # already narrowed at the Qdrant level above; re-applying here is a no-op).
    if source in ("code", "wiki"):
        want_wiki = source == "wiki"
        results = [r for r in results if _is_wiki(r.get("payload") or {}) == want_wiki]

    return results


def _format_results(results: list[dict], include_wiki: bool = True) -> str:
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

        is_wiki = _is_wiki(payload)
        location = f"{file_path}:{start_line}-{end_line}" if start_line and end_line else file_path
        symbol = func_name or class_name
        header = f"[{i}] [{'wiki' if is_wiki else 'code'}] {location}{f' ({symbol})' if symbol else ''} | score: {score:.4f}"

        parts.append(f"{header}\n```{language}\n{text}\n```")

        if is_wiki:
            # Surface the wiki page's own one-line summary when present.
            summary = (payload.get("summary") or "").strip()
            if summary:
                parts.append(f"↳ 📖 {summary}")
        elif include_wiki:
            # Attach the OKF wiki explanation for this code hit (via the shared graph).
            wc = _wiki_context(file_path, symbol)
            if wc:
                wsum = (wc.get("summary") or "").strip()
                parts.append(f"↳ 📖 wiki: {wc.get('title')}" + (f" — {wsum}" if wsum else ""))

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
    source: str = "all",
    include_wiki: bool = True,
) -> str:
    """Search indexed code using vector embeddings and/or graph relationships.

    Also searches the OKF LLM wiki: human-readable prose explaining each concept,
    stored in the same collection (source="okf_wiki"). Code results are annotated
    with the relevant wiki explanation when one exists.

    Args:
        query: Natural language or code search query (e.g. "how does auth work", "getUserById")
        mode: Retrieval mode — "vector" (semantic similarity), "hybrid" (vector + graph, recommended), "graph" (Neo4j traversal only)
        top_k: Number of code chunks to return (default 10)
        language: Filter by language — "javascript", "typescript", or "tsx"
        file_pattern: Filter by file path glob pattern, e.g. "src/components/*" or "*.service.ts"
        min_score: Minimum similarity score 0.0–1.0 (higher = stricter relevance)
        vector_weight: Weight for vector results in hybrid mode (default 0.7)
        graph_weight: Weight for graph results in hybrid mode (default 0.3)
        source: Which layer to return — "all" (default), "code" (only code chunks), or "wiki" (only OKF wiki prose)
        include_wiki: For code results, attach the related OKF wiki explanation (default True)

    Returns:
        Formatted results tagged [code]/[wiki], with file paths, line numbers, scores, and wiki context
    """
    try:
        results = _retrieve(query, mode, top_k, language, file_pattern, min_score, vector_weight, graph_weight, source)
        return _format_results(results, include_wiki=include_wiki)
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
    source: str = "all",
    include_wiki: bool = True,
) -> str:
    """Search indexed code and return structured JSON results for programmatic use.

    Also searches the OKF LLM wiki (source="okf_wiki") stored in the same collection.
    Each result carries a "source" ("code"|"wiki"); code results include "wiki_context"
    (the related OKF wiki explanation) when one exists.

    Args:
        query: Natural language or code search query (e.g. "how does auth work", "getUserById")
        mode: Retrieval mode — "vector" (semantic similarity), "hybrid" (vector + graph, recommended), "graph" (Neo4j traversal only)
        top_k: Number of code chunks to return (default 10)
        language: Filter by language — "javascript", "typescript", or "tsx"
        file_pattern: Filter by file path glob pattern, e.g. "src/components/*" or "*.service.ts"
        min_score: Minimum similarity score 0.0–1.0 (higher = stricter relevance)
        vector_weight: Weight for vector results in hybrid mode (default 0.7)
        graph_weight: Weight for graph results in hybrid mode (default 0.3)
        source: Which layer to return — "all" (default), "code", or "wiki"
        include_wiki: For code results, include the related OKF wiki explanation (default True)

    Returns:
        JSON string with structured results including file paths, line numbers, code content, metadata, source, and wiki_context
    """
    try:
        results = _retrieve(query, mode, top_k, language, file_pattern, min_score, vector_weight, graph_weight, source)
        structured = []
        for r in results:
            payload = r.get("payload") or {}
            is_wiki = _is_wiki(payload)
            item = {
                "id": str(r.get("id", "")),
                "source": "wiki" if is_wiki else "code",
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
            }
            if is_wiki:
                item["summary"] = payload.get("summary")
                item["term"] = payload.get("term")
            elif include_wiki:
                item["wiki_context"] = _wiki_context(payload.get("file_path", ""), payload.get("function_name") or payload.get("class_name"))
            structured.append(item)
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


def main() -> None:
    """Entry point for `cvg-mcp` — serve the tools over stdio."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
