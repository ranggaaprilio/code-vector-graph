"""Per-file inventory for feature discovery.

Summarizes each file the OKF `Skeleton` scanned — exports, child symbols, a
best-effort "looks like an entry point" hint, and its cached one-line summary
if enrichment already ran — so the feature-map LLM call can group files
without re-reading source. `chunk_inventory` then packs that inventory into
LLM-call-sized groups (by top-level directory) for large repos.
"""

from __future__ import annotations

import os
import re
from typing import Iterable

from code_vector_graph.ingestion.okf.cache import concept_hash
from code_vector_graph.ingestion.okf.features.models import FileInventory
from code_vector_graph.ingestion.okf.skeleton import Skeleton, concept_name

# Decorator names (bare, as extracted by graph_extractor._get_decorators — no
# "@" or call args) that usually mark an HTTP handler or another entry point.
_HTTP_DECORATORS = {"get", "post", "put", "patch", "delete", "options", "head"}
_OTHER_ENTRY_DECORATORS = {"cron", "eventpattern", "messagepattern", "sse", "webhook", "listener", "subscribe"}

# call_sites are callee expressions as text (e.g. "router.get", "app.post");
# matched structurally rather than by scanning raw source we don't have here.
_ROUTE_CALL_RE = re.compile(r"^(?:router|app|route|api)\.(get|post|put|patch|delete|options|head)$", re.IGNORECASE)
_QUEUE_CALL_RE = re.compile(r"\.(consumer|subscribe|schedule|cron|on)$", re.IGNORECASE)


def _route_hints(decorators: Iterable[str], call_sites: Iterable[str]) -> list[str]:
    hints: list[str] = []
    for d in decorators:
        dl = (d or "").strip().lower()
        if dl in _HTTP_DECORATORS:
            hints.append(dl.upper())
        elif dl in _OTHER_ENTRY_DECORATORS:
            hints.append(dl)
    for c in call_sites:
        cl = (c or "").strip()
        m = _ROUTE_CALL_RE.match(cl)
        if m:
            hints.append(m.group(1).upper())
        elif _QUEUE_CALL_RE.search(cl):
            hints.append("queue/cron")
    seen: set[str] = set()
    out: list[str] = []
    for h in hints:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


def _symbol_line(node: dict) -> str:
    props = node.get("properties", {}) or {}
    bits = [f"{node.get('label', '')} {concept_name(node)}"]
    params = props.get("parameters")
    if params:
        bits.append(f"({', '.join(params)})")
    if props.get("is_async"):
        bits.append("[async]")
    if props.get("is_exported"):
        bits.append("[exported]")
    return " ".join(bits)


def _find_file_node(skeleton: Skeleton, path: str) -> dict | None:
    for node in skeleton.nodes.values():
        if node.get("label") == "File" and (node.get("_file") or {}).get("path") == path:
            return node
    return None


def build_inventory(skeleton: Skeleton, okf_cache: dict[str, dict] | None = None) -> list[FileInventory]:
    """One `FileInventory` per file the skeleton scanned that produced a File
    node (i.e. wasn't excluded from the concept-enrichment labels)."""
    okf_cache = okf_cache or {}
    out: list[FileInventory] = []
    for fmeta in skeleton.files:
        path = fmeta["path"]
        file_node = _find_file_node(skeleton, path)
        if file_node is None:
            continue
        props = file_node.get("properties", {}) or {}
        # `build_skeleton` runs the extractor directly, without the main
        # pipeline's repo-identity stamping step, so File nodes never carry
        # `rel_path` here — compute it from the skeleton's own repo_path.
        rel_path = os.path.relpath(path, skeleton.repo_path).replace(os.sep, "/")
        top_dir = rel_path.split("/", 1)[0] if "/" in rel_path else "."

        symbols: list[str] = []
        decorators = list(props.get("decorators") or [])
        call_sites = list(props.get("call_sites") or [])
        for child_id in skeleton.contains.get(file_node["id"], []):
            child = skeleton.nodes.get(child_id)
            if not child:
                continue
            symbols.append(_symbol_line(child))
            cprops = child.get("properties", {}) or {}
            decorators.extend(cprops.get("decorators") or [])
            call_sites.extend(cprops.get("call_sites") or [])

        out.append(
            FileInventory(
                file_id=file_node["id"],
                path=path,
                rel_path=rel_path,
                language=fmeta.get("language", ""),
                top_dir=top_dir,
                exports=list(props.get("exports") or []),
                symbols=symbols,
                routes=_route_hints(decorators, call_sites),
                summary=(okf_cache.get(concept_hash(file_node)) or {}).get("summary", ""),
                concept_hash=concept_hash(file_node),
            )
        )
    return out


def _file_cost(f: FileInventory) -> int:
    """Rough prompt-character cost of one file's inventory line."""
    return len(f.rel_path) + len(f.summary) + sum(len(s) for s in f.symbols) + sum(len(e) for e in f.exports) + 40


def chunk_inventory(
    inventory: list[FileInventory],
    max_files: int = 250,
    max_chars: int = 60_000,
) -> list[list[FileInventory]]:
    """Group files by top-level directory, then greedily pack directories
    together into chunks bounded by `max_files`/`max_chars`. A directory that
    alone exceeds either bound is split alphabetically."""
    by_dir: dict[str, list[FileInventory]] = {}
    for f in inventory:
        by_dir.setdefault(f.top_dir, []).append(f)
    for files in by_dir.values():
        files.sort(key=lambda f: f.rel_path)

    dir_pieces: list[list[FileInventory]] = []
    for top_dir in sorted(by_dir):
        files = by_dir[top_dir]
        start = 0
        while start < len(files):
            piece: list[FileInventory] = []
            chars = 0
            i = start
            while i < len(files) and len(piece) < max_files and (not piece or chars + _file_cost(files[i]) <= max_chars):
                chars += _file_cost(files[i])
                piece.append(files[i])
                i += 1
            if not piece:  # a single file alone exceeds max_chars; keep it anyway
                piece = [files[start]]
                i = start + 1
            dir_pieces.append(piece)
            start = i

    packed: list[list[FileInventory]] = []
    current: list[FileInventory] = []
    current_chars = 0
    for piece in dir_pieces:
        piece_chars = sum(_file_cost(f) for f in piece)
        if current and (len(current) + len(piece) > max_files or current_chars + piece_chars > max_chars):
            packed.append(current)
            current, current_chars = [], 0
        current.extend(piece)
        current_chars += piece_chars
    if current:
        packed.append(current)
    return packed
