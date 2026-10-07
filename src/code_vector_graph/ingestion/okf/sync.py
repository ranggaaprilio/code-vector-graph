"""Phase 2 — sync an OKF wiki bundle into Qdrant + Neo4j.

The OKF bundle (produced by Phase 1) is the source of truth. This module parses
it back and pushes the enriched knowledge into the two stores so the wiki becomes
searchable and connected to the existing code graph:

- **Qdrant**: embed each page's prose (title + summary + overview + how-it-works),
  chunked with the shared chunker to respect the embedder's token cap, and upsert
  as points tagged `source="okf_wiki"` — so semantic search returns human-readable
  explanations, not just raw code.
- **Neo4j**: one `WikiPage` node per concept, linked to the code node it documents
  via `DOCUMENTS` (WikiPage.concept_id == the code node's uuid5 id) and to other
  wiki pages via `REFERENCES` (the LLM-suggested "Related" links, which are not in
  the AST). This wires the wiki layer into the existing code graph.

Store objects/embedder are injected so the logic is unit-testable without any DB.
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any, Optional

import yaml

from code_vector_graph.config import SUPPORTED_EXTENSIONS
from code_vector_graph.ingestion.okf.cache import CACHE_FILENAME

logger = logging.getLogger(__name__)

NAMESPACE = uuid.NAMESPACE_URL
RESERVED = {"index.md", "log.md"}

# OKF `## Related` heading -> the only wiki-to-wiki edge we materialize. The
# structural edges (CALLS/CONTAINS/INHERITS) already exist between the *code*
# nodes in Neo4j, so we don't duplicate them; the LLM's "Related" links are the
# genuinely new cross-references.
_RELATED_HEADING = "Related"


def wiki_id(concept_id: str) -> str:
    """Deterministic id for a WikiPage node documenting `concept_id`."""
    return str(uuid.uuid5(NAMESPACE, f"okf-wiki:{concept_id}"))


def _rel(rel_type: str, source_id: str, target_id: str) -> dict[str, Any]:
    return {"type": rel_type, "source_id": source_id, "target_id": target_id, "properties": {}}


def _language_from_path(path: str) -> str:
    ext = Path(path.split("#")[0]).suffix.lower()
    return SUPPORTED_EXTENSIONS.get(ext, {}).get("language", "")


def _section(body: str, name: str, level: str = "# ") -> str:
    """Extract a Markdown section body by heading text (until the next heading)."""
    pattern = rf"^{re.escape(level)}{re.escape(name)}\s*$"
    lines = body.splitlines()
    out: list[str] = []
    capturing = False
    heading_re = re.compile(rf"^#+\s")
    start_re = re.compile(pattern)
    for line in lines:
        if capturing:
            if heading_re.match(line):
                break
            out.append(line)
        elif start_re.match(line):
            capturing = True
    return "\n".join(out).strip()


def _related_links(body: str) -> list[str]:
    """Concept paths (minus `.md`) linked under the `## Related` subsection."""
    section = _section(body, _RELATED_HEADING, level="## ")
    if not section:
        return []
    return [m.rstrip("/").lstrip("/") for m in re.findall(r"]\(/([^)]+)\.md\)", section)]


def _parse_page(path: Path, bundle_root: Path) -> Optional[dict]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        fm = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(fm, dict) or "type" not in fm:
        return None
    body = parts[2]
    repo = fm.get("repo") or None
    app = fm.get("app") or None

    if "okf_version" in fm:
        # The root index is the Repository page: accepted only at the bundle
        # root and only when it declares type: Repository. Its Architecture
        # Overview becomes the WikiPage that DOCUMENTS the Repository node.
        if path.parent.resolve() != bundle_root.resolve() or fm.get("type") != "Repository":
            return None
        return {
            "path": "index",
            "concept_id": fm.get("node_id", "") or "",
            "type": "Repository",
            "title": fm.get("title", "") or repo or "index",
            "summary": fm.get("description", "") or "",
            "overview": _section(body, "Architecture Overview"),
            "how_it_works": _section(body, "How it fits together"),
            "tags": [],
            "resource": "",
            "source": fm.get("source", "llm") or "llm",
            "file_path": "",
            "language": "",
            "related_paths": [],
            "repo": repo,
            "app": app,
        }

    rel_path = path.relative_to(bundle_root).as_posix()
    concept_path = rel_path[:-3] if rel_path.endswith(".md") else rel_path

    if fm.get("type") == "Feature":
        # Feature pages carry their own frontmatter shape (see
        # ingestion/okf/features/template.py) — no `resource`/`how_it_works`,
        # and extra fields (`content`, `member_ids`, ...) consumed only by
        # build_wiki_graph's Feature branch below.
        from code_vector_graph.ingestion.okf.features.template import parse_sections as _feature_sections

        return {
            "path": concept_path,
            "concept_id": fm.get("feature_id", "") or "",
            "type": "Feature",
            "title": fm.get("title", "") or concept_path,
            "summary": fm.get("description", "") or "",
            "overview": _feature_sections(body).get("Overview", ""),
            "how_it_works": None,
            "tags": fm.get("tags", []) or [],
            "resource": "",
            "source": fm.get("source", "llm") or "llm",
            "file_path": "",
            "language": fm.get("language", "") or "",
            "related_paths": [],
            "repo": repo,
            "app": app,
            "content": body.strip(),
            "slug": fm.get("slug", "") or "",
            "kind": fm.get("kind", "") or "other",
            "members_hash": fm.get("members_hash", "") or "",
            "member_files": [str(x) for x in (fm.get("member_files") or []) if isinstance(x, str)],
            "member_ids": [str(x) for x in (fm.get("member_ids") or []) if isinstance(x, str)],
            "stale": bool(fm.get("stale", False)),
            "stale_since": fm.get("stale_since"),
            "generated_at": fm.get("generated_at", "") or "",
            "edited_at": fm.get("edited_at"),
            "edited_members_hash": fm.get("edited_members_hash"),
            "model": fm.get("model"),
            "needs_reembed": bool(fm.get("needs_reembed", False)),
        }

    resource = fm.get("resource", "") or ""
    return {
        "path": concept_path,
        "concept_id": fm.get("node_id", "") or "",
        "type": fm.get("type", ""),
        "title": fm.get("title", "") or concept_path,
        "summary": fm.get("description", "") or "",
        "overview": _section(body, "Overview"),
        "how_it_works": _section(body, "How it works"),
        "tags": fm.get("tags", []) or [],
        "resource": resource,
        "source": fm.get("source", "llm") or "llm",
        "file_path": resource.split("#")[0],
        "language": _language_from_path(resource),
        "related_paths": _related_links(body),
        "repo": repo,
        "app": app,
    }


def parse_bundle(bundle_dir: str) -> list[dict]:
    """Parse every concept page in an OKF bundle (skips reserved index/log)."""
    root = Path(bundle_dir)
    concepts: list[dict] = []
    for md in sorted(root.rglob("*.md")):
        if md.name in RESERVED:
            # Per-directory listings and log.md are skipped; the root index.md is
            # the Repository page (see _parse_page) and is the one exception.
            if md.name != "index.md" or md.parent.resolve() != root.resolve():
                continue
        parsed = _parse_page(md, root)
        if parsed:
            concepts.append(parsed)
    logger.info("Parsed %d concept pages from %s", len(concepts), bundle_dir)
    return concepts


def build_prose(concept: dict) -> str:
    """Text embedded into Qdrant for this concept."""
    if concept.get("type") == "Feature":
        # Feature pages have no how_it_works section; their prose is the
        # whole validated body (see features/store.py:build_prose).
        parts = [concept.get("title", ""), concept.get("summary", ""), concept.get("content", "")]
    else:
        parts = [concept.get("title", ""), concept.get("summary", ""),
                 concept.get("overview", ""), concept.get("how_it_works", "")]
    return "\n\n".join(p.strip() for p in parts if p and p.strip()).strip()


# --- Neo4j -----------------------------------------------------------------

def _build_feature_pages(feature_concepts: list[dict]) -> "list":
    """Reconstruct `FeaturePage`s from parsed Feature concept dicts, so a
    disk re-import (e.g. after `cvg-reinit-graph --clear`) can reuse
    `features.store.build_feature_graph` instead of duplicating its shape."""
    from code_vector_graph.ingestion.okf.features.models import FeatureFrontmatter, FeaturePage

    pages = []
    for c in feature_concepts:
        fm = FeatureFrontmatter(
            title=c.get("title") or c["path"],
            slug=c.get("slug") or "",
            description=c.get("summary") or "",
            app=c.get("app") or "",
            repo=c.get("repo") or "",
            feature_id=c.get("concept_id") or "",
            kind=c.get("kind") or "other",
            members_hash=c.get("members_hash") or "0" * 16,
            member_files=c.get("member_files") or [],
            member_ids=c.get("member_ids") or [],
            source=c.get("source") or "llm",
            stale=bool(c.get("stale", False)),
            stale_since=c.get("stale_since"),
            generated_at=c.get("generated_at") or "",
            edited_at=c.get("edited_at"),
            edited_members_hash=c.get("edited_members_hash"),
            model=c.get("model"),
            language=c.get("language") or "en",
            tags=[t for t in (c.get("tags") or []) if isinstance(t, str)],
            needs_reembed=bool(c.get("needs_reembed", False)),
        )
        pages.append(FeaturePage(fm=fm, body=c.get("content") or ""))
    return pages


def build_wiki_graph(concepts: list[dict]) -> tuple[list[dict], list[dict], dict[str, str]]:
    """Build WikiPage nodes + DOCUMENTS/REFERENCES relationships.

    Returns (nodes, relationships, node_labels) ready for GraphStore.
    """
    by_path = {c["path"]: c for c in concepts}
    nodes: list[dict] = []
    rels: list[dict] = []
    node_labels: dict[str, str] = {}

    feature_concepts = [c for c in concepts if c.get("type") == "Feature" and c.get("concept_id")]
    other_concepts = [c for c in concepts if c.get("type") != "Feature"]

    for c in other_concepts:
        cid = c.get("concept_id")
        if not cid:
            continue  # cannot link a page with no documented node id
        wid = wiki_id(cid)
        nodes.append({
            "label": "WikiPage",
            "id": wid,
            "properties": {
                "concept_id": cid,
                "path": c["path"],
                "type": c["type"],
                "title": c.get("title") or c["path"],
                "summary": c.get("summary") or "",
                "overview": c.get("overview") or "",
                "tags": [t for t in (c.get("tags") or []) if isinstance(t, str)],
                "resource": c.get("resource") or "",
                "source": c.get("source") or "llm",
                "repo": c.get("repo") or None,
                "app": c.get("app") or None,
                "how_it_works": c.get("how_it_works") or None,
            },
        })
        node_labels[wid] = "WikiPage"
        if c["type"] == "Repository":
            node_labels[cid] = "Repository"
        else:
            node_labels.setdefault(cid, c["type"])  # documented code node label
        rels.append(_rel("DOCUMENTS", wid, cid))
        for rp in c.get("related_paths", []):
            tgt = by_path.get(rp)
            if tgt and tgt.get("concept_id"):
                rels.append(_rel("REFERENCES", wid, wiki_id(tgt["concept_id"])))

    if feature_concepts:
        from code_vector_graph.ingestion.okf.features.store import build_feature_graph
        from code_vector_graph.repos import RepoIdentity

        by_repo: dict[tuple[str, str], list] = {}
        for c, page in zip(feature_concepts, _build_feature_pages(feature_concepts)):
            by_repo.setdefault((c.get("app") or "", c.get("repo") or ""), []).append(page)
        for (app_, repo_), repo_pages in by_repo.items():
            # Member-node labels are unknown on a disk re-import (no skeleton
            # available); upsert_relationships falls back to a label-less
            # MATCH for those, which still creates the edge correctly.
            repo_id = RepoIdentity(app=app_, name=repo_, root="").id
            f_nodes, f_rels, f_labels = build_feature_graph(repo_pages, {}, repo_id)
            nodes.extend(f_nodes)
            rels.extend(f_rels)
            node_labels.update(f_labels)

    return nodes, rels, node_labels


def sync_neo4j(concepts: list[dict], graph_store) -> dict:
    """Upsert WikiPage nodes and their edges into Neo4j."""
    nodes, rels, node_labels = build_wiki_graph(concepts)
    graph_store.create_constraints()
    node_counts = graph_store.upsert_nodes(nodes)
    rel_counts = graph_store.upsert_relationships(rels, node_labels=node_labels)
    documents = sum(1 for r in rels if r["type"] == "DOCUMENTS")
    references = sum(1 for r in rels if r["type"] == "REFERENCES")
    return {
        "wiki_pages": len(nodes),
        "documents_edges": documents,
        "references_edges": references,
        "nodes_created": node_counts.get("nodes_created", 0),
        "relationships_created": rel_counts.get("relationships_created", 0),
    }


# --- Qdrant ----------------------------------------------------------------

def build_wiki_chunks(concepts: list[dict], tokenizer_name: str, chunk_size: int = 400, chunk_overlap: int = 64) -> list[dict]:
    """Turn wiki prose into store-ready chunk dicts (token-bounded)."""
    from code_vector_graph.parsing.chunker import chunk_text  # local import keeps this module light

    chunks: list[dict] = []
    for c in concepts:
        prose = build_prose(c)
        if not prose:
            continue
        raw = chunk_text(
            text=prose,
            start_line=1,
            end_line=max(1, len(prose.splitlines())),
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            file_path=c.get("file_path", "") or c["path"],
            language=c.get("language", "") or "",
            node_type=c.get("type"),
            class_name=c.get("title"),
            tokenizer_name=tokenizer_name,
        )
        total = len(raw)
        for i, ch in enumerate(raw):
            meta = ch.pop("metadata", {})
            ch.update(meta)
            ch["text_content"] = ch["text"]
            ch["total_chunks"] = total
            ch["chunk_index"] = i
            ch["id"] = str(uuid.uuid5(NAMESPACE, f"okf:{c['concept_id'] or c['path']}:{i}"))
            ch["source"] = "okf_wiki"
            ch["kind"] = c.get("type")
            ch["term"] = c.get("title")
            ch["summary"] = c.get("summary")
            ch["symbol_id"] = c.get("concept_id")
            ch["repo"] = c.get("repo")
            ch["app"] = c.get("app")
            chunks.append(ch)
    return chunks


def sync_qdrant(concepts: list[dict], embedder, vector_store, tokenizer_name: str, batch_size: int = 64) -> dict:
    """Embed wiki prose and upsert it into a Qdrant collection."""
    chunks = build_wiki_chunks(concepts, tokenizer_name)
    if not chunks:
        return {"chunks": 0, "stored": 0}
    vector_store.create_collection()
    embedded = embedder.embed_chunks(chunks, batch_size=batch_size)
    ids = vector_store.upsert_chunks(embedded)
    return {"chunks": len(chunks), "stored": len(ids)}
