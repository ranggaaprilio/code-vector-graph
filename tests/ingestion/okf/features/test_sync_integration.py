"""Tests for Feature-page support in ingestion/okf/sync.py (bundle round-trip).

Covers the disk re-import path (e.g. after `cvg-reinit-graph --clear`), which
must recognize `type: Feature` pages the same way `features/build.py`'s
in-process sync does, via `features/store.py:build_feature_graph`.
"""

from pathlib import Path

from code_vector_graph.ingestion.okf.features.models import EntryPoint, FeatureDoc, FeatureFrontmatter
from code_vector_graph.ingestion.okf.features.store import feature_id_for
from code_vector_graph.ingestion.okf.features.template import compose_page, render_feature_markdown
from code_vector_graph.ingestion.okf.sync import build_wiki_chunks, build_wiki_graph, parse_bundle
from code_vector_graph.repos import RepoIdentity
from code_vector_graph.stores.graph_schema import validate_node

ROOT_INDEX = (
    "---\ntype: Repository\nokf_version: '0.1'\ntitle: demo\nrepo: demo-repo\napp: demo\n"
    "node_id: repo-id-xyz\ndescription: d\nsource: llm\ntimestamp: t\n---\n\n"
    "# demo\n\n# Architecture Overview\nhi\n\n# How it fits together\nhi\n\n# Contents\n"
)


def _write_feature_bundle(tmp_path: Path) -> tuple[Path, str]:
    bundle = tmp_path / "wiki"
    (bundle / "feature").mkdir(parents=True)
    (bundle / "index.md").write_text(ROOT_INDEX)

    fid = feature_id_for("demo", "demo-repo", "user-login")
    doc = FeatureDoc(
        title="User Login",
        description="Handles login.",
        overview="Lets users authenticate.",
        business_rules=["Password must match."],
        process_flow=["Submit.", "Verify."],
        entry_points=[EntryPoint(kind="Function", name="login", file="auth/login.js", line=1)],
    )
    body = render_feature_markdown(doc.title, doc)
    fm = FeatureFrontmatter(
        title="User Login", slug="user-login", description="Handles login.",
        app="demo", repo="demo-repo", feature_id=fid, kind="user-facing",
        members_hash="abc1234567890def", member_files=["auth/login.js"], member_ids=["fnid-1"],
        source="llm", generated_at="2026-08-28T00:00:00Z", model="deepseek-v4-pro",
    )
    (bundle / "feature" / "user-login.md").write_text(compose_page(fm, body))
    # A per-directory listing, same as file/index.md, class/index.md, etc. —
    # must be skipped by parse_bundle just like those are.
    (bundle / "feature" / "index.md").write_text("# Features\n- [User Login](/feature/user-login.md)\n")
    return bundle, fid


def test_parse_bundle_recognizes_feature_pages(tmp_path):
    bundle, fid = _write_feature_bundle(tmp_path)
    concepts = parse_bundle(str(bundle))
    types = sorted(c["type"] for c in concepts)
    assert types == ["Feature", "Repository"]  # feature/index.md was skipped

    feature = next(c for c in concepts if c["type"] == "Feature")
    assert feature["concept_id"] == fid
    assert feature["slug"] == "user-login"
    assert feature["member_ids"] == ["fnid-1"]
    assert feature["member_files"] == ["auth/login.js"]
    assert "Lets users authenticate" in feature["overview"]


def test_build_wiki_graph_creates_implemented_by_and_documents_edges(tmp_path):
    bundle, fid = _write_feature_bundle(tmp_path)
    concepts = parse_bundle(str(bundle))

    nodes, rels, node_labels = build_wiki_graph(concepts)
    feature_node = next(n for n in nodes if n["properties"]["type"] == "Feature")
    assert validate_node("WikiPage", feature_node["properties"])

    expected_repo_id = RepoIdentity(app="demo", name="demo-repo", root="").id
    assert any(
        r["type"] == "DOCUMENTS" and r["target_id"] == expected_repo_id and r["source_id"] == feature_node["id"]
        for r in rels
    )
    assert any(r["type"] == "IMPLEMENTED_BY" and r["target_id"] == "fnid-1" for r in rels)
    # Feature pages never get a code-node DOCUMENTS edge (that would collide
    # with the "exactly one documented node" contract other pages rely on).
    assert not any(r["type"] == "DOCUMENTS" and r["target_id"] == fid for r in rels)


def test_build_wiki_chunks_embeds_feature_body(tmp_path):
    bundle, fid = _write_feature_bundle(tmp_path)
    concepts = parse_bundle(str(bundle))

    chunks = build_wiki_chunks(concepts, tokenizer_name="bert-base-uncased")
    feature_chunks = [c for c in chunks if c["kind"] == "Feature"]
    assert feature_chunks
    assert feature_chunks[0]["symbol_id"] == fid
    assert feature_chunks[0]["source"] == "okf_wiki"
    assert feature_chunks[0]["file_path"] == "feature/user-login"
