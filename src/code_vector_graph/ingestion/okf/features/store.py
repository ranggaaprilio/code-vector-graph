"""Neo4j/Qdrant IO for Feature pages.

Mirrors `ingestion/okf/sync.py`'s WikiPage sync, but a Feature page documents
a *cluster* of code nodes rather than one, so it uses `IMPLEMENTED_BY` (one
edge per member) instead of `DOCUMENTS`; `DOCUMENTS` is kept for its usual
meaning by pointing the Feature page at the Repository it belongs to. The
preserve/stale policy for human-edited pages lives in `build.py`, which reads
`load_existing_features` before deciding what to (re)generate; `save_feature_page`
is the write path for a human edit via the dashboard's PUT endpoint.
"""

from __future__ import annotations

import logging
import uuid

from code_vector_graph.api.serialize import node_props, record_get, records_of
from code_vector_graph.ingestion.okf.features.models import ExistingFeature, FeatureFrontmatter, FeaturePage
from code_vector_graph.ingestion.okf.features.template import parse_sections
from code_vector_graph.ingestion.okf.sync import wiki_id

logger = logging.getLogger(__name__)

NAMESPACE = uuid.NAMESPACE_URL


def feature_id_for(app: str, repo: str, slug: str) -> str:
    """Stable id for a feature, scoped to one app+repo so two repos of the
    same app never collide on the same slug."""
    return str(uuid.uuid5(NAMESPACE, f"feature:{app}:{repo}:{slug}"))


def load_existing_features(graph_store, app: str, repo: str) -> dict[str, ExistingFeature]:
    """Feature-page state already in Neo4j for this app+repo, keyed by slug."""
    result = graph_store.query_graph(
        "MATCH (w:WikiPage {type:'Feature'}) WHERE w.app = $app AND w.repo = $repo "
        "RETURN w.id AS wid, w.concept_id AS feature_id, w.slug AS slug, w.source AS source, "
        "w.members_hash AS members_hash, w.edited_members_hash AS edited_members_hash, "
        "w.content AS content, w.stale AS stale, w.stale_since AS stale_since, "
        "w.title AS title, w.summary AS description, w.kind AS kind, w.tags AS tags, "
        "w.generated_at AS generated_at, w.edited_at AS edited_at",
        {"app": app, "repo": repo},
    )
    out: dict[str, ExistingFeature] = {}
    for rec in records_of(result):
        slug = record_get(rec, "slug")
        if not slug:
            continue
        out[slug] = ExistingFeature(
            wiki_id=record_get(rec, "wid"),
            feature_id=record_get(rec, "feature_id"),
            slug=slug,
            source=record_get(rec, "source") or "llm",
            members_hash=record_get(rec, "members_hash") or "",
            edited_members_hash=record_get(rec, "edited_members_hash"),
            content=record_get(rec, "content") or "",
            stale=bool(record_get(rec, "stale") or False),
            stale_since=record_get(rec, "stale_since"),
            title=record_get(rec, "title") or "",
            description=record_get(rec, "description") or "",
            kind=record_get(rec, "kind") or "other",
            tags=list(record_get(rec, "tags") or []),
            generated_at=record_get(rec, "generated_at") or "",
            edited_at=record_get(rec, "edited_at"),
        )
    return out


def _entry_point_files(body: str) -> set[str]:
    """File paths named in the '## Entry Points' table's Location column."""
    section = parse_sections(body).get("Entry Points", "")
    files: set[str] = set()
    for line in section.splitlines():
        line = line.strip()
        if not line.startswith("|") or set(line) <= {"|", "-", " "}:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3 or cells[0].lower() == "kind":
            continue
        location = cells[2].strip("`")
        path = location.split(":")[0].strip()
        if path:
            files.add(path)
    return files


