"""Glossary extraction and graph enrichment helpers."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover - dependency is declared in requirements.txt
    yaml = None

logger = logging.getLogger(__name__)

NAMESPACE = uuid.NAMESPACE_URL
COMMENT_NODE_TYPES = {"comment", "line_comment", "block_comment"}
SYMBOL_LABEL_TO_KIND = {
    "Class": "class",
    "Field": "field",
    "Function": "function",
    "Method": "method",
    "Variable": "variable",
    "Interface": "interface",
    "TypeAlias": "type_alias",
}
KIND_ALIASES = {
    "typealias": "type_alias",
    "type-alias": "type_alias",
    "property": "field",
}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _glossary_id(file_path: str, kind: str, term: str, symbol_id: str = "") -> str:
    return str(uuid.uuid5(NAMESPACE, f"{file_path}:GlossaryEntry:{kind}:{term}:{symbol_id}"))


def normalize_kind(kind: Any) -> str:
    normalized = str(kind or "").strip().lower()
    return KIND_ALIASES.get(normalized, normalized)


def _normalize_path(file_path: Any, repo_path: str | None = None) -> str:
    if not file_path:
        return ""
    path = Path(str(file_path))
    if repo_path and not path.is_absolute():
        path = Path(repo_path) / path
    return str(path)


def _same_path(candidate: str, file_path: str) -> bool:
    if not candidate:
        return True
    if candidate == file_path:
        return True
    return file_path.endswith(candidate) or candidate.endswith(file_path)


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def load_manual_glossary(glossary_file: str | None, repo_path: str | None = None) -> list[dict[str, Any]]:
    """Load manual glossary entries from YAML. Missing files return an empty list."""
    if not glossary_file:
        return []

    path = Path(glossary_file)
    if not path.is_absolute() and repo_path:
        path = Path(repo_path) / path
    if not path.exists():
        logger.info("Glossary file not found, skipping: %s", path)
        return []
    if yaml is None:
        raise RuntimeError("PyYAML is required to read glossary files")

    with open(path, "r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    entries = raw.get("entries") if isinstance(raw, dict) else None
    if not isinstance(entries, list):
        logger.warning("Glossary file has no entries list: %s", path)
        return []

    normalized_entries = []
    for entry in entries:
        normalized = normalize_entry(entry, source_default="manual", repo_path=repo_path)
        if normalized:
            normalized_entries.append(normalized)
    return normalized_entries


def normalize_entry(
    entry: Any,
    source_default: str,
    repo_path: str | None = None,
) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        logger.warning("Skipping invalid glossary entry: %r", entry)
        return None

    term = str(entry.get("term") or "").strip()
    kind = normalize_kind(entry.get("kind"))
    summary = str(entry.get("summary") or "").strip()
    if not term or not kind or not summary:
        logger.warning("Skipping glossary entry missing term, kind, or summary: %r", entry)
        return None

    source = str(entry.get("source") or source_default).strip() or source_default
    confidence = _as_float(entry.get("confidence"), 1.0 if source == "manual" else 0.75)
    return {
        "term": term,
        "kind": kind,
        "summary": summary,
        "source": source,
        "confidence": confidence,
        "file_path": _normalize_path(entry.get("file_path"), repo_path),
        "symbol_id": str(entry.get("symbol_id") or ""),
        "created_at": str(entry.get("created_at") or ""),
        "updated_at": str(entry.get("updated_at") or ""),
    }


def _collect_comment_nodes(node, source_bytes: bytes, comments: list[dict[str, Any]]) -> None:
    if node.type in COMMENT_NODE_TYPES:
        comments.append({
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "text": source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace"),
        })
    for child in node.children:
        _collect_comment_nodes(child, source_bytes, comments)


def _clean_comment(comment: str) -> str:
    text = comment.strip()
    text = re.sub(r"^/\*\*", "", text)
    text = re.sub(r"^/\*", "", text)
    text = re.sub(r"\*/$", "", text)
    lines = []
    for line in text.splitlines():
        cleaned = re.sub(r"^\s*//\s?", "", line)
        cleaned = re.sub(r"^\s*\*\s?", "", cleaned).strip()
        if not cleaned or cleaned.startswith("@"):
            continue
        lines.append(cleaned)
    return " ".join(lines).strip()


def _symbol_nodes(graph_data: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    symbols = []
    for node in graph_data.get("nodes", []):
        label = node.get("label")
        kind = SYMBOL_LABEL_TO_KIND.get(label)
        if not kind:
            continue
        properties = node.get("properties", {})
        name = properties.get("name")
        if not name:
            continue
        symbols.append({
            "id": node.get("id", ""),
            "kind": kind,
            "term": str(name),
            "start_line": int(properties.get("start_line") or 0),
        })
    symbols.sort(key=lambda item: item["start_line"])
    return symbols


def extract_comment_glossary(
    tree,
    source_bytes: bytes,
    file_path: str,
    graph_data: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Extract comment/JSDoc summaries attached to the next nearby symbol."""
    if tree is None or source_bytes is None:
        return []

    comments: list[dict[str, Any]] = []
    _collect_comment_nodes(tree.root_node, source_bytes, comments)
    symbols = _symbol_nodes(graph_data)
    entries = []

    for comment in comments:
        summary = _clean_comment(comment["text"])
        if not summary:
            continue
        target = next(
            (
                symbol for symbol in symbols
                if symbol["start_line"] > comment["end_line"]
                and symbol["start_line"] - comment["end_line"] <= 2
            ),
            None,
        )
        if not target:
            continue
        entries.append({
            "term": target["term"],
            "kind": target["kind"],
            "summary": summary,
            "source": "comment",
            "confidence": 0.75,
            "file_path": file_path,
            "symbol_id": target["id"],
            "created_at": "",
            "updated_at": "",
        })

    return entries


