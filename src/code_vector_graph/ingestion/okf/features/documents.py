"""Neo4j/Qdrant IO for human-authored Document pages.

A Document is a ``WikiPage {type:"Document"}`` created directly by a person
via the dashboard (not by the feature-mapper LLM pipeline). It mirrors the
Feature-page IO in `store.py`, but:

* it is never touched by `features/build.py` (which only loads/reaps
  ``type:'Feature'`` pages), so it needs no members_hash/stale machinery;
* its scope edge is ``DOCUMENTS -> Repository`` (repo chosen) or
  ``DOCUMENTS -> Application`` (app-level, ``repo`` is ``None``);
* it additionally links ``MENTIONS -> File`` for every file path the body
  names in backticks or link targets — auto-detected, not curated.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Callable

from code_vector_graph.api.serialize import node_props, record_get, records_of
from code_vector_graph.ingestion.okf.features.models import DocumentFrontmatter, DocumentPage
from code_vector_graph.ingestion.okf.features.store import NAMESPACE, _chunks_for
from code_vector_graph.ingestion.okf.sync import wiki_id

logger = logging.getLogger(__name__)

MAX_MENTION_TOKENS = 200

# Inline code spans (`path/to/file.py`) and Markdown link targets ([text](path)).
_INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")
_LINK_TARGET_RE = re.compile(r"\]\(([^)\s]+)\)")
_FENCE_RE = re.compile(r"^\s*```")
# A candidate token looks like a path: has a '/' or a code-ish extension.
_CODE_EXT_RE = re.compile(
    r"\.(py|js|jsx|ts|tsx|mjs|cjs|svelte|vue|java|kt|go|rs|rb|php|c|cc|cpp|h|hpp|cs|swift|"
    r"sql|sh|yaml|yml|json|toml|md|txt|html|css|scss)$",
    re.IGNORECASE,
)
_TRAILING_LOCATION_RE = re.compile(r"(:\d+(-\d+)?|#\S*)$")


def slugify(title: str, max_len: int = 80) -> str:
    """Lowercase, ``[^a-z0-9]+`` -> single ``-``, trimmed; a safe fallback
    when the title has no alphanumeric characters at all."""
    base = re.sub(r"[^a-z0-9]+", "-", (title or "").strip().lower()).strip("-")
    base = base[:max_len].strip("-")
    return base or "document"


def document_id_for(app: str, repo: str | None, slug: str) -> str:
    """Stable id for a document, scoped to app+repo (or app-level when
    ``repo`` is ``None``) so two repos of the same app never collide on the
    same slug."""
    return str(uuid.uuid5(NAMESPACE, f"document:{app}:{repo or ''}:{slug}"))


def existing_document_slugs(graph_store, app: str, repo: str | None) -> set[str]:
    result = graph_store.query_graph(
        "MATCH (w:WikiPage {type:'Document'}) WHERE w.app = $app AND coalesce(w.repo, '') = $repo "
        "RETURN w.slug AS slug",
        {"app": app, "repo": repo or ""},
    )
    return {record_get(rec, "slug") for rec in records_of(result) if record_get(rec, "slug")}


def unique_slug(base: str, taken: set[str]) -> str:
    if base not in taken:
        return base
    i = 2
    while f"{base}-{i}" in taken:
        i += 1
    return f"{base}-{i}"


def word_count(body: str) -> int:
    return len(re.findall(r"\S+", body or ""))


def extract_mentioned_paths(body: str) -> list[str]:
    """File-path-like tokens named in inline code spans or link targets,
    outside fenced code blocks. Order-preserving, deduplicated, capped."""
    lines = (body or "").replace("\r\n", "\n").replace("\r", "\n").splitlines()
    candidates: list[str] = []
    in_fence = False
    for line in lines:
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        candidates.extend(_INLINE_CODE_RE.findall(line))
        candidates.extend(_LINK_TARGET_RE.findall(line))

    seen: set[str] = set()
    out: list[str] = []
    for raw in candidates:
        token = raw.strip()
        if not token or token.startswith(("http://", "https://", "mailto:")):
            continue
        token = _TRAILING_LOCATION_RE.sub("", token).strip()
        if token.startswith("./"):
            token = token[2:]
        token = token.lstrip("/")
        if not token or " " in token:
            continue
        if "/" not in token and not _CODE_EXT_RE.search(token):
            continue
        if token in seen:
            continue
        seen.add(token)
        out.append(token)
        if len(out) >= MAX_MENTION_TOKENS:
            break
    return out


def resolve_mentions(graph_store, scope, tokens: list[str]) -> list[dict]:
    """Resolve mentioned path tokens against `File` nodes in ``scope``.

    Returns ``[{id, path, rel_path, repo, token}]`` — one row per token that
    matched a File (a token matching several files resolves to just one, via
    ``collect(...)[0]``, to keep the edge count bounded to the token count).
    """
    if not tokens:
        return []
    fwhere, params = scope.cypher_file_where("f")
    params = dict(params)
    params["paths"] = tokens
    result = graph_store.query_graph(
        f"MATCH (f:File) WHERE {fwhere} "
        "UNWIND $paths AS token "
        "WITH token, f WHERE f.rel_path = token OR f.path = token OR f.path ENDS WITH ('/' + token) "
        "WITH token, collect(f)[0] AS f "
        "RETURN f.id AS id, f.path AS path, f.rel_path AS rel_path, f.repo AS repo, token AS token",
        params,
    )
    return [
        {
            "id": record_get(rec, "id"),
            "path": record_get(rec, "path"),
            "rel_path": record_get(rec, "rel_path"),
            "repo": record_get(rec, "repo"),
            "token": record_get(rec, "token"),
        }
        for rec in records_of(result)
        if record_get(rec, "id")
    ]


def build_document_graph(
    page: DocumentPage,
    mentions: list[dict],
    *,
    target_id: str,
    target_label: str,
) -> tuple[list[dict], list[dict], dict[str, str]]:
    """WikiPage node for ``page``, plus its ``DOCUMENTS`` (page -> target) and
    ``MENTIONS`` (page -> mentioned File) edges."""
    fm = page.fm
    wid = wiki_id(fm.doc_id)
    node_labels: dict[str, str] = {wid: "WikiPage", target_id: target_label}

    node = {
        "label": "WikiPage",
        "id": wid,
        "properties": {
            "concept_id": fm.doc_id,
            "path": f"document/{fm.slug}",
            "type": "Document",
            "title": fm.title,
            "summary": fm.description,
            "overview": fm.description,
            "tags": list(fm.tags),
            "resource": "",
            "source": fm.source,
            "repo": fm.repo,
            "app": fm.app,
            "how_it_works": None,
            "slug": fm.slug,
            "content": page.body,
            "kind": None,
            "members_hash": None,
            "edited_members_hash": None,
            "member_files": [],
            "member_count": 0,
            "stale": False,
            "stale_since": None,
            "generated_at": None,
            "edited_at": fm.edited_at,
            "model": None,
            "language": fm.language,
            "draft": None,
            "draft_generated_at": None,
            "needs_reembed": fm.needs_reembed,
            "category": fm.category,
            "created_at": fm.created_at,
            "word_count": fm.word_count,
            "source_file": fm.source_file,
            "mentions": [m.get("rel_path") or m.get("path") or m["token"] for m in mentions],
        },
    }

    rels = [{"type": "DOCUMENTS", "source_id": wid, "target_id": target_id, "properties": {}}]
    for m in mentions:
        node_labels.setdefault(m["id"], "File")
        rels.append({"type": "MENTIONS", "source_id": wid, "target_id": m["id"], "properties": {"path": m["token"]}})

    return [node], rels, node_labels


def sync_document_neo4j(
    page: DocumentPage,
    mentions: list[dict],
    *,
    target_id: str,
    target_label: str,
    graph_store,
) -> dict:
    """Upsert a Document's WikiPage node + edges. Clears its old `MENTIONS`
    edges first, so a re-index whose body dropped a reference doesn't keep a
    stale edge to it."""
    nodes, rels, node_labels = build_document_graph(page, mentions, target_id=target_id, target_label=target_label)
    graph_store.create_constraints()
    wid = wiki_id(page.fm.doc_id)
    graph_store.query_graph("MATCH (w:WikiPage {id:$wid})-[r:MENTIONS]->() DELETE r", {"wid": wid})
    node_counts = graph_store.upsert_nodes(nodes)
    rel_counts = graph_store.upsert_relationships(rels, node_labels=node_labels)
    return {
        "wiki_pages": len(nodes),
        "mentions_edges": sum(1 for r in rels if r["type"] == "MENTIONS"),
        "nodes_created": node_counts.get("nodes_created", 0),
        "relationships_created": rel_counts.get("relationships_created", 0),
    }


def set_mentions(graph_store, doc_id: str, mentions: list[dict]) -> int:
    """Replace a Document's `MENTIONS` edges and its denormalized `mentions`
    property list (used by PUT/reindex, which re-link separately from the
    initial create so a body-only edit still refreshes stale references)."""
    wid = wiki_id(doc_id)
    graph_store.query_graph("MATCH (w:WikiPage {id:$wid})-[r:MENTIONS]->() DELETE r", {"wid": wid})
    paths = [m.get("rel_path") or m.get("path") or m["token"] for m in mentions]
    graph_store.query_graph("MATCH (w:WikiPage {id:$wid}) SET w.mentions = $paths", {"wid": wid, "paths": paths})
    if mentions:
        node_labels = {wid: "WikiPage", **{m["id"]: "File" for m in mentions}}
        rels = [{"type": "MENTIONS", "source_id": wid, "target_id": m["id"], "properties": {"path": m["token"]}} for m in mentions]
        graph_store.upsert_relationships(rels, node_labels=node_labels)
    return len(mentions)


def save_document_page(
    graph_store,
    doc_id: str,
    *,
    content: str,
    title: str,
    description: str,
    tags: list[str],
    category: str,
    now: str,
    needs_reembed: bool,
    word_count: int,
    source_file: str | None,
) -> dict | None:
    """Persist a human edit to a Document page's body."""
    result = graph_store.query_graph(
        "MATCH (w:WikiPage {type:'Document'}) WHERE w.concept_id = $cid OR w.id = $cid "
        "SET w.content = $content, w.title = $title, w.summary = $description, w.overview = $description, "
        "w.tags = $tags, w.category = $category, w.edited_at = $now, w.needs_reembed = $needs_reembed, "
        "w.word_count = $word_count, w.source_file = coalesce($source_file, w.source_file) "
        "RETURN w",
        {
            "cid": doc_id, "content": content, "title": title, "description": description, "tags": tags,
            "category": category, "now": now, "needs_reembed": needs_reembed, "word_count": word_count,
            "source_file": source_file,
        },
    )
    recs = records_of(result)
    if not recs:
        return None
    return node_props(record_get(recs[0], "w"))


