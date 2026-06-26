"""Reinitialize Neo4j graph data from Qdrant chunk payloads."""

from __future__ import annotations

import argparse
import logging
import sys
import uuid
from pathlib import Path
from typing import Any, Iterable

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv()

from src.config import (
    DEFAULT_COLLECTION_NAME,
    DEFAULT_QDRANT_URL,
    EMBEDDING_DIMENSIONS,
    NEO4J_DATABASE,
    NEO4J_PASSWORD,
    NEO4J_URI,
    NEO4J_USER,
)
from src.graph_store import GraphStore
from src.store import VectorStore, get_collection_name

logger = logging.getLogger(__name__)

BATCH_SIZE = 500
NAMESPACE = uuid.NAMESPACE_URL


def _node_id(file_path: str, label: str, name: str, start_line: int) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{file_path}:{label}:{name}:{start_line}"))


def _rel(
    rel_type: str,
    source_id: str,
    target_id: str,
    properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": rel_type,
        "source_id": source_id,
        "target_id": target_id,
        "properties": properties or {},
    }


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _dedupe(items: Iterable[dict[str, Any]], key_fields: tuple[str, ...]) -> list[dict[str, Any]]:
    seen = set()
    result = []
    for item in items:
        key = tuple(item.get(field) for field in key_fields)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def point_to_graph(point_id: str, payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Convert one Qdrant point payload into Neo4j graph nodes and relationships."""
    if payload.get("graph_nodes") or payload.get("graph_relationships"):
        return {
            "nodes": payload.get("graph_nodes") or [],
            "relationships": payload.get("graph_relationships") or [],
        }

    file_path = payload.get("file_path")
    if not file_path:
        logger.warning("Skipping Qdrant point without file_path: %s", point_id)
        return {"nodes": [], "relationships": []}

    language = payload.get("language", "")
    file_hash = payload.get("file_hash", "")
    start_line = int(payload.get("start_line") or 0)
    end_line = int(payload.get("end_line") or start_line)
    chunk_index = int(payload.get("chunk_index") or 0)
    total_chunks = int(payload.get("total_chunks") or 0)

    imports = [str(item) for item in _as_list(payload.get("imports")) if item]
    exports = [str(item) for item in _as_list(payload.get("exports")) if item]
    symbols_defined = [str(item) for item in _as_list(payload.get("symbols_defined")) if item]
    call_sites = [str(item) for item in _as_list(payload.get("call_sites")) if item]
    decorators = [str(item) for item in _as_list(payload.get("decorators")) if item]

    file_id = _node_id(file_path, "File", file_path, 1)
    chunk_id = str(point_id)
    nodes = [
        {
            "label": "File",
            "id": file_id,
            "properties": {
                "path": file_path,
                "language": language,
                "file_hash": file_hash,
                "line_count": max(end_line, 0),
                "exports": exports,
                "imports": imports,
            },
        },
        {
            "label": "Chunk",
            "id": chunk_id,
            "properties": {
                "qdrant_id": chunk_id,
                "file_path": file_path,
                "start_line": start_line,
                "end_line": end_line,
                "chunk_index": chunk_index,
                "total_chunks": total_chunks,
                "function_name": payload.get("function_name"),
                "class_name": payload.get("class_name"),
                "parent_function": payload.get("parent_function"),
                "imports": imports,
                "exports": exports,
                "symbols_defined": symbols_defined,
                "call_sites": call_sites,
                "is_exported": bool(payload.get("is_exported", False)),
                "visibility": payload.get("visibility"),
                "nesting_depth": int(payload.get("nesting_depth") or 0),
                "token_count": int(payload.get("token_count") or 0),
                "decorators": decorators,
                "file_hash": file_hash,
            },
        },
    ]
    relationships = [_rel("CONTAINS", file_id, chunk_id)]

    class_name = payload.get("class_name")
    if class_name:
        class_id = _node_id(file_path, "Class", str(class_name), start_line or 1)
        nodes.append({
            "label": "Class",
            "id": class_id,
            "properties": {
                "name": str(class_name),
                "start_line": start_line,
                "end_line": end_line,
                "is_exported": str(class_name) in exports,
                "visibility": payload.get("visibility") or "private",
                "decorators": decorators,
                "parent_class": None,
            },
        })
        relationships.extend([
            _rel("CONTAINS", file_id, class_id),
            _rel("DEFINES", file_id, class_id),
            _rel("CONTAINS", class_id, chunk_id),
        ])

    function_name = payload.get("function_name") or payload.get("parent_function")
    function_id = None
    if function_name:
        function_id = _node_id(file_path, "Function", str(function_name), start_line or 1)
        nodes.append({
            "label": "Function",
            "id": function_id,
            "properties": {
                "name": str(function_name),
                "start_line": start_line,
                "end_line": end_line,
                "is_exported": str(function_name) in exports,
                "visibility": payload.get("visibility") or "private",
                "parameters": [],
                "decorators": decorators,
                "is_async": False,
                "parent_function": payload.get("parent_function"),
                "call_sites": call_sites,
            },
        })
        relationships.extend([
            _rel("CONTAINS", file_id, function_id),
            _rel("DEFINES", file_id, function_id),
            _rel("CONTAINS", function_id, chunk_id),
        ])

    for module in imports:
        import_id = _node_id(file_path, "Import", module, start_line or 1)
        nodes.append({
            "label": "Import",
            "id": import_id,
            "properties": {
                "module": module,
                "names": [],
                "start_line": start_line,
                "end_line": start_line,
                "is_wildcard": module == "*",
            },
        })
        relationships.extend([
            _rel("CONTAINS", file_id, import_id),
            _rel("IMPORTS", file_id, import_id),
            _rel("DEPENDS_ON", file_id, import_id),
        ])

    for symbol in symbols_defined:
        variable_id = _node_id(file_path, "Variable", symbol, start_line or 1)
        nodes.append({
            "label": "Variable",
            "id": variable_id,
            "properties": {
                "name": symbol,
                "start_line": start_line,
                "end_line": end_line,
                "is_exported": symbol in exports,
                "visibility": "public" if symbol in exports else "private",
                "is_constant": False,
                "type_annotation": None,
            },
        })
        relationships.extend([
            _rel("CONTAINS", file_id, variable_id),
            _rel("DEFINES", file_id, variable_id),
        ])

    for export_name in exports:
        for node in nodes:
            if node["label"] in ("Class", "Function", "Variable"):
                if node["properties"].get("name") == export_name:
                    relationships.append(_rel("EXPORTS", file_id, node["id"]))
                    break

    if function_id:
        for callee in call_sites:
            callee_id = _node_id(file_path, "Function", callee, 1)
            nodes.append({
                "label": "Function",
                "id": callee_id,
                "properties": {
                    "name": callee,
                    "start_line": 1,
                    "end_line": 1,
                    "is_exported": callee in exports,
                    "visibility": "private",
                    "parameters": [],
                    "decorators": [],
                    "is_async": False,
                    "parent_function": None,
                    "call_sites": [],
                },
            })
            relationships.append(_rel("CALLS", function_id, callee_id))

    return {
        "nodes": _dedupe(nodes, ("label", "id")),
        "relationships": _dedupe(relationships, ("type", "source_id", "target_id")),
    }


def iter_qdrant_points(vector_store: VectorStore, batch_size: int):
    offset = None
    while True:
        points, offset = vector_store.client.scroll(
            collection_name=vector_store.collection_name,
            limit=batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        if not points:
            break
        for point in points:
            yield point
        if offset is None:
            break


def flush_graph_batch(graph_store: GraphStore, nodes: list[dict[str, Any]],
                      relationships: list[dict[str, Any]]) -> dict[str, int]:
    node_counts = graph_store.upsert_nodes(nodes)
    node_labels = {
        n["id"]: n["label"] for n in nodes if n.get("id") and n.get("label")
    }
    relationship_counts = graph_store.upsert_relationships(
        relationships, node_labels=node_labels
    )
    return {
        "nodes_created": node_counts["nodes_created"],
        "relationships_created": relationship_counts["relationships_created"],
        "nodes_attempted": node_counts["attempted_nodes"],
        "relationships_attempted": relationship_counts["attempted_relationships"],
    }


def rebuild_neo4j_from_qdrant(args: argparse.Namespace) -> dict[str, int]:
    collection_name = args.collection_name
    if not args.collection_name_is_final:
        collection_name = get_collection_name(args.collection_name, "huggingface")

    vector_store = VectorStore(
        collection_name=collection_name,
        qdrant_url=args.qdrant_url,
        embedding_dimensions=EMBEDDING_DIMENSIONS,
    )
    if not vector_store.check_health():
        raise RuntimeError(f"Cannot connect to Qdrant at {args.qdrant_url}")

    graph_store = GraphStore(
        uri=args.neo4j_uri,
        user=args.neo4j_user,
        password=args.neo4j_password,
        database=args.neo4j_database,
    )
    if not graph_store.check_health():
        graph_store.close()
        raise RuntimeError(f"Cannot connect to Neo4j at {args.neo4j_uri}")

    stats = {
        "points_read": 0,
        "nodes_attempted": 0,
        "relationships_attempted": 0,
        "nodes_created": 0,
        "relationships_created": 0,
    }

    try:
        if args.clear:
            logger.info("Clearing existing Neo4j data")
            graph_store.query_graph("MATCH (n) DETACH DELETE n")

        graph_store.create_constraints()

        nodes: list[dict[str, Any]] = []
        relationships: list[dict[str, Any]] = []

        for point in iter_qdrant_points(vector_store, args.batch_size):
            graph_data = point_to_graph(str(point.id), point.payload or {})
            stats["points_read"] += 1
            nodes.extend(graph_data["nodes"])
            relationships.extend(graph_data["relationships"])

            if len(nodes) >= args.batch_size:
                counts = flush_graph_batch(graph_store, nodes, relationships)
                for key, value in counts.items():
                    stats[key] += value
                nodes.clear()
                relationships.clear()

        if nodes or relationships:
            counts = flush_graph_batch(graph_store, nodes, relationships)
            for key, value in counts.items():
                stats[key] += value

        return stats
    finally:
        graph_store.close()


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reinitialize Neo4j graph data from existing Qdrant chunk payloads.",
    )
    parser.add_argument(
        "--qdrant-url",
        default=DEFAULT_QDRANT_URL,
        help=f"Qdrant server URL (default: {DEFAULT_QDRANT_URL})",
    )
    parser.add_argument(
        "--collection-name",
        default=DEFAULT_COLLECTION_NAME,
        help=(
            "Base Qdrant collection name. By default this is expanded using the "
            "same naming convention as main.py."
        ),
    )
    parser.add_argument(
        "--collection-name-is-final",
        action="store_true",
        help="Use --collection-name exactly as provided instead of expanding it.",
    )
    parser.add_argument(
        "--neo4j-uri",
        default=NEO4J_URI,
        help=f"Neo4j bolt URI (default: {NEO4J_URI})",
    )
    parser.add_argument(
        "--neo4j-user",
        default=NEO4J_USER,
        help=f"Neo4j username (default: {NEO4J_USER})",
    )
    parser.add_argument(
        "--neo4j-password",
        default=NEO4J_PASSWORD,
        help="Neo4j password",
    )
    parser.add_argument(
        "--neo4j-database",
        default=NEO4J_DATABASE,
        help=f"Neo4j database name (default: {NEO4J_DATABASE})",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=BATCH_SIZE,
        help=f"Qdrant scroll and Neo4j write batch size (default: {BATCH_SIZE})",
    )
    parser.add_argument(
        "--no-clear",
        dest="clear",
        action="store_false",
        help="Do not delete existing Neo4j data before rebuilding.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print progress info.",
    )
    parser.set_defaults(clear=True)
    return parser


def main() -> int:
    parser = create_parser()
    args = parser.parse_args()
    if args.batch_size <= 0:
        parser.error(f"Batch size must be positive, got: {args.batch_size}")

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    try:
        stats = rebuild_neo4j_from_qdrant(args)
    except Exception as exc:
        logger.exception("Failed to rebuild Neo4j from Qdrant")
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("Neo4j reinitialization complete")
    print(f"  Qdrant points read:       {stats['points_read']}")
    print(f"  Nodes attempted:          {stats['nodes_attempted']}")
    print(f"  Relationships attempted:  {stats['relationships_attempted']}")
    print(f"  Nodes created:            {stats['nodes_created']}")
    print(f"  Relationships created:    {stats['relationships_created']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
