from scripts.reinit_neo4j_from_qdrant import point_to_graph


def test_point_to_graph_builds_file_chunk_and_metadata_nodes():
    payload = {
        "file_path": "/repo/src/app.ts",
        "language": "typescript",
        "file_hash": "abc123",
        "start_line": 10,
        "end_line": 20,
        "chunk_index": 1,
        "total_chunks": 3,
        "function_name": "handleRequest",
        "class_name": "Controller",
        "imports": ["express"],
        "exports": ["handleRequest"],
        "symbols_defined": ["result"],
        "call_sites": ["sendResponse"],
        "is_exported": True,
        "visibility": "public",
        "nesting_depth": 2,
        "token_count": 42,
        "decorators": ["Route"],
    }

    graph_data = point_to_graph("point-1", payload)

    labels = {node["label"] for node in graph_data["nodes"]}
    rel_types = {rel["type"] for rel in graph_data["relationships"]}

    assert {"File", "Chunk", "Class", "Function", "Import", "Variable"} <= labels
    assert {"CONTAINS", "DEFINES", "IMPORTS", "DEPENDS_ON", "EXPORTS", "CALLS"} <= rel_types

    chunk = next(node for node in graph_data["nodes"] if node["label"] == "Chunk")
    assert chunk["id"] == "point-1"
    assert chunk["properties"]["qdrant_id"] == "point-1"
    assert chunk["properties"]["function_name"] == "handleRequest"
    assert chunk["properties"]["token_count"] == 42


def test_point_to_graph_skips_points_without_file_path():
    graph_data = point_to_graph("point-1", {"function_name": "missingFile"})

    assert graph_data == {"nodes": [], "relationships": []}


def test_point_to_graph_prefers_authoritative_graph_payload():
    graph_nodes = [
        {"label": "File", "id": "file-1", "properties": {"path": "/repo/a.ts"}},
    ]
    graph_relationships = [
        {"type": "CONTAINS", "source_id": "file-1", "target_id": "chunk-1", "properties": {}},
    ]

    graph_data = point_to_graph(
        "point-1",
        {
            "function_name": "fallbackShouldNotBeUsed",
            "graph_nodes": graph_nodes,
            "graph_relationships": graph_relationships,
        },
    )

    assert graph_data == {"nodes": graph_nodes, "relationships": graph_relationships}