def build_prose(fm: DocumentFrontmatter, body: str) -> str:
    """Text embedded into Qdrant for a Document page."""
    parts = [fm.title, fm.description, body]
    return "\n\n".join(p.strip() for p in parts if p and p.strip()).strip()


def build_document_chunks(page: DocumentPage, tokenizer_name: str) -> list[dict]:
    fm = page.fm
    prose = build_prose(fm, page.body)
    return _chunks_for(
        prose, page_path=f"document/{fm.slug}", kind="Document", title=fm.title, summary=fm.description,
        symbol_id=fm.doc_id, repo=fm.repo, app=fm.app, tokenizer_name=tokenizer_name,
    )


def sync_document_qdrant(
    page: DocumentPage,
    embedder,
    vector_store,
    tokenizer_name: str,
    *,
    batch_size: int = 16,
    report: Callable[[int, int], None] | None = None,
) -> dict:
    """Re-embed one Document page's chunks, reporting (done, total) batches
    as it goes so the caller can surface embedding progress."""
    chunks = build_document_chunks(page, tokenizer_name)
    vector_store.create_collection()
    vector_store.delete_by_symbol_id(page.fm.doc_id)
    if not chunks:
        return {"chunks": 0, "stored": 0}

    total = len(chunks)
    stored_ids: list[str] = []
    for start in range(0, total, batch_size):
        batch = chunks[start : start + batch_size]
        embedded = embedder.embed_chunks(batch, batch_size=batch_size)
        stored_ids.extend(vector_store.upsert_chunks(embedded))
        if report is not None:
            report(min(start + len(batch), total), total)
    return {"chunks": total, "stored": len(stored_ids)}


