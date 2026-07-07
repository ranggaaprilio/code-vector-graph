"""Tests for OKF Phase 2 sync (Qdrant + Neo4j), with stores/embedder mocked."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from src.graph_schema import validate_node
from src.okf.skeleton import build_skeleton, concept_name
from src.okf.render import write_bundle
from src.okf.enricher import fallback_enrichment
from src.okf.sync import (
    build_prose,
    build_wiki_chunks,
    build_wiki_graph,
    parse_bundle,
    sync_neo4j,
    sync_qdrant,
    wiki_id,
    _language_from_path,
)


def _make_bundle(tmp_path: Path) -> Path:
    """Build a small OKF bundle on disk (greet -> Related -> format)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.js").write_text(
        "export function greet(name) { return format(name); }\n"
        "function format(x) { return 'hi ' + x; }\n"
    )
    out = tmp_path / "wiki"
    sk = build_skeleton(str(repo))
    enrich = {}
    for nid in sk.concept_ids:
        node = sk.nodes[nid]
        e = fallback_enrichment(node)
        if node["label"] == "Function" and node["properties"]["name"] == "greet":
            e = {**e, "overview": "Greets someone.", "related": ["format"]}
        enrich[nid] = e
    write_bundle(str(out), sk, enrich, {"summary": "demo"}, repo_root=str(repo))
    return out


# --- parsing --------------------------------------------------------------

def test_parse_bundle_roundtrip(tmp_path):
    out = _make_bundle(tmp_path)
    concepts = parse_bundle(str(out))
    assert concepts
    for c in concepts:
        assert c["type"] and c["concept_id"] and c["path"]
    greet = next(c for c in concepts if c["title"] == "greet")
    assert greet["overview"] == "Greets someone."
    # the `## Related` link to format was captured
    assert any(p.startswith("function/") for p in greet["related_paths"])


def test_language_from_path():
    assert _language_from_path("src/a.ts#L1-L2") == "typescript"
    assert _language_from_path("b.js") == "javascript"
    assert _language_from_path("notes.md") == ""


def test_build_prose():
    c = {"title": "greet", "summary": "s", "overview": "o", "how_it_works": ""}
    assert build_prose(c) == "greet\n\ns\n\no"


# --- Neo4j ----------------------------------------------------------------

def test_build_wiki_graph_valid(tmp_path):
    concepts = parse_bundle(str(_make_bundle(tmp_path)))
    nodes, rels, node_labels = build_wiki_graph(concepts)

    assert nodes and all(n["label"] == "WikiPage" for n in nodes)
    for n in nodes:
        assert validate_node("WikiPage", n["properties"]), n
        assert node_labels[n["id"]] == "WikiPage"

    # one DOCUMENTS edge per page, pointing at the documented code node id
    docs = [r for r in rels if r["type"] == "DOCUMENTS"]
    assert len(docs) == len(nodes)
    a_page = next(c for c in concepts if c["title"] == "greet")
    assert any(r["source_id"] == wiki_id(a_page["concept_id"]) for r in docs)

    # the greet -> format Related link becomes a REFERENCES edge
    refs = [r for r in rels if r["type"] == "REFERENCES"]
    assert refs
    fmt = next(c for c in concepts if c["title"] == "format")
    assert any(r["target_id"] == wiki_id(fmt["concept_id"]) for r in refs)


def test_sync_neo4j_calls_store(tmp_path):
    concepts = parse_bundle(str(_make_bundle(tmp_path)))
    gs = MagicMock()
    gs.upsert_nodes.return_value = {"nodes_created": 3}
    gs.upsert_relationships.return_value = {"relationships_created": 4}

    stats = sync_neo4j(concepts, gs)

    gs.create_constraints.assert_called_once()
    nodes_arg = gs.upsert_nodes.call_args.args[0]
    assert all(n["label"] == "WikiPage" for n in nodes_arg)
    # relationships passed with a node_labels map
    assert "node_labels" in gs.upsert_relationships.call_args.kwargs
    assert stats["wiki_pages"] == len(nodes_arg)
    assert stats["nodes_created"] == 3


# --- Qdrant ---------------------------------------------------------------

def _fake_chunk_text(**kwargs):
    return [{"text": kwargs["text"], "metadata": {
        "file_path": kwargs.get("file_path", ""),
        "language": kwargs.get("language", ""),
        "start_line": 1, "end_line": 1, "chunk_index": 1,
        "function_name": None, "total_chunks": 0, "node_type": kwargs.get("node_type"),
        "class_name": kwargs.get("class_name"), "parent_function": None,
        "imports": None, "exports": None, "symbols_defined": None, "call_sites": None,
        "is_exported": False, "visibility": "unknown", "decorators": None, "file_hash": "",
    }}]


def test_build_wiki_chunks(tmp_path):
    concepts = parse_bundle(str(_make_bundle(tmp_path)))
    with patch("src.chunker.chunk_text", side_effect=_fake_chunk_text):
        chunks = build_wiki_chunks(concepts, tokenizer_name="fake")
    assert chunks
    for ch in chunks:
        assert ch["text_content"] == ch["text"]
        assert ch["source"] == "okf_wiki"
        assert ch["symbol_id"]      # concept id
        assert ch["id"]
        assert "embedding" not in ch  # not yet embedded


def test_sync_qdrant_calls_store(tmp_path):
    concepts = parse_bundle(str(_make_bundle(tmp_path)))
    embedder = MagicMock()
    embedder.embed_chunks.side_effect = lambda chunks, batch_size=64: [
        {**c, "embedding": [0.0, 0.0]} for c in chunks
    ]
    store = MagicMock()
    store.upsert_chunks.side_effect = lambda chunks: [c["id"] for c in chunks]

    with patch("src.chunker.chunk_text", side_effect=_fake_chunk_text):
        stats = sync_qdrant(concepts, embedder, store, tokenizer_name="fake")

    store.create_collection.assert_called_once()
    embedder.embed_chunks.assert_called_once()
    store.upsert_chunks.assert_called_once()
    # every upserted point carried an embedding
    upserted = store.upsert_chunks.call_args.args[0]
    assert all("embedding" in c for c in upserted)
    assert stats["chunks"] == stats["stored"] == len(upserted)
