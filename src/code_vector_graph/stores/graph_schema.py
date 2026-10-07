"""
Neo4j code ontology schema.
"""

from __future__ import annotations

import logging
import types
from typing import get_origin, get_args

logger = logging.getLogger(__name__)

NODE_LABELS = frozenset([
    "File",
    "Module",
    "Class",
    "Function",
    "Method",
    "Field",
    "Variable",
    "Import",
    "Interface",
    "TypeAlias",
    "Chunk",
    "GlossaryEntry",
    "WikiPage",
    # Application / repository identity (see repos.py). One Application
    # CONTAINS many Repository nodes; a Repository CONTAINS its File nodes.
    "Application",
    "Repository",
])

# Relationship types for the code ontology
RELATIONSHIP_TYPES = frozenset([
    "CONTAINS",
    "CALLS",
    "IMPORTS",
    "INHERITS",
    "EXPORTS",
    "REFERENCES",
    "DEFINES",
    "TYPE_OF",
    "DEPENDS_ON",
    "HAS_GLOSSARY",
    "DOCUMENTS",
    # WikiPage {type:"Feature"} -> code node it documents (one edge per member).
    "IMPLEMENTED_BY",
    # WikiPage {type:"Document"} -> File it names in its body (auto-detected).
    "MENTIONS",
])

# Node property schemas keyed by label
NODE_PROPERTIES = {
    "File": {
        "path": str,
        "language": str,
        "file_hash": str,
        "line_count": int,
        "exports": list[str],
        "imports": list[str],
        # Identity (optional; absent on legacy nodes indexed before Phase 4).
        "app": str | None,
        "repo": str | None,
        "rel_path": str | None,
    },
    "Module": {
        "name": str,
        "path": str,
        "is_package": bool,
    },
    "Class": {
        "name": str,
        "start_line": int,
        "end_line": int,
        "is_exported": bool,
        "visibility": str,
        "decorators": list[str],
        "parent_class": str | None,
    },
    "Function": {
        "name": str,
        "start_line": int,
        "end_line": int,
        "is_exported": bool,
        "visibility": str,
        "parameters": list[str],
        "decorators": list[str],
        "is_async": bool,
        "parent_function": str | None,
        "call_sites": list[str],
    },
    "Method": {
        "name": str,
        "start_line": int,
        "end_line": int,
        "is_exported": bool,
        "visibility": str,
        "parameters": list[str],
        "decorators": list[str],
        "is_async": bool,
        "parent_class": str | None,
        "call_sites": list[str],
    },
    "Field": {
        "name": str,
        "start_line": int,
        "end_line": int,
        "is_exported": bool,
        "visibility": str,
        "type_annotation": str | None,
        "parent_class": str | None,
    },
    "Variable": {
        "name": str,
        "start_line": int,
        "end_line": int,
        "is_exported": bool,
        "visibility": str,
        "is_constant": bool,
        "type_annotation": str | None,
    },
    "Import": {
        "module": str,
        "names": list[str],
        "start_line": int,
        "end_line": int,
        "is_wildcard": bool,
    },
    "Interface": {
        "name": str,
        "start_line": int,
        "end_line": int,
        "is_exported": bool,
        "extends": list[str],
    },
    "TypeAlias": {
        "name": str,
        "start_line": int,
        "end_line": int,
        "is_exported": bool,
        "type_expression": str,
    },
    "Chunk": {
        "qdrant_id": str,
        "file_path": str,
        "start_line": int,
        "end_line": int,
        "chunk_index": int,
        "total_chunks": int,
        "function_name": str | None,
        "class_name": str | None,
        "parent_function": str | None,
        "imports": list[str],
        "exports": list[str],
        "symbols_defined": list[str],
        "call_sites": list[str],
        "is_exported": bool,
        "visibility": str | None,
        "nesting_depth": int,
        "token_count": int,
        "decorators": list[str],
        "file_hash": str,
        "repo": str | None,
    },
    "GlossaryEntry": {
        "term": str,
        "kind": str,
        "summary": str,
        "source": str,
        "confidence": float,
        "file_path": str,
        "symbol_id": str,
        "created_at": str,
        "updated_at": str,
    },
    # OKF "LLM wiki" page. Documents a code node (concept_id) with enriched,
    # human-readable content; linked to that node via a DOCUMENTS relationship
    # and to other wiki pages via REFERENCES.
    "WikiPage": {
        "concept_id": str,
        "path": str,
        "type": str,
        "title": str,
        "summary": str,
        "overview": str,
        "tags": list[str],
        "resource": str,
        "source": str,
        "repo": str | None,
        "app": str | None,
        "how_it_works": str | None,
        # Feature-page fields (type == "Feature"). Absent on symbol/file/repo pages.
        "slug": str | None,
        "content": str | None,
        "kind": str | None,
        "members_hash": str | None,
        "edited_members_hash": str | None,
        "member_files": list[str],
        "member_count": int | None,
        "stale": bool | None,
        "stale_since": str | None,
        "generated_at": str | None,
        "edited_at": str | None,
        "model": str | None,
        "language": str | None,
        "draft": str | None,
        "draft_generated_at": str | None,
        "needs_reembed": bool | None,
        # Document-page fields (type == "Document"). Absent on other page types.
        "category": str | None,
        "created_at": str | None,
        "word_count": int | None,
        "source_file": str | None,
        "mentions": list[str],
    },
    "Application": {
        "name": str,
    },
    "Repository": {
        "name": str,
        "root": str,
        "app": str,
        "indexed_at": str,
    },
}

# Properties that may be absent from a node of the given label. Everything else
# in NODE_PROPERTIES[label] is required. Optional properties are still
# type-checked when present; ``None`` is always accepted for them.
OPTIONAL_NODE_PROPERTIES: dict[str, frozenset[str]] = {
    "File": frozenset({"app", "repo", "rel_path"}),
    "Chunk": frozenset({"repo"}),
    "WikiPage": frozenset({
        "repo", "app", "how_it_works",
        "slug", "content", "kind", "members_hash", "edited_members_hash",
        "member_files", "member_count", "stale", "stale_since",
        "generated_at", "edited_at", "model", "language",
        "draft", "draft_generated_at", "needs_reembed",
        "category", "created_at", "word_count", "source_file", "mentions",
    }),
    "Repository": frozenset({"indexed_at", "app"}),
}


def validate_node(label: str, properties: dict) -> bool:
    if label not in NODE_PROPERTIES:
        logger.warning(f"Unknown node label: {label}")
        return False

    schema = NODE_PROPERTIES[label]
    optional = OPTIONAL_NODE_PROPERTIES.get(label, frozenset())
    required_props = set(schema.keys()) - optional

    missing = required_props - set(properties.keys())
    if missing:
        logger.debug(f"Missing required properties for {label}: {missing}")
        return False

    for prop_name, prop_value in properties.items():
        if prop_name not in schema:
            continue

        expected_type = schema[prop_name]
        if prop_value is None and prop_name in optional:
            continue
        if isinstance(expected_type, types.UnionType):
            if prop_value is not None and not isinstance(prop_value, get_args(expected_type)):
                return False
        elif get_origin(expected_type):
            if not isinstance(prop_value, get_origin(expected_type)):
                return False
        else:
            if not isinstance(prop_value, expected_type):
                return False

    return True


def get_required_properties(label: str) -> set[str]:
    if label not in NODE_PROPERTIES:
        return set()
    return set(NODE_PROPERTIES[label].keys()) - OPTIONAL_NODE_PROPERTIES.get(label, frozenset())