def mark_reembedded(graph_store, doc_id: str) -> None:
    graph_store.query_graph(
        "MATCH (w:WikiPage {type:'Document'}) WHERE w.concept_id = $cid OR w.id = $cid SET w.needs_reembed = false",
        {"cid": doc_id},
    )


def load_document(graph_store, app: str, doc_id: str) -> dict | None:
    result = graph_store.query_graph(
        "MATCH (w:WikiPage {type:'Document'}) WHERE (w.concept_id = $cid OR w.id = $cid) AND w.app = $app RETURN w",
        {"cid": doc_id, "app": app},
    )
    recs = records_of(result)
    if not recs:
        return None
    return node_props(record_get(recs[0], "w"))


def document_page_from_props(props: dict) -> DocumentPage:
    fm = DocumentFrontmatter(
        title=props.get("title") or props.get("slug") or "Untitled",
        slug=props.get("slug") or "document",
        description=props.get("summary") or "",
        app=props.get("app") or "",
        repo=props.get("repo"),
        doc_id=props.get("concept_id") or "",
        category=props.get("category") or "note",
        tags=list(props.get("tags") or []),
        created_at=props.get("created_at") or "",
        edited_at=props.get("edited_at"),
        language=props.get("language") or "en",
        word_count=int(props.get("word_count") or 0),
        mentions=list(props.get("mentions") or []),
        source_file=props.get("source_file"),
        needs_reembed=bool(props.get("needs_reembed") or False),
    )
    return DocumentPage(fm=fm, body=props.get("content") or "")