def build_feature_graph(
    pages: list[FeaturePage],
    member_labels: dict[str, str],
    repo_id: str,
) -> tuple[list[dict], list[dict], dict[str, str]]:
    """WikiPage nodes for the given Feature pages, plus their `IMPLEMENTED_BY`
    (page -> member code node) and `DOCUMENTS` (page -> Repository) edges.

    ``member_labels`` maps a member code-node id to its Neo4j label (from the
    skeleton that produced the feature map), so `upsert_relationships` can
    target the right label instead of an unindexed label-less MATCH.
    """
    nodes: list[dict] = []
    rels: list[dict] = []
    node_labels: dict[str, str] = {repo_id: "Repository"}

    for page in pages:
        fm = page.fm
        wid = wiki_id(fm.feature_id)
        node_labels[wid] = "WikiPage"
        overview = parse_sections(page.body).get("Overview", "")
        nodes.append({
            "label": "WikiPage",
            "id": wid,
            "properties": {
                "concept_id": fm.feature_id,
                "path": f"feature/{fm.slug}",
                "type": "Feature",
                "title": fm.title,
                "summary": fm.description,
                "overview": overview,
                "tags": list(fm.tags),
                "resource": "",
                "source": fm.source,
                "repo": fm.repo,
                "app": fm.app,
                "how_it_works": None,
                "slug": fm.slug,
                "content": page.body,
                "kind": fm.kind,
                "members_hash": fm.members_hash,
                "edited_members_hash": fm.edited_members_hash,
                "member_files": list(fm.member_files),
                "member_count": len(fm.member_ids),
                "stale": fm.stale,
                "stale_since": fm.stale_since,
                "generated_at": fm.generated_at,
                "edited_at": fm.edited_at,
                "model": fm.model,
                "language": fm.language,
                "draft": None,
                "draft_generated_at": None,
                "needs_reembed": fm.needs_reembed,
            },
        })
        rels.append({"type": "DOCUMENTS", "source_id": wid, "target_id": repo_id, "properties": {}})

        entry_files = _entry_point_files(page.body)
        member_path_by_id = dict(zip(fm.member_ids, fm.member_files))
        for member_id in fm.member_ids:
            label = member_labels.get(member_id)
            if label:
                node_labels.setdefault(member_id, label)
            role = "entry_point" if member_path_by_id.get(member_id) in entry_files else "member"
            rels.append({"type": "IMPLEMENTED_BY", "source_id": wid, "target_id": member_id, "properties": {"role": role}})

    return nodes, rels, node_labels


def sync_features_neo4j(
    pages: list[FeaturePage],
    member_labels: dict[str, str],
    repo_id: str,
    graph_store,
) -> dict:
    """Upsert Feature WikiPage nodes + edges. Clears each page's old
    `IMPLEMENTED_BY` edges first, so a feature that lost a member doesn't
    keep a stale edge to it."""
    nodes, rels, node_labels = build_feature_graph(pages, member_labels, repo_id)
    graph_store.create_constraints()
    for page in pages:
        graph_store.query_graph(
            "MATCH (w:WikiPage {id:$wid})-[r:IMPLEMENTED_BY]->() DELETE r",
            {"wid": wiki_id(page.fm.feature_id)},
        )
    node_counts = graph_store.upsert_nodes(nodes)
    rel_counts = graph_store.upsert_relationships(rels, node_labels=node_labels)
    return {
        "wiki_pages": len(nodes),
        "implemented_by_edges": sum(1 for r in rels if r["type"] == "IMPLEMENTED_BY"),
        "nodes_created": node_counts.get("nodes_created", 0),
        "relationships_created": rel_counts.get("relationships_created", 0),
    }


def delete_feature(graph_store, vector_store, wid: str, feature_id: str) -> None:
    """Remove an orphaned LLM-authored Feature page from both stores."""
    if graph_store is not None:
        graph_store.query_graph("MATCH (w:WikiPage {id:$wid}) DETACH DELETE w", {"wid": wid})
    if vector_store is not None:
        vector_store.delete_by_symbol_id(feature_id)


