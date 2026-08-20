"""Build an in-memory concept skeleton from the repository.

Reuses the existing, tested extraction stack (scanner -> parser ->
graph_extractor) so the wiki's concepts, ids, and edges match exactly what the
Neo4j pipeline produces. No database is required — Phase 1 reads the repo files
directly.

The skeleton provides everything enrichment and rendering need:
- the set of concepts to document (filtered by label, minus synthetic nodes),
- a stable, unique, human-readable concept path per concept (for links),
- a name -> concept-id index (for resolving CALLS/INHERITS/related links),
- a CONTAINS parent -> children map (for bottom-up context and `## Contains`).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from code_vector_graph.parsing.graph_extractor import extract_graph_entities
from code_vector_graph.parsing.parser import parse_file
from code_vector_graph.parsing.scanner import discover_files

logger = logging.getLogger(__name__)

# Label -> bundle subdirectory (also the OKF concept-path prefix).
DIR_FOR_LABEL = {
    "File": "file",
    "Class": "class",
    "Function": "function",
    "Method": "method",
    "Field": "field",
    "Variable": "variable",
    "Import": "import",
    "Interface": "interface",
    "TypeAlias": "typealias",
    "Module": "module",
    "Chunk": "chunk",
    "GlossaryEntry": "glossary",
}

# Concepts that get their own enriched wiki page by default. Imports/Variables/
# Fields are low-signal as standalone pages; they still inform links/tags.
DEFAULT_ENRICH_LABELS = ("File", "Class", "Function", "Method", "Interface", "TypeAlias")
DEFAULT_EXCLUDE_LABELS = ("Import", "Variable", "Field", "Chunk", "GlossaryEntry", "Module")

# graph_extractor fabricates placeholder nodes when a file has no real entity of
# a kind; those are noise in a wiki and are filtered out here.
_SYNTHETIC_NAMES = {"AnonymousClass", "anonymous"}
_SYNTHETIC_PREFIXES = ("AnonymousClass_", "AnonymousInterface_", "Alias_", "anon_method_")

# Priority for resolving a bare name to a single concept id (best definition first).
_NAME_PRIORITY = {"Function": 0, "Method": 1, "Class": 2, "Interface": 3, "TypeAlias": 4, "File": 5}


def dir_for_label(label: str) -> str:
    return DIR_FOR_LABEL.get(label, label.lower())


def slugify(text: str, maxlen: int = 60) -> str:
    """Filesystem-safe, human-readable slug: lowercase alnum runs joined by '-'."""
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:maxlen].rstrip("-")


def concept_name(node: dict) -> str:
    """Human name for a node, using the same fallback chain as the dashboard."""
    props = node.get("properties", {}) or {}
    if node.get("label") == "File":
        path = props.get("path", "") or ""
        return Path(path).name or path
    return props.get("name") or props.get("term") or props.get("module") or ""


def is_synthetic(node: dict) -> bool:
    """True for placeholder nodes the extractor fabricates as fallbacks."""
    name = concept_name(node)
    if name in _SYNTHETIC_NAMES:
        return True
    if any(name.startswith(p) for p in _SYNTHETIC_PREFIXES):
        return True
    props = node.get("properties", {}) or {}
    if node.get("label") == "Import" and props.get("module") == "./module":
        return True
    return not name


def _build_concept_paths(concepts: list[dict]) -> dict[str, str]:
    """Assign each concept a unique, stable, human-readable path `dir/slug-hash`.

    Deterministic: sort by id, extend the id-hash slice on collision. Two
    same-named symbols in different files therefore get distinct paths.
    """
    used: set[str] = set()
    mapping: dict[str, str] = {}
    for node in sorted(concepts, key=lambda n: n["id"]):
        d = dir_for_label(node["label"])
        base = slugify(concept_name(node)) or d
        nid = node["id"]
        candidate = f"{d}/{base}-{nid[:8]}"
        for n in (8, 12, 16, 36):
            candidate = f"{d}/{base}-{nid[:n]}"
            if candidate not in used:
                break
        used.add(candidate)
        mapping[nid] = candidate
    return mapping


@dataclass
class Skeleton:
    repo_path: str
    nodes: dict[str, dict]              # id -> node (non-synthetic; may include non-enriched)
    concept_ids: list[str]             # ids to enrich, in stable order
    id_to_path: dict[str, str]         # concept id -> "dir/slug-hash"
    name_to_id: dict[str, str]         # bare name -> concept id
    contains: dict[str, list[str]]     # parent id -> child ids (enriched children)
    files: list[dict] = field(default_factory=list)

    def path_for(self, node_id: str) -> Optional[str]:
        return self.id_to_path.get(node_id)

    def resolve_name(self, name: str) -> Optional[str]:
        """Concept id for a bare symbol name, or None."""
        return self.name_to_id.get(name)


def build_skeleton(
    repo_path: str,
    labels: Optional[Iterable[str]] = None,
    exclude_labels: Optional[Iterable[str]] = None,
    limit: Optional[int] = None,
) -> Skeleton:
    """Discover, parse, and extract the concept graph for `repo_path`."""
    enrich_labels = set(labels) if labels else set(DEFAULT_ENRICH_LABELS)
    excluded = set(exclude_labels) if exclude_labels is not None else set(DEFAULT_EXCLUDE_LABELS)
    enrich_labels -= excluded

    files = discover_files(repo_path)
    nodes: dict[str, dict] = {}
    contains_all: dict[str, list[str]] = {}
    files_info: list[dict] = []

    for finfo in files:
        parsed = parse_file(finfo["path"], finfo["grammar"])
        if parsed is None:
            logger.warning("Skipping unparseable file: %s", finfo["path"])
            continue
        data = extract_graph_entities(
            parsed["tree"],
            parsed["source_bytes"],
            finfo["path"],
            finfo["language"],
            finfo.get("file_hash", ""),
        )
        fmeta = {
            "path": finfo["path"],
            "language": finfo["language"],
            "file_hash": finfo.get("file_hash", ""),
        }
        for n in data["nodes"]:
            if is_synthetic(n):
                continue
            n.setdefault("_file", fmeta)
            nodes.setdefault(n["id"], n)
        for rel in data["relationships"]:
            if rel.get("type") == "CONTAINS":
                contains_all.setdefault(rel["source_id"], []).append(rel["target_id"])
        files_info.append(fmeta)

    # Concepts to enrich (filtered by label), stable order, optional cap.
    concepts = [n for n in nodes.values() if n["label"] in enrich_labels]
    concepts.sort(key=lambda n: (DIR_FOR_LABEL.get(n["label"], n["label"]), concept_name(n), n["id"]))
    if limit is not None and limit > 0:
        concepts = concepts[:limit]
    concept_id_set = {n["id"] for n in concepts}

    id_to_path = _build_concept_paths(concepts)

    # name -> concept id, best definition wins (deterministic on ties).
    name_to_id: dict[str, str] = {}
    for node in sorted(concepts, key=lambda n: (_NAME_PRIORITY.get(n["label"], 9), n["id"])):
        nm = concept_name(node)
        name_to_id.setdefault(nm, node["id"])

    # CONTAINS map restricted to enriched endpoints.
    contains: dict[str, list[str]] = {}
    for parent_id, child_ids in contains_all.items():
        if parent_id not in concept_id_set:
            continue
        kept = [c for c in child_ids if c in concept_id_set]
        if kept:
            contains[parent_id] = kept

    logger.info(
        "Skeleton: %d files, %d concepts (%s)",
        len(files_info),
        len(concepts),
        ", ".join(sorted(enrich_labels)),
    )
    return Skeleton(
        repo_path=repo_path,
        nodes=nodes,
        concept_ids=[n["id"] for n in concepts],
        id_to_path=id_to_path,
        name_to_id=name_to_id,
        contains=contains,
        files=files_info,
    )
