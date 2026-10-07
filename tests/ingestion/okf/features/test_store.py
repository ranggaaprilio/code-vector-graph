"""Tests for Neo4j/Qdrant IO of Feature pages (stores mocked — no DB/network)."""

from unittest.mock import MagicMock

from code_vector_graph.ingestion.okf.features.models import EntryPoint, FeatureDoc, FeatureFrontmatter, FeaturePage
from code_vector_graph.ingestion.okf.features.store import (
    build_feature_chunks,
    build_feature_graph,
    delete_feature,
    feature_id_for,
    load_existing_features,
    save_feature_page,
    sync_features_neo4j,
    sync_features_qdrant,
)
from code_vector_graph.ingestion.okf.features.template import render_feature_markdown
from code_vector_graph.stores.graph_schema import validate_node

FID = feature_id_for("demo", "demo-repo", "user-login")


def _page(**overrides) -> FeaturePage:
    doc = FeatureDoc(
        title="User Login", description="Handles login.", overview="Lets users authenticate.",
        business_rules=["Password must match."], process_flow=["Submit.", "Verify."],
        entry_points=[EntryPoint(kind="Function", name="login", file="auth/login.js", line=1)],
    )
    body = render_feature_markdown(doc.title, doc)
    fm_kwargs = dict(
        title="User Login", slug="user-login", description="Handles login.",
        app="demo", repo="demo-repo", feature_id=FID, kind="user-facing",
        members_hash="abc1234567890def", member_files=["auth/login.js"], member_ids=["fnid-1"],
        source="llm", generated_at="2026-08-28T00:00:00Z", model="deepseek-v4-pro",
    )
    fm_kwargs.update(overrides)
    return FeaturePage(fm=FeatureFrontmatter(**fm_kwargs), body=body)


def test_feature_id_for_is_stable_and_scoped_by_repo():
    a = feature_id_for("demo", "repo-a", "checkout")
    b = feature_id_for("demo", "repo-b", "checkout")
    assert feature_id_for("demo", "repo-a", "checkout") == a
    assert a != b  # same app+slug, different repo -> different id


def test_build_feature_graph_produces_valid_wikipage_node():
    page = _page()
    nodes, rels, node_labels = build_feature_graph([page], {"fnid-1": "Function"}, repo_id="repo-id-1")
    assert len(nodes) == 1
    assert validate_node("WikiPage", nodes[0]["properties"])
    assert node_labels["fnid-1"] == "Function"
    assert node_labels[nodes[0]["id"]] == "WikiPage"


def test_build_feature_graph_documents_edge_points_at_repository():
    page = _page()
    nodes, rels, _ = build_feature_graph([page], {}, repo_id="repo-id-1")
    wid = nodes[0]["id"]
    documents = [r for r in rels if r["type"] == "DOCUMENTS"]
    assert documents == [{"type": "DOCUMENTS", "source_id": wid, "target_id": "repo-id-1", "properties": {}}]


def test_build_feature_graph_marks_entry_point_role_from_table():
    page = _page()  # entry point "auth/login.js" matches the one member file
    _, rels, _ = build_feature_graph([page], {}, repo_id="repo-id-1")
    implemented = [r for r in rels if r["type"] == "IMPLEMENTED_BY"]
    assert len(implemented) == 1
    assert implemented[0]["properties"]["role"] == "entry_point"


def test_build_feature_graph_marks_non_entry_point_member_as_member():
    page = _page(member_files=["auth/other.js"], member_ids=["fnid-2"])  # not the entry point's file
    _, rels, _ = build_feature_graph([page], {}, repo_id="repo-id-1")
    implemented = [r for r in rels if r["type"] == "IMPLEMENTED_BY"]
    assert implemented[0]["properties"]["role"] == "member"


def test_sync_features_neo4j_clears_old_implemented_by_edges_first():
    page = _page()
    gs = MagicMock()
    gs.query_graph.return_value = []
    gs.upsert_nodes.return_value = {"nodes_created": 1}
    gs.upsert_relationships.return_value = {"relationships_created": 2}
    stats = sync_features_neo4j([page], {"fnid-1": "Function"}, "repo-id-1", gs)
    assert stats == {
        "wiki_pages": 1, "implemented_by_edges": 1, "nodes_created": 1, "relationships_created": 2,
    }
    gs.create_constraints.assert_called_once()
    delete_call = gs.query_graph.call_args_list[0]
    assert "DELETE r" in delete_call.args[0]


def test_load_existing_features_keys_by_slug():
    gs = MagicMock()
    gs.query_graph.return_value = [
        {"wid": "w1", "feature_id": FID, "slug": "user-login", "source": "human",
         "members_hash": "old", "edited_members_hash": "old", "content": "body", "stale": False},
    ]
    existing = load_existing_features(gs, "demo", "demo-repo")
    assert set(existing) == {"user-login"}
    assert existing["user-login"].source == "human"
    assert existing["user-login"].stale is False


def test_load_existing_features_skips_records_without_slug():
    gs = MagicMock()
    gs.query_graph.return_value = [{"wid": "w1", "slug": None}]
    assert load_existing_features(gs, "demo", "demo-repo") == {}


def test_save_feature_page_returns_node_props():
    gs = MagicMock()
    gs.query_graph.return_value = [{"w": {"content": "new body", "source": "human", "id": "w1"}}]
    saved = save_feature_page(
        gs, FID, content="new body", title="User Login", summary="d", overview="ov",
        tags=["x"], source="human", now="2026-08-28T01:00:00Z", needs_reembed=False,
    )
    assert saved == {"content": "new body", "source": "human", "id": "w1"}


def test_save_feature_page_returns_none_when_not_found():
    gs = MagicMock()
    gs.query_graph.return_value = []
    assert save_feature_page(
        gs, "missing", content="x", title="X", summary="", overview="",
        tags=[], source="human", now="t", needs_reembed=False,
    ) is None


def test_delete_feature_removes_from_both_stores():
    gs, vs = MagicMock(), MagicMock()
    delete_feature(gs, vs, "w1", FID)
    gs.query_graph.assert_called_once()
    vs.delete_by_symbol_id.assert_called_once_with(FID)


def test_delete_feature_tolerates_missing_stores():
    delete_feature(None, None, "w1", FID)  # must not raise


def test_build_feature_chunks_tags_source_and_symbol_id():
    page = _page()
    chunks = build_feature_chunks([page], tokenizer_name="bert-base-uncased")
    assert chunks
    for ch in chunks:
        assert ch["source"] == "okf_wiki"
        assert ch["kind"] == "Feature"
        assert ch["symbol_id"] == FID
        assert ch["file_path"] == "feature/user-login"


def test_sync_features_qdrant_deletes_before_reembedding():
    page = _page()
    embedder = MagicMock()
    embedder.embed_chunks.side_effect = lambda chunks, batch_size=64: chunks
    vs = MagicMock()
    vs.upsert_chunks.return_value = ["p1"]
    stats = sync_features_qdrant([page], embedder, vs, tokenizer_name="bert-base-uncased")
    vs.delete_by_symbol_id.assert_called_once_with(FID)
    assert stats["stored"] == 1


def test_sync_features_qdrant_handles_empty_pages():
    embedder, vs = MagicMock(), MagicMock()
    assert sync_features_qdrant([], embedder, vs, tokenizer_name="bert-base-uncased") == {"chunks": 0, "stored": 0}
    embedder.embed_chunks.assert_not_called()
