"""Render the enriched skeleton into an OKF (Open Knowledge Format) bundle.

OKF v0.1: a directory of Markdown files with YAML frontmatter. Each non-reserved
`.md` file is one concept; `type` is the only required frontmatter field.
Relationships are ordinary Markdown links to other concept files, grouped under
headings that name the relationship type. Reserved files: per-directory
`index.md` listings and a root `index.md` (which may carry `okf_version`), plus a
`log.md` change history.

Written with PyYAML only — no dependency on Google's Python 3.13 reference agent.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from code_vector_graph.ingestion.okf.skeleton import Skeleton, concept_name, dir_for_label
from code_vector_graph.repos import RepoIdentity

logger = logging.getLogger(__name__)

OKF_VERSION = "0.1"

# Relationship heading text per edge type, in display order.
_REL_HEADINGS = [
    ("contains", "Contains"),
    ("calls", "Calls"),
    ("inherits", "Inherits"),
    ("imports", "Imports"),
    ("related", "Related"),
]
_MAX_REL = 40


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _relpath(path: str, repo_root: Optional[str]) -> str:
    if not repo_root:
        return path
    try:
        return os.path.relpath(path, repo_root)
    except ValueError:
        return path


def _resource(node: dict, repo_base_url: Optional[str], repo_root: Optional[str]) -> str:
    fmeta = node.get("_file", {}) or {}
    props = node.get("properties", {}) or {}
    path = fmeta.get("path") or props.get("path") or ""
    if not path:
        return ""
    rel = _relpath(path, repo_root)
    start, end = props.get("start_line"), props.get("end_line")
    anchor = f"#L{start}-L{end}" if start and end else ""
    if repo_base_url:
        return f"{repo_base_url.rstrip('/')}/{rel}{anchor}"
    return f"{rel}{anchor}"


def _tags(node: dict, enrichment: dict) -> list[str]:
    props = node.get("properties", {}) or {}
    fmeta = node.get("_file", {}) or {}
    tags: list[str] = []
    lang = props.get("language") or fmeta.get("language")
    if lang:
        tags.append(lang)
    if props.get("visibility"):
        tags.append(props["visibility"])
    if props.get("is_exported"):
        tags.append("exported")
    if props.get("is_async"):
        tags.append("async")
    for dec in props.get("decorators") or []:
        tags.append(f"@{dec}")
    tags.extend(enrichment.get("tags") or [])
    # dedupe preserving order
    seen: set[str] = set()
    out = []
    for t in tags:
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _frontmatter(
    node: dict,
    enrichment: dict,
    repo_base_url: Optional[str],
    repo_root: Optional[str],
    timestamp: str,
    repo_name: Optional[str] = None,
    app_name: Optional[str] = None,
) -> str:
    props = node.get("properties", {}) or {}
    fm: dict = {
        "type": node.get("label", "Concept"),
        "title": concept_name(node),
        "description": enrichment.get("summary", ""),
        "resource": _resource(node, repo_base_url, repo_root),
        "tags": _tags(node, enrichment),
        "timestamp": timestamp,
        "node_id": node.get("id", ""),
        "start_line": props.get("start_line"),
        "end_line": props.get("end_line"),
        "source": "llm",
        "repo": repo_name,
        "app": app_name,
    }
    fm = {k: v for k, v in fm.items() if v not in (None, "", [], {})}
    body = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True, default_flow_style=False)
    return f"---\n{body}---\n"


def _link(skeleton: Skeleton, target_id: Optional[str]) -> Optional[str]:
    if not target_id:
        return None
    path = skeleton.id_to_path.get(target_id)
    if not path:
        return None
    node = skeleton.nodes.get(target_id)
    title = concept_name(node) if node else Path(path).name
    return f"[{title}](/{path}.md)"


def _link_or_text(skeleton: Skeleton, name: str) -> str:
    link = _link(skeleton, skeleton.resolve_name(name))
    return link if link else name


def _relationships(skeleton: Skeleton, node: dict, enrichment: dict) -> str:
    props = node.get("properties", {}) or {}
    groups: dict[str, list[str]] = {}

    # Contains — real CONTAINS edges to enriched children.
    contains = []
    for cid in skeleton.contains.get(node["id"], [])[:_MAX_REL]:
        link = _link(skeleton, cid)
        if link:
            contains.append(link)
    if contains:
        groups["contains"] = contains

    # Calls — from the node's own call_sites, resolved by name.
    calls = []
    seen_calls: set[str] = set()
    for callee in (props.get("call_sites") or [])[:_MAX_REL]:
        if callee in seen_calls:
            continue
        seen_calls.add(callee)
        calls.append(_link_or_text(skeleton, callee))
    if calls:
        groups["calls"] = calls

    # Inherits — parent class / extended interfaces, resolved by name.
    inherits = []
    if props.get("parent_class"):
        inherits.append(_link_or_text(skeleton, props["parent_class"]))
    for base in props.get("extends") or []:
        inherits.append(_link_or_text(skeleton, base))
    if inherits:
        groups["inherits"] = inherits

    # Imports — module strings, shown as plain text (external deps).
    imports = [m for m in (props.get("imports") or [])[:_MAX_REL]]
    if imports:
        groups["imports"] = imports

    # Related — model-suggested, validated against the symbol index.
    related = []
    seen_rel: set[str] = set()
    for name in (enrichment.get("related") or [])[:_MAX_REL]:
        if name == concept_name(node) or name in seen_rel:
            continue
        seen_rel.add(name)
        link = _link(skeleton, skeleton.resolve_name(name))
        if link:
            related.append(link)
    if related:
        groups["related"] = related

    if not groups:
        return ""

    out = ["# Relationships", ""]
    for key, heading in _REL_HEADINGS:
        items = groups.get(key)
        if not items:
            continue
        out.append(f"## {heading}")
        out.extend(f"- {item}" for item in items)
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def render_page(
    skeleton: Skeleton,
    node: dict,
    enrichment: dict,
    repo_base_url: Optional[str],
    repo_root: Optional[str],
    timestamp: str,
    repo_name: Optional[str] = None,
    app_name: Optional[str] = None,
) -> str:
    parts = [_frontmatter(node, enrichment, repo_base_url, repo_root, timestamp, repo_name, app_name)]
    parts.append(f"# {concept_name(node)}\n")

    if enrichment.get("summary"):
        parts.append(f"# Summary\n\n{enrichment['summary']}\n")
    if enrichment.get("overview"):
        parts.append(f"# Overview\n\n{enrichment['overview']}\n")
    if enrichment.get("how_it_works"):
        parts.append(f"# How it works\n\n{enrichment['how_it_works']}\n")

    params = enrichment.get("parameters") or []
    if params:
        rows = ["# Parameters", ""]
        for p in params:
            desc = p.get("description", "")
            rows.append(f"- `{p['name']}`" + (f" — {desc}" if desc else ""))
        parts.append("\n".join(rows) + "\n")

    rel = _relationships(skeleton, node, enrichment)
    if rel:
        parts.append(rel)

    return "\n".join(parts).rstrip() + "\n"


def _render_dir_index(label: str, entries: list[tuple[str, str]]) -> str:
    """Per-directory listing (reserved file, no frontmatter)."""
    out = [f"# {label}", ""]
    for title, path in sorted(entries):
        out.append(f"- [{title}](/{path}.md)")
    return "\n".join(out) + "\n"


def _render_root_index(
    skeleton: Skeleton,
    overview: dict,
    counts: dict[str, int],
    timestamp: str,
    repo_name: Optional[str] = None,
    app_name: Optional[str] = None,
    repo_root: Optional[str] = None,
) -> str:
    """Root ``index.md``: the Repository page.

    Besides ``okf_version`` the frontmatter now carries ``type: Repository`` and
    the repo/app identity, so `cvg-okf-sync` can turn it into a WikiPage that
    DOCUMENTS the Repository node (see repos.RepoIdentity).
    """
    repo_name = repo_name or Path(skeleton.repo_path).resolve().name or skeleton.repo_path
    app_name = app_name or repo_name
    root = repo_root or skeleton.repo_path
    identity = RepoIdentity(app=app_name, name=repo_name, root=str(Path(root).resolve()) if root else "")
    fm_dict = {
        "okf_version": OKF_VERSION,
        "type": "Repository",
        "title": repo_name,
        "repo": repo_name,
        "app": app_name,
        "node_id": identity.id,
        "description": overview.get("summary", "") or "",
        "source": "llm",
        "timestamp": timestamp,
    }
    fm = yaml.safe_dump(fm_dict, sort_keys=False, allow_unicode=True, default_flow_style=False)
    parts = [f"---\n{fm}---\n", f"# {repo_name} — Code Wiki\n"]
    if overview.get("summary"):
        parts.append(f"# Summary\n\n{overview['summary']}\n")
    if overview.get("overview"):
        parts.append(f"# Architecture Overview\n\n{overview['overview']}\n")
    if overview.get("how_it_works"):
        parts.append(f"# How it fits together\n\n{overview['how_it_works']}\n")

    parts.append("# Contents\n")
    for label in sorted(counts):
        d = dir_for_label(label)
        parts.append(f"- [{label} ({counts[label]})](/{d}/index.md)")
    parts.append("")
    return "\n".join(parts).rstrip() + "\n"


def _render_log(skeleton: Skeleton, stats: dict, timestamp: str) -> str:
    lines = [
        "# Log",
        "",
        f"- generated_at: {timestamp}",
        f"- repo_path: {skeleton.repo_path}",
        f"- files: {len(skeleton.files)}",
        f"- concepts: {len(skeleton.concept_ids)}",
    ]
    for k in ("model_flash", "model_pro", "enriched", "cached", "fallback", "dry_run"):
        if k in stats:
            lines.append(f"- {k}: {stats[k]}")
    by_type = stats.get("counts", {})
    if by_type:
        lines.append("- counts_by_type:")
        for label in sorted(by_type):
            lines.append(f"    - {label}: {by_type[label]}")
    return "\n".join(lines) + "\n"


def write_bundle(
    out_dir: str,
    skeleton: Skeleton,
    enrichments: dict[str, dict],
    overview: dict,
    *,
    repo_base_url: Optional[str] = None,
    repo_root: Optional[str] = None,
    stats: Optional[dict] = None,
    timestamp: Optional[str] = None,
    repo_name: Optional[str] = None,
    app_name: Optional[str] = None,
) -> dict:
    """Write the full OKF bundle. Returns a counts dict.

    ``repo_name`` / ``app_name`` are recorded in every page's frontmatter and on
    the root index (the Repository page); they default to the repo directory name.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    repo_root = repo_root or skeleton.repo_path
    timestamp = timestamp or _now_iso()
    repo_name = repo_name or Path(skeleton.repo_path).resolve().name or skeleton.repo_path
    app_name = app_name or repo_name

    counts: dict[str, int] = {}
    dir_entries: dict[str, list[tuple[str, str]]] = {}
    written = 0

    for nid in skeleton.concept_ids:
        node = skeleton.nodes.get(nid)
        if not node:
            continue
        enrichment = enrichments.get(nid) or {}
        rel_path = skeleton.id_to_path[nid]  # e.g. "function/foo-1a2b3c4d"
        page = render_page(skeleton, node, enrichment, repo_base_url, repo_root, timestamp, repo_name, app_name)
        file_path = out / f"{rel_path}.md"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(page, encoding="utf-8")
        written += 1
        label = node["label"]
        counts[label] = counts.get(label, 0) + 1
        d = dir_for_label(label)
        dir_entries.setdefault(d, []).append((concept_name(node), rel_path))

    # Per-directory index.md
    label_by_dir = {dir_for_label(lbl): lbl for lbl in counts}
    for d, entries in dir_entries.items():
        (out / d / "index.md").write_text(
            _render_dir_index(label_by_dir.get(d, d.title()), entries), encoding="utf-8"
        )

    # Root index.md + log.md
    (out / "index.md").write_text(
        _render_root_index(skeleton, overview, counts, timestamp, repo_name, app_name, repo_root),
        encoding="utf-8",
    )
    log_stats = dict(stats or {})
    log_stats["counts"] = counts
    (out / "log.md").write_text(_render_log(skeleton, log_stats, timestamp), encoding="utf-8")

    logger.info("Wrote OKF bundle to %s (%d concept pages)", out, written)
    return {"pages": written, "counts": counts}
