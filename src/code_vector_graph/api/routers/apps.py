"""Application-centric endpoints: list apps, per-app summary, file tree, file detail, wiki.

All identity comes from :class:`ApplicationRegistry` (recorded Application/Repository
nodes ∪ repos derived from legacy file paths). Every Cypher predicate is built from
:class:`AppScope` so recorded (``repo`` equality) and derived (path prefix) data are
handled the same way.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

from code_vector_graph.api.config import QDRANT_COLLECTION
from code_vector_graph.api.deps import get_graph, get_qdrant, get_registry
from code_vector_graph.api.serialize import (
    node_id,
    node_label,
    node_props,
    record_get,
    records_of,
    scalar,
)
from code_vector_graph.api.services.apps import (
    WIKI_SOURCE,
    ApplicationRegistry,
    AppScope,
    FileEntry,
    RepoInfo,
)

router = APIRouter(prefix="/apps")
logger = logging.getLogger(__name__)

# labels(s)[0] -> counts key
_SYMBOL_COUNT_KEYS = {
    "Function": "functions",
    "Method": "methods",
    "Class": "classes",
    "Interface": "interfaces",
    "TypeAlias": "type_aliases",
    "Variable": "variables",
    "Import": "imports",
    "Field": "fields",
}
_WIKI_ORDER = "CASE w.type WHEN 'Repository' THEN 0 WHEN 'File' THEN 1 WHEN 'Class' THEN 2 ELSE 3 END"
_WIKI_LIST_RETURN = (
    "RETURN w.concept_id AS concept_id, w.title AS title, w.type AS type, "
    "w.summary AS summary, w.repo AS repo, w.path AS path, w.resource AS resource"
)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _scope_or_404(registry: ApplicationRegistry, app: str, repo: str | None = None) -> AppScope:
    try:
        return registry.scope(app, repo or None)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


def _query(graph, cypher: str, params: dict | None = None, *, what: str) -> list:
    """Run a read query; on failure log and return [] so one bad leg never 500s a page."""
    try:
        return records_of(graph.query_graph(cypher, params or {}))
    except Exception:
        logger.warning("%s query failed", what, exc_info=True)
        return []


def _count(graph, cypher: str, params: dict, *, what: str) -> int:
    try:
        return int(scalar(graph.query_graph(cypher, params), "n", 0) or 0)
    except Exception:
        logger.warning("%s count failed", what, exc_info=True)
        return 0


def _symbol_counts(graph, scope: AppScope) -> dict[str, int]:
    where, params = scope.cypher_file_where("f")
    counts = {k: 0 for k in _SYMBOL_COUNT_KEYS.values()}
    for rec in _query(
        graph,
        f"MATCH (f:File) WHERE {where} MATCH (f)-[:DEFINES]->(s) "
        "RETURN labels(s)[0] AS label, count(DISTINCT s) AS n",
        params,
        what="symbol counts",
    ):
        label = record_get(rec, "label")
        if not label:
            continue
        key = _SYMBOL_COUNT_KEYS.get(label, str(label).lower())
        counts[key] = counts.get(key, 0) + int(record_get(rec, "n") or 0)
    return counts


def _glossary_count(graph, scope: AppScope) -> int:
    _, params = scope.cypher_file_where("f")
    return _count(
        graph,
        "MATCH (g:GlossaryEntry) WHERE g.repo IN $repos "
        "OR any(p IN $roots WHERE g.file_path STARTS WITH p) RETURN count(g) AS n",
        params,
        what="glossary",
    )


def _wiki_row(rec) -> dict[str, Any]:
    return {
        "concept_id": record_get(rec, "concept_id"),
        "title": record_get(rec, "title"),
        "type": record_get(rec, "type"),
        "summary": record_get(rec, "summary"),
        "repo": record_get(rec, "repo"),
        "path": record_get(rec, "path"),
        "resource": record_get(rec, "resource"),
    }


def _top_modules(files: list[FileEntry], limit: int = 10) -> list[dict[str, Any]]:
    mods: dict[str, dict[str, int]] = {}
    for f in files:
        rel = f.rel_path.replace("\\", "/")
        top = rel.split("/", 1)[0] if "/" in rel else "."
        m = mods.setdefault(top, {"file_count": 0, "chunk_count": 0})
        m["file_count"] += 1
        m["chunk_count"] += f.chunk_count
    rows = [{"path": k, **v} for k, v in mods.items()]
    rows.sort(key=lambda r: (-r["file_count"], r["path"]))
    return rows[:limit]


def _fallback_overview(repo: RepoInfo, counts: dict[str, int]) -> dict[str, Any]:
    langs = ", ".join(repo.languages) if repo.languages else "no languages recorded"
    summary = (
        f"{repo.file_count} files · {langs} · "
        f"{counts.get('functions', 0)} functions, {counts.get('classes', 0)} classes"
    )
    return {
        "title": repo.name,
        "summary": summary,
        "overview": "",
        "how_it_works": "",
        "source": "fallback",
        "hint": f"cvg-okf-build --repo-path {repo.root} --app-name {repo.app} && cvg-okf-sync",
    }


def _repo_overview(graph, repo: RepoInfo, counts: dict[str, int]) -> dict[str, Any]:
    recs = _query(
        graph,
        "MATCH (w:WikiPage {type:'Repository'}) WHERE w.repo = $repo RETURN w LIMIT 1",
        {"repo": repo.name},
        what="repo overview",
    )
    for rec in recs:
        props = node_props(record_get(rec, "w"))
        if props:
            return {
                "title": props.get("title") or repo.name,
                "summary": props.get("summary") or "",
                "overview": props.get("overview") or "",
                "how_it_works": props.get("how_it_works") or "",
                "source": "wiki",
                "concept_id": props.get("concept_id"),
            }
    return _fallback_overview(repo, counts)


# --------------------------------------------------------------------------- #
# endpoints
# --------------------------------------------------------------------------- #


@router.get("")
def list_apps(refresh: bool = False, registry: ApplicationRegistry = Depends(get_registry)):
    apps = registry.list(refresh=refresh)
    return {"apps": [a.model_dump() for a in apps], "cached_at": registry.cached_at}


@router.post("/refresh")
def refresh_apps(registry: ApplicationRegistry = Depends(get_registry)):
    apps = registry.list(refresh=True)
    return {"apps": [a.model_dump() for a in apps], "cached_at": registry.cached_at}


@router.get("/{app}")
def app_detail(
    app: str,
    registry: ApplicationRegistry = Depends(get_registry),
    graph=Depends(get_graph),
):
    scope = _scope_or_404(registry, app)
    info = registry.get(app)

    counts = _symbol_counts(graph, scope)
    counts.update(
        files=info.file_count,
        chunks=info.chunk_count,
        wiki_pages=info.wiki_pages,
        glossary=_glossary_count(graph, scope),
    )

    repos_out = []
    for repo in info.repos:
        rscope = scope.for_repo(repo.name)
        rcounts = _symbol_counts(graph, rscope)
        rcounts.update(files=repo.file_count, chunks=repo.chunk_count, wiki_pages=repo.wiki_pages)
        try:
            files = registry.files(app, repo.name)
        except Exception:
            logger.warning("files(%s/%s) failed", app, repo.name, exc_info=True)
            files = []
        repos_out.append(
            {
                **repo.model_dump(),
                "counts": rcounts,
                "top_modules": _top_modules(files),
                "overview": _repo_overview(graph, repo, rcounts),
            }
        )

    wwhere, wparams = scope.cypher_wiki_where("w")
    wiki_top = [
        _wiki_row(rec)
        for rec in _query(
            graph,
            f"MATCH (w:WikiPage) WHERE {wwhere} {_WIKI_LIST_RETURN} ORDER BY {_WIKI_ORDER}, w.title LIMIT 12",
            wparams,
            what="wiki_top",
        )
    ]

    return {
        "app": info.model_dump(),
        "counts": counts,
        "languages": info.languages,
        "repos": repos_out,
        "wiki_top": wiki_top,
    }


def _norm_dir(path: str | None) -> str:
    return "/".join(p for p in (path or "").replace("\\", "/").split("/") if p and p != ".")


@router.get("/{app}/tree")
def app_tree(
    app: str,
    repo: str = Query(default=""),
    path: str = Query(default=""),
    registry: ApplicationRegistry = Depends(get_registry),
):
    scope = _scope_or_404(registry, app)
    if not repo:
        return {
            "kind": "repos",
            "app": app,
            "repos": [
                {"name": r.name, "root": r.root, "file_count": r.file_count, "source": r.source}
                for r in scope.repos
            ],
        }
    rscope = _scope_or_404(registry, app, repo)
    files = registry.files(app, repo)
    path = _norm_dir(path)
    prefix = path + "/" if path else ""

    dirs: dict[str, int] = {}
    out_files: list[dict[str, Any]] = []
    for f in files:
        rel = f.rel_path.replace("\\", "/")
        if prefix and not rel.startswith(prefix):
            continue
        rest = rel[len(prefix):]
        if not rest:
            continue
        head, sep, _tail = rest.partition("/")
        if sep:
            dirs[head] = dirs.get(head, 0) + 1
        else:
            out_files.append(
                {
                    "name": head,
                    "path": rel,
                    "abs_path": f.path,
                    "language": f.language,
                    "file_id": f.id,
                    "line_count": f.line_count,
                    "chunk_count": f.chunk_count,
                }
            )
    if path and not dirs and not out_files:
        raise HTTPException(status_code=404, detail=f"No such directory '{path}' in {rscope.label}")
    return {
        "kind": "dir",
        "app": app,
        "repo": repo,
        "path": path,
        "dirs": [
            {"name": n, "path": f"{prefix}{n}", "file_count": c}
            for n, c in sorted(dirs.items())
        ],
        "files": sorted(out_files, key=lambda x: x["name"]),
    }


def _scroll_chunks(qdrant: QdrantClient, file_path: str) -> list[dict[str, Any]] | None:
    """Code chunks for a file from Qdrant (None on failure so the caller can fall back)."""
    try:
        points, _ = qdrant.scroll(
            collection_name=QDRANT_COLLECTION,
            limit=500,
            scroll_filter=Filter(
                must=[FieldCondition(key="file_path", match=MatchValue(value=file_path))],
                must_not=[FieldCondition(key="source", match=MatchValue(value=WIKI_SOURCE))],
            ),
            with_payload=[
                "chunk_index", "start_line", "end_line", "function_name", "class_name",
                "node_type", "text_content", "language", "token_count", "symbols_defined",
            ],
            with_vectors=False,
        )
    except Exception:
        logger.debug("Qdrant scroll for %s failed", file_path, exc_info=True)
        return None
    chunks = []
    for p in points:
        payload = p.payload or {}
        chunks.append(
            {
                "id": str(p.id),
                "chunk_index": payload.get("chunk_index"),
                "start_line": payload.get("start_line"),
                "end_line": payload.get("end_line"),
                "function_name": payload.get("function_name"),
                "class_name": payload.get("class_name"),
                "node_type": payload.get("node_type"),
                "text_content": payload.get("text_content", ""),
                "language": payload.get("language"),
                "token_count": payload.get("token_count"),
                "symbols_defined": payload.get("symbols_defined") or [],
                "source": "qdrant",
            }
        )
    chunks.sort(key=lambda c: (c["chunk_index"] is None, c["chunk_index"] or 0, c["start_line"] or 0))
    return chunks


def _graph_chunks(graph, file_id: str) -> list[dict[str, Any]]:
    out = []
    for rec in _query(
        graph,
        "MATCH (f:File {id: $fid})-[:CONTAINS]->(c:Chunk) RETURN c ORDER BY c.chunk_index, c.start_line",
        {"fid": file_id},
        what="graph chunks",
    ):
        props = node_props(record_get(rec, "c"))
        if props:
            out.append({**props, "id": props.get("id"), "source": "graph"})
    return out


@router.get("/{app}/files/{repo}/{file_path:path}")
def app_file(
    app: str,
    repo: str,
    file_path: str,
    registry: ApplicationRegistry = Depends(get_registry),
    graph=Depends(get_graph),
    qdrant: QdrantClient = Depends(get_qdrant),
):
    scope = _scope_or_404(registry, app, repo)
    rinfo = scope.repos[0]
    rel = _norm_dir(file_path)
    if not rel:
        raise HTTPException(status_code=404, detail="Empty file path")
    where, params = scope.cypher_file_where("f")
    params.update(rel=rel, abs=f"{rinfo.norm_root}/{rel}", slash_rel=f"/{rel}")
    try:
        recs = records_of(
            graph.query_graph(
                f"MATCH (f:File) WHERE {where} "
                "AND (f.rel_path = $rel OR f.path = $abs OR f.path ENDS WITH $slash_rel) "
                "RETURN f LIMIT 1",
                params,
            )
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    fnode = record_get(recs[0], "f") if recs else None
    props = node_props(fnode)
    if not props:
        raise HTTPException(status_code=404, detail=f"File '{rel}' not found in {scope.label}")

    fid = node_id(fnode)
    fpath = props.get("path") or params["abs"]
    file_out = {
        "id": fid,
        "path": fpath,
        "rel_path": rinfo.rel_path(fpath, props.get("rel_path")),
        "repo": rinfo.name,
        "app": scope.app,
        "language": props.get("language"),
        "line_count": props.get("line_count"),
        "exports": props.get("exports") or [],
        "imports": props.get("imports") or [],
    }

    symbols = []
    if fid:
        for rec in _query(
            graph,
            "MATCH (f:File {id: $fid})-[:DEFINES]->(s) WHERE NOT s:Chunk "
            "OPTIONAL MATCH (w:WikiPage)-[:DOCUMENTS]->(s) "
            "RETURN s, labels(s)[0] AS label, w ORDER BY s.start_line",
            {"fid": fid},
            what="symbols",
        ):
            s = record_get(rec, "s")
            sp = node_props(s)
            if not sp:
                continue
            w = node_props(record_get(rec, "w"))
            symbols.append(
                {
                    "id": node_id(s),
                    "label": record_get(rec, "label") or node_label(s),
                    "name": sp.get("name"),
                    "start_line": sp.get("start_line"),
                    "end_line": sp.get("end_line"),
                    "is_exported": sp.get("is_exported"),
                    "wiki": (
                        {
                            "concept_id": w.get("concept_id"),
                            "title": w.get("title"),
                            "summary": w.get("summary"),
                            "type": w.get("type"),
                        }
                        if w
                        else None
                    ),
                }
            )

    chunks = _scroll_chunks(qdrant, fpath)
    if not chunks and fid:
        chunks = _graph_chunks(graph, fid)

    wiki = []
    glossary = []
    if fid:
        wiki = [
            {**node_props(record_get(rec, "w")), "id": node_id(record_get(rec, "w"))}
            for rec in _query(
                graph,
                "MATCH (w:WikiPage)-[:DOCUMENTS]->(f:File {id: $fid}) RETURN w",
                {"fid": fid},
                what="file wiki",
            )
            if node_props(record_get(rec, "w"))
        ]
    glossary = [
        node_props(record_get(rec, "g"))
        for rec in _query(
            graph,
            "MATCH (g:GlossaryEntry {file_path: $path}) RETURN g ORDER BY g.term",
            {"path": fpath},
            what="file glossary",
        )
        if node_props(record_get(rec, "g"))
    ]

    return {"file": file_out, "symbols": symbols, "chunks": chunks or [], "wiki": wiki, "glossary": glossary}


@router.get("/{app}/wiki")
def app_wiki(
    app: str,
    repo: str = Query(default=""),
    type: str = Query(default=""),
    q: str = Query(default=""),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    registry: ApplicationRegistry = Depends(get_registry),
    graph=Depends(get_graph),
):
    scope = _scope_or_404(registry, app, repo)
    where, params = scope.cypher_wiki_where("w")
    params.update(type=type or None, q=(q or "").strip().lower() or None, limit=limit, offset=offset)
    filters = (
        f"{where} AND ($type IS NULL OR w.type = $type) "
        "AND ($q IS NULL OR toLower(coalesce(w.title,'')) CONTAINS $q "
        "OR toLower(coalesce(w.summary,'')) CONTAINS $q)"
    )
    total = _count(graph, f"MATCH (w:WikiPage) WHERE {filters} RETURN count(w) AS n", params, what="wiki total")
    pages = [
        _wiki_row(rec)
        for rec in _query(
            graph,
            f"MATCH (w:WikiPage) WHERE {filters} {_WIKI_LIST_RETURN} "
            f"ORDER BY {_WIKI_ORDER}, w.title SKIP $offset LIMIT $limit",
            params,
            what="wiki pages",
        )
    ]
    return {"pages": pages, "total": total, "limit": limit, "offset": offset, "scope": scope.label}


@router.get("/{app}/wiki/{concept_id}")
def app_wiki_page(
    app: str,
    concept_id: str,
    registry: ApplicationRegistry = Depends(get_registry),
    graph=Depends(get_graph),
):
    _scope_or_404(registry, app)
    try:
        recs = records_of(
            graph.query_graph(
                "MATCH (w:WikiPage) WHERE w.concept_id = $cid OR w.id = $cid "
                "OPTIONAL MATCH (w)-[:DOCUMENTS]->(n) "
                "OPTIONAL MATCH (n)<-[:CONTAINS|DEFINES]-(pf:File) "
                "RETURN w, n, labels(n)[0] AS label, "
                "CASE WHEN n:File THEN n.path ELSE pf.path END AS file_path LIMIT 1",
                {"cid": concept_id},
            )
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    if not recs or not node_props(record_get(recs[0], "w")):
        raise HTTPException(status_code=404, detail=f"Wiki page '{concept_id}' not found")
    rec = recs[0]
    page = node_props(record_get(rec, "w"))
    page.setdefault("id", node_id(record_get(rec, "w")))
    n = record_get(rec, "n")
    documents = None
    if node_props(n):
        np_ = node_props(n)
        documents = {
            "id": node_id(n),
            "label": record_get(rec, "label") or node_label(n),
            "name": np_.get("name") or np_.get("path") or np_.get("title"),
            "file_path": record_get(rec, "file_path"),
        }

    def _related(direction: str) -> list[dict[str, Any]]:
        pattern = "(w)-[:REFERENCES]->(o:WikiPage)" if direction == "out" else "(w)<-[:REFERENCES]-(o:WikiPage)"
        return [
            {
                "concept_id": record_get(r, "concept_id"),
                "title": record_get(r, "title"),
                "type": record_get(r, "type"),
                "summary": record_get(r, "summary"),
                "repo": record_get(r, "repo"),
            }
            for r in _query(
                graph,
                f"MATCH (w:WikiPage) WHERE w.concept_id = $cid OR w.id = $cid MATCH {pattern} "
                "RETURN o.concept_id AS concept_id, o.title AS title, o.type AS type, "
                "o.summary AS summary, o.repo AS repo ORDER BY o.title LIMIT 50",
                {"cid": concept_id},
                what=f"wiki references {direction}",
            )
        ]

    return {
        "page": page,
        "documents": documents,
        "references": _related("out"),
        "referenced_by": _related("in"),
    }