def save_feature_page(
    graph_store,
    feature_id: str,
    *,
    content: str,
    title: str,
    summary: str,
    overview: str,
    tags: list[str],
    source: str,
    now: str,
    needs_reembed: bool,
) -> dict | None:
    """Persist a human edit (or an applied AI draft) to a Feature page's body.

    Sets ``edited_members_hash = members_hash`` (the code state this edit was
    made against) and clears `stale`/`stale_since` — a later build compares
    the *new* members_hash to `edited_members_hash` to detect drift and
    re-flag the page stale, without ever overwriting `content` itself.
    """
    result = graph_store.query_graph(
        "MATCH (w:WikiPage {type:'Feature'}) WHERE w.concept_id = $cid OR w.id = $cid "
        "SET w.content = $content, w.title = $title, w.summary = $summary, w.overview = $overview, "
        "w.tags = $tags, w.source = $source, w.edited_at = $now, w.edited_members_hash = w.members_hash, "
        "w.stale = false, w.stale_since = null, w.needs_reembed = $needs_reembed, w.draft = null "
        "RETURN w",
        {
            "cid": feature_id,
            "content": content,
            "title": title,
            "summary": summary,
            "overview": overview,
            "tags": tags,
            "source": source,
            "now": now,
            "needs_reembed": needs_reembed,
        },
    )
    recs = records_of(result)
    if not recs:
        return None
    return node_props(record_get(recs[0], "w"))


def build_prose(fm: FeatureFrontmatter, body: str) -> str:
    """Text embedded into Qdrant for a Feature page."""
    parts = [fm.title, fm.description, body]
    return "\n\n".join(p.strip() for p in parts if p and p.strip()).strip()


def _chunks_for(
    prose: str,
    *,
    page_path: str,
    kind: str,
    title: str,
    summary: str,
    symbol_id: str,
    repo: str | None,
    app: str,
    tokenizer_name: str,
    chunk_size: int = 400,
    chunk_overlap: int = 64,
) -> list[dict]:
    """Turn one page's prose into store-ready chunk dicts (token-bounded).

    Shared by Feature and Document pages (and any future OKF page kind) —
    only the tagging (``kind``/``symbol_id``/...) differs per caller.
    """
    from code_vector_graph.parsing.chunker import chunk_text  # local import keeps this module light

    if not prose:
        return []
    raw = chunk_text(
        text=prose,
        start_line=1,
        end_line=max(1, len(prose.splitlines())),
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        file_path=page_path,
        language="",
        node_type=kind,
        class_name=title,
        tokenizer_name=tokenizer_name,
    )
    total = len(raw)
    chunks: list[dict] = []
    for i, ch in enumerate(raw):
        meta = ch.pop("metadata", {})
        ch.update(meta)
        ch["text_content"] = ch["text"]
        ch["total_chunks"] = total
        ch["chunk_index"] = i
        ch["id"] = str(uuid.uuid5(NAMESPACE, f"okf:{symbol_id}:{i}"))
        ch["source"] = "okf_wiki"
        ch["kind"] = kind
        ch["term"] = title
        ch["summary"] = summary
        ch["symbol_id"] = symbol_id
        ch["repo"] = repo
        ch["app"] = app
        chunks.append(ch)
    return chunks


def build_feature_chunks(
    pages: list[FeaturePage],
    tokenizer_name: str,
    chunk_size: int = 400,
    chunk_overlap: int = 64,
) -> list[dict]:
    """Turn Feature-page prose into store-ready chunk dicts (token-bounded)."""
    chunks: list[dict] = []
    for page in pages:
        fm = page.fm
        prose = build_prose(fm, page.body)
        chunks.extend(_chunks_for(
            prose, page_path=f"feature/{fm.slug}", kind="Feature", title=fm.title, summary=fm.description,
            symbol_id=fm.feature_id, repo=fm.repo, app=fm.app, tokenizer_name=tokenizer_name,
            chunk_size=chunk_size, chunk_overlap=chunk_overlap,
        ))
    return chunks


def sync_features_qdrant(
    pages: list[FeaturePage],
    embedder,
    vector_store,
    tokenizer_name: str,
    batch_size: int = 64,
) -> dict:
    """Re-embed the given pages (the caller filters to touched, non-preserved
    pages — an unchanged human-edited page's prose never needs re-embedding)."""
    chunks = build_feature_chunks(pages, tokenizer_name)
    if not chunks:
        return {"chunks": 0, "stored": 0}
    vector_store.create_collection()
    for page in pages:
        vector_store.delete_by_symbol_id(page.fm.feature_id)
    embedded = embedder.embed_chunks(chunks, batch_size=batch_size)
    ids = vector_store.upsert_chunks(embedded)
    return {"chunks": len(chunks), "stored": len(ids)}