def delete_document(graph_store, vector_store, wid: str, doc_id: str) -> None:
    """Remove a Document page from both stores (mirrors `store.delete_feature`)."""
    if graph_store is not None:
        graph_store.query_graph("MATCH (w:WikiPage {id:$wid}) DETACH DELETE w", {"wid": wid})
    if vector_store is not None:
        vector_store.delete_by_symbol_id(doc_id)


def write_document_bundle_file(page: DocumentPage, bundle_dir: str) -> bool:
    """Best-effort mirror of a Document page onto the OKF bundle on disk
    (`<bundle>/document/<slug>.md`) — not re-imported by `cvg-okf-sync`;
    Neo4j remains the source of truth. A missing bundle dir on this host
    (the common case for the API server) is not an error."""
    from pathlib import Path

    from code_vector_graph.ingestion.okf.features.template import compose_page

    doc_dir = Path(bundle_dir) / "document"
    if not doc_dir.parent.is_dir() and not Path(bundle_dir).is_dir():
        return False
    try:
        doc_dir.mkdir(parents=True, exist_ok=True)
        (doc_dir / f"{page.fm.slug}.md").write_text(compose_page(page.fm, page.body), encoding="utf-8")
        return True
    except Exception:
        logger.warning("Failed to write bundle file for document '%s'", page.fm.slug, exc_info=True)
        return False


def remove_document_bundle_file(slug: str, bundle_dir: str) -> None:
    from pathlib import Path

    path = Path(bundle_dir) / "document" / f"{slug}.md"
    try:
        path.unlink(missing_ok=True)
    except Exception:
        logger.warning("Failed to remove bundle file for document '%s'", slug, exc_info=True)