def _entry_key(entry: dict[str, Any], file_path: str) -> tuple[str, str, str]:
    return (_normalize_path(entry.get("file_path")) or file_path, entry["kind"], entry["term"])


def _symbol_index(graph_data: dict[str, list[dict[str, Any]]]) -> dict[tuple[str, str], str]:
    indexed = {}
    for symbol in _symbol_nodes(graph_data):
        indexed[(symbol["kind"], symbol["term"])] = symbol["id"]
    return indexed


def build_glossary_graph(
    graph_data: dict[str, list[dict[str, Any]]],
    file_path: str,
    language: str,
    manual_entries: list[dict[str, Any]] | None = None,
    comment_entries: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Build glossary nodes, relationships, and Qdrant records for one file graph."""
    manual_entries = [
        entry for entry in (manual_entries or [])
        if _same_path(entry.get("file_path", ""), file_path)
    ]
    comment_entries = comment_entries or []

    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    for entry in comment_entries:
        normalized = normalize_entry(entry, source_default="comment")
        if normalized:
            merged[_entry_key(normalized, file_path)] = normalized
    for entry in manual_entries:
        normalized = normalize_entry(entry, source_default="manual")
        if normalized:
            key = _entry_key(normalized, file_path)
            merged[key] = normalized

    symbol_ids = _symbol_index(graph_data)
    created_at = _now()
    nodes = []
    relationships = []
    qdrant_records = []

    for entry in merged.values():
        symbol_id = entry.get("symbol_id") or symbol_ids.get((entry["kind"], entry["term"]), "")
        entry_file_path = entry.get("file_path") or file_path
        glossary_id = _glossary_id(entry_file_path, entry["kind"], entry["term"], symbol_id)
        properties = {
            "term": entry["term"],
            "kind": entry["kind"],
            "summary": entry["summary"],
            "source": entry["source"],
            "confidence": float(entry["confidence"]),
            "file_path": entry_file_path,
            "symbol_id": symbol_id,
            "created_at": entry.get("created_at") or created_at,
            "updated_at": entry.get("updated_at") or created_at,
        }
        nodes.append({
            "label": "GlossaryEntry",
            "id": glossary_id,
            "properties": properties,
        })
        if symbol_id:
            relationships.append({
                "type": "HAS_GLOSSARY",
                "source_id": symbol_id,
                "target_id": glossary_id,
                "properties": {},
            })
        qdrant_records.append({
            "id": glossary_id,
            "text": f"{entry['term']} ({entry['kind']}): {entry['summary']}",
            "text_content": f"{entry['term']} ({entry['kind']}): {entry['summary']}",
            "file_path": entry_file_path,
            "language": language,
            "start_line": 0,
            "end_line": 0,
            "chunk_index": 0,
            "total_chunks": 1,
            "function_name": None,
            "node_type": "glossary_entry",
            "class_name": None,
            "parent_function": None,
            "imports": [],
            "exports": [],
            "symbols_defined": [entry["term"]],
            "call_sites": [],
            "is_exported": False,
            "visibility": None,
            "nesting_depth": 0,
            "token_count": 0,
            "decorators": [],
            "file_hash": glossary_id,
            "graph_nodes": [],
            "graph_relationships": [],
            "term": entry["term"],
            "kind": entry["kind"],
            "summary": entry["summary"],
            "source": entry["source"],
            "confidence": float(entry["confidence"]),
            "symbol_id": symbol_id,
        })

    return nodes, relationships, qdrant_records
