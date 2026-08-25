"""MCP server exposing code search tools from the code-vector-graph project."""

import fnmatch
import json
import logging
from typing import Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Load .env before importing code_vector_graph.config: config resolves DEFAULT_MODEL_ID (and the
# CVG_* overrides below) from the environment at import time.
load_dotenv()

from code_vector_graph.config import (  # noqa: E402
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USER,
    QDRANT_URL,
    active_collection,
)
from code_vector_graph.embeddings.embedder import create_embedder  # noqa: E402
from code_vector_graph.repos import display_rel_path  # noqa: E402
from code_vector_graph.stores.graph_store import GraphStore  # noqa: E402
from code_vector_graph.retrieval.hybrid import HybridRetriever  # noqa: E402
from code_vector_graph.stores.vector_store import VectorStore  # noqa: E402

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

mcp = FastMCP("code-vector-graph")

# Lazy singletons — model load is expensive, initialize on first use
_embedder = None
_store = None
_graph_store = None


# Which embedding model + Qdrant collection the server reads is resolved by
# `active_collection()` from CVG_MODEL_ID / CVG_COLLECTION_NAME (see config.py), so
# the MCP can point at whatever `cvg-ingest` / run_mac_mps_24gb.sh indexed into.

# OKF wiki prose is stored in the SAME collection as code, tagged source="okf_wiki".
_WIKI_SOURCE = "okf_wiki"


def _get_embedder():
    global _embedder
    if _embedder is None:
        _, _, model_id = active_collection()
        _embedder = create_embedder(model_id=model_id)
    return _embedder


def _get_store():
    global _store
    if _store is None:
        collection_name, dimensions, _ = active_collection()
        _store = VectorStore(
            collection_name=collection_name,
            qdrant_url=QDRANT_URL,
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


def _root_prefixes(repo_roots: Optional[list[str]]) -> list[str]:
    """Normalise repo roots into the ``"<root>/"`` prefixes every file under them starts with."""
    out = []
    for root in repo_roots or []:
        if not root:
            continue
        norm = root.replace("\\", "/").rstrip("/")
        if norm:
            out.append(norm + "/")
    return out


def _matching_root(file_path: str, repo_roots: Optional[list[str]]) -> Optional[str]:
    """The longest entry of ``repo_roots`` that ``file_path`` lives under, else None."""
    fp = (file_path or "").replace("\\", "/")
    best = None
    for prefix in _root_prefixes(repo_roots):
        if fp.startswith(prefix) and (best is None or len(prefix) > len(best)):
            best = prefix
    return best[:-1] if best else None


def _repo_matches(
    payload: dict,
    repos: Optional[list[str]] = None,
    repo_roots: Optional[list[str]] = None,
) -> bool:
    """Is this result inside the requested application scope?

    Two kinds of indexed data coexist:

    * **recorded** — the ingest pipeline / backfill stamped ``repo`` into the payload,
      so an exact name match against ``repos`` decides membership.
    * **legacy** — no ``repo`` was recorded; identity is only implied by the
      ``file_path`` prefix, hence the caller also supplies ``repo_roots``.

    OKF wiki chunks are the exception: their ``file_path`` is *repo-relative*
    (see ``ingestion/okf/sync.py``), so a root-prefix test can never match one. A
    wiki payload with no recorded ``repo`` therefore carries no usable identity —
    we keep it instead of silently dropping the entire wiki layer for legacy
    bundles (``api/routers/search.py::_in_scope`` treats an unknown wiki repo as
    in-scope for the same reason).
    """
    if not repos and not repo_roots:
        return True  # no scope requested
    payload = payload or {}
    recorded = payload.get("repo")
    if recorded:
        if repos:
            return recorded in repos
        # Only roots were supplied — fall through to the prefix test below.
    elif _is_wiki(payload):
        return True
    prefixes = _root_prefixes(repo_roots)
    if not prefixes:
        return False
    # Qdrant payloads and Chunk nodes key the path as `file_path`; File/WikiPage
    # graph nodes call it `path` (see stores/graph_schema.py) — accept either.
    file_path = (payload.get("file_path") or payload.get("path") or "").replace("\\", "/")
    if not file_path:
        return False
    return any(file_path.startswith(prefix) for prefix in prefixes)


def _wiki_context(
    file_path: str,
    symbol: str,
    repo: Optional[str] = None,
    rel_path: Optional[str] = None,
) -> Optional[dict]:
    """Best-effort OKF wiki explanation for a code hit, via the shared Neo4j graph.

    Code chunks carry no graph node id, so we join by path. A WikiPage's `resource`
    is repo-relative: it either equals the hit's own `rel_path` (exact, preferred)
    or is a suffix of the hit's absolute file_path. `repo` narrows the join to pages
    from the same repository — pages synced before repo identity was recorded have
    `repo IS NULL` and stay eligible. Prefer a page whose title matches the hit's
    symbol (function/class), else the File-level page. Returns None (silently) if
    Neo4j is unreachable or nothing matches — never fatal.
    """
    if not file_path:
        return None
    try:
        graph_store = _get_graph_store()
        cypher = (
            "MATCH (w:WikiPage) "
            "WHERE w.resource <> '' "
            "AND ($repo IS NULL OR w.repo IS NULL OR w.repo = $repo) "
            "AND (($rel <> '' AND split(w.resource, '#')[0] = $rel) "
            "     OR $fp ENDS WITH ('/' + split(w.resource, '#')[0])) "
            "RETURN w.title AS title, w.summary AS summary, w.type AS type, w.path AS path "
            "ORDER BY CASE WHEN $sym <> '' AND w.title = $sym THEN 0 "
            "              WHEN w.type = 'File' THEN 1 ELSE 2 END "
            "LIMIT 1"
        )
        raw = graph_store.query_graph(
            cypher,
            {"fp": file_path, "sym": symbol or "", "repo": repo or None, "rel": rel_path or ""},
        )
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
    repos: Optional[list[str]] = None,
    repo_roots: Optional[list[str]] = None,
) -> list[dict]:
    """Shared retrieval logic used by both search_code and search_code_json.

    Application scoping (`repos` / `repo_roots`) comes in two flavours:

    * every repo in the scope has its identity **recorded** in the index — the
      caller then passes `repos` only, and we push a `repo MatchAny` down into
      Qdrant / Neo4j, which is exact and index friendly;
    * at least one repo is **legacy** (indexed before `repo` was recorded) — the
      caller passes `repo_roots` too. A hard `repo` filter would drop every legacy
      point, so instead we over-fetch (`top_k * 3`) and post-filter on the
      `file_path` prefix via `_repo_matches`, trimming back to `top_k` at the end.
    """
    embedder = _get_embedder()
    store = _get_store()
    query_vector = embedder.embed_query(query)
    source = (source or "all").lower()

    repos = [r for r in (repos or []) if r] or None
    prefixes = _root_prefixes(repo_roots)
    scoped = bool(repos or prefixes)
    # Roots present => legacy data may be in scope => post-filter instead of hard filter.
    fetch_k = max(1, top_k * 3) if prefixes else top_k

    if mode == "vector":
        from qdrant_client.models import FieldCondition, Filter, MatchAny, MatchValue

        must = []
        must_not = []
        if language:
            must.append(FieldCondition(key="language", match=MatchValue(value=language)))
        if source == "wiki":
            must.append(FieldCondition(key="source", match=MatchValue(value=_WIKI_SOURCE)))
        elif source == "code":
            must_not.append(FieldCondition(key="source", match=MatchValue(value=_WIKI_SOURCE)))
        if repos and not prefixes:
            must.append(FieldCondition(key="repo", match=MatchAny(any=repos)))
        query_filter = Filter(must=must or None, must_not=must_not or None) if (must or must_not) else None
        raw = store.search(query_vector, top_k=fetch_k, query_filter=query_filter)
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
            "WHERE (toLower(n.name) CONTAINS toLower($query) "
            "   OR toLower(n.path) CONTAINS toLower($query)) "
            "AND ($repos IS NULL OR n.repo IN $repos "
            "     OR any(p IN $root_prefixes WHERE n.path STARTS WITH p) "
            "     OR EXISTS { MATCH (f:File)-[:CONTAINS|DEFINES]->(n) "
            "                 WHERE f.repo IN $repos "
            "                    OR any(p IN $root_prefixes WHERE f.path STARTS WITH p) }) "
            "RETURN n.id AS id, n AS node, 1.0 AS score "
            "LIMIT $limit"
        )
        raw = graph_store.query_graph(
            cypher,
            {
                "query": query,
                "limit": fetch_k,
                # None disables the scope branch entirely; [] would only match nothing.
                "repos": (repos or []) if scoped else None,
                "root_prefixes": prefixes,
            },
        )
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
        from qdrant_client.models import FieldCondition, Filter, MatchAny

        query_filter = None
        if repos and not prefixes:
            query_filter = Filter(must=[FieldCondition(key="repo", match=MatchAny(any=repos))])
        graph_store = _get_graph_store()
        retriever = HybridRetriever(store, graph_store, embedder)
        results = retriever.search(
            query,
            mode="hybrid",
            top_k=fetch_k,
            vector_weight=vector_weight,
            graph_weight=graph_weight,
            query_vec=query_vector,
            query_filter=query_filter,
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
    # Repo scope — a no-op for recorded-only scopes (already filtered in the store),
    # the actual filter for legacy data that was deliberately over-fetched above.
    if scoped:
        results = [r for r in results if _repo_matches(r.get("payload") or {}, repos, repo_roots)]

    if len(results) > top_k:
        results = results[:top_k]
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
            wc = _wiki_context(file_path, symbol, payload.get("repo"), payload.get("rel_path"))
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
    repos: Optional[list[str]] = None,
    repo_roots: Optional[list[str]] = None,
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
        repos: Restrict results to these repositories (application scoping) — the repository
            names recorded in the index, e.g. ["backend_nodejs_global_tnlm"]
        repo_roots: Absolute path prefixes of the same repositories, needed for repositories
            indexed before repo identity was recorded. Pass both when the dashboard supplies them.

    Returns:
        Formatted results tagged [code]/[wiki], with file paths, line numbers, scores, and wiki context
    """
    try:
        results = _retrieve(
            query, mode, top_k, language, file_pattern, min_score, vector_weight, graph_weight,
            source, repos=repos, repo_roots=repo_roots,
        )
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
    repos: Optional[list[str]] = None,
    repo_roots: Optional[list[str]] = None,
) -> str:
    """Search indexed code and return structured JSON results for programmatic use.

    Also searches the OKF LLM wiki (source="okf_wiki") stored in the same collection.
    Each result carries a "source" ("code"|"wiki"); code results include "wiki_context"
    (the related OKF wiki explanation) when one exists. Every result also carries the
    repository it belongs to ("repo"/"app"/"rel_path") when that is known.

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
        repos: Restrict results to these repositories (application scoping) — the repository
            names recorded in the index, e.g. ["backend_nodejs_global_tnlm"]
        repo_roots: Absolute path prefixes of the same repositories, needed for repositories
            indexed before repo identity was recorded. Pass both when the dashboard supplies them.

    Returns:
        JSON string with structured results including file paths, line numbers, code content, metadata, source, repo/app/rel_path, and wiki_context
    """
    try:
        results = _retrieve(
            query, mode, top_k, language, file_pattern, min_score, vector_weight, graph_weight,
            source, repos=repos, repo_roots=repo_roots,
        )
        structured = []
        for r in results:
            payload = r.get("payload") or {}
            is_wiki = _is_wiki(payload)
            file_path = payload.get("file_path", "")
            # Legacy points carry no rel_path: derive it from whichever scoped root
            # prefixes this hit (None when unscoped -> rel_path falls back to file_path).
            rel_path = display_rel_path(
                file_path, _matching_root(file_path, repo_roots), payload.get("rel_path")
            )
            item = {
                "id": str(r.get("id", "")),
                "source": "wiki" if is_wiki else "code",
                "score": round(float(r.get("score", 0.0)), 4),
                "file_path": file_path,
                "repo": payload.get("repo"),
                "app": payload.get("app"),
                "rel_path": rel_path,
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
                item["concept_id"] = payload.get("symbol_id")
            elif include_wiki:
                item["wiki_context"] = _wiki_context(
                    file_path,
                    payload.get("function_name") or payload.get("class_name"),
                    payload.get("repo"),
                    rel_path,
                )
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
        lines.append(f"Qdrant ({QDRANT_URL}, collection={store.collection_name}): {'OK' if ok else 'FAIL'}")
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
