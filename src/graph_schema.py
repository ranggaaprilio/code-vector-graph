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
}


def validate_node(label: str, properties: dict) -> bool:
    if label not in NODE_PROPERTIES:
        logger.warning(f"Unknown node label: {label}")
        return False

    schema = NODE_PROPERTIES[label]
    required_props = set(schema.keys())

    missing = required_props - set(properties.keys())
    if missing:
        logger.debug(f"Missing required properties for {label}: {missing}")
        return False

    for prop_name, prop_value in properties.items():
        if prop_name not in schema:
            continue

        expected_type = schema[prop_name]
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
    return set(NODE_PROPERTIES[label].keys())
