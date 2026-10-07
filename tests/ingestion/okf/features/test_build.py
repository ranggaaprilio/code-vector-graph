"""Tests for the feature-doc build orchestrator (stores/LLM fully mocked)."""

import json
from pathlib import Path
from unittest.mock import MagicMock

from code_vector_graph.ingestion.okf.features.build import _members_hash, build_feature_docs
from code_vector_graph.ingestion.okf.features.inventory import build_inventory
from code_vector_graph.ingestion.okf.features.models import (
    FeatureBuildDeps,
    FeatureBuildRequest,
    FeatureSpec,
)
from code_vector_graph.ingestion.okf.skeleton import build_skeleton

LOGIN_V1 = (
    "export function login(user, pass) { return checkPassword(user, pass); }\n"
    "function checkPassword(u, p) { return true; }\n"
)
LOGIN_V2 = (
    "export function login(user, pass, otp) { return checkPassword(user, pass) && otp; }\n"
    "function checkPassword(u, p) { return true; }\n"
)
INVOICE_JS = (
    "export function createInvoice(order) { return sendEmail(order); }\n"
    "function sendEmail(o) { return true; }\n"
)

MAP_PAYLOAD = {"features": [
    {"slug": "user-login", "title": "User Login", "member_files": ["auth/login.js"]},
    {"slug": "invoicing", "title": "Invoicing", "member_files": ["billing/invoice.js"]},
]}
INVOICING_DOC = {
    "title": "Invoicing", "description": "d", "overview": "o",
    "business_rules": ["r"], "process_flow": ["a", "b"],
}
USER_LOGIN_DOC = {
    "title": "User Login", "description": "Handles login.", "overview": "Lets users authenticate.",
    "business_rules": ["Password must match."], "process_flow": ["Submit.", "Verify."],
}


def _resp(payload: dict):
    return MagicMock(choices=[MagicMock(message=MagicMock(content=json.dumps(payload)))])


def _client(*payloads: dict):
    client = MagicMock()
    client.chat.completions.create.side_effect = [_resp(p) for p in payloads]
    return client


def _write_repo(tmp_path: Path, login_source: str = LOGIN_V1) -> Path:
    (tmp_path / "auth").mkdir(exist_ok=True)
    (tmp_path / "billing").mkdir(exist_ok=True)
    (tmp_path / "auth" / "login.js").write_text(login_source)
    (tmp_path / "billing" / "invoice.js").write_text(INVOICE_JS)
    return tmp_path


def _req(tmp_path: Path, bundle: Path, **overrides) -> FeatureBuildRequest:
    base = dict(
        repo_path=str(tmp_path), app="demo", repo_name="demo-repo", repo_id="repo-id-1",
        bundle_dir=str(bundle), language="en", model_map="m", model_doc="m",
    )
    base.update(overrides)
    return FeatureBuildRequest(**base)


def _deps(client=None, graph_store=None, vector_store=None, embedder=None) -> FeatureBuildDeps:
    return FeatureBuildDeps(
        llm_client=client, graph_store=graph_store, vector_store=vector_store,
        embedder=embedder, tokenizer_name="bert-base-uncased",
    )


def _fake_store(existing_records=None):
    gs = MagicMock()
    gs.query_graph.return_value = existing_records or []
    gs.upsert_nodes.return_value = {"nodes_created": 1}
    gs.upsert_relationships.return_value = {"relationships_created": 1}
    return gs


def _fake_vector():
    embedder = MagicMock()
    embedder.embed_chunks.side_effect = lambda chunks, batch_size=64: chunks
    vs = MagicMock()
    vs.upsert_chunks.return_value = ["p1"]
    return vs, embedder


def _real_hash(tmp_path: Path, member_files: list[str]) -> str:
    sk = build_skeleton(str(tmp_path))
    inv = build_inventory(sk, {})
    return _members_hash(FeatureSpec(slug="x", title="x", member_files=member_files), inv)


# --- discovery / dry-run -----------------------------------------------------


def test_dry_run_generates_structural_preview_without_persisting_map(tmp_path):
    repo = _write_repo(tmp_path)
    bundle = tmp_path / "bundle"
    result = build_feature_docs(_req(repo, bundle, dry_run=True), _deps())
    assert result.features == 2
    names = sorted(p.name for p in (bundle / "feature").glob("*.md"))
    assert "auth.md" in names and "billing.md" in names
    assert not (bundle / ".okf-features.json").exists()
    assert not (bundle / ".okf-features-cache.json").exists()


# --- llm cache hit / regenerate ----------------------------------------------


def test_llm_feature_unchanged_uses_cache_on_second_run(tmp_path):
    repo = _write_repo(tmp_path)
    bundle = tmp_path / "bundle"
    vs, embedder = _fake_vector()

    gs1 = _fake_store()
    client1 = _client(MAP_PAYLOAD, USER_LOGIN_DOC, INVOICING_DOC)
    r1 = build_feature_docs(_req(repo, bundle), _deps(client1, gs1, vs, embedder))
    assert r1.generated == 2 and r1.cached == 0

    gs2 = _fake_store()  # a fresh Neo4j fake — cache reuse comes from the bundle, not Neo4j state
    client2 = _client(MAP_PAYLOAD)  # only the map call; no doc-gen calls expected
    r2 = build_feature_docs(_req(repo, bundle), _deps(client2, gs2, vs, embedder))
    assert r2.cached == 2 and r2.generated == 0
    assert client2.chat.completions.create.call_count == 1


def test_only_the_changed_feature_regenerates_others_stay_cached(tmp_path):
    repo = _write_repo(tmp_path)
    bundle = tmp_path / "bundle"
    vs, embedder = _fake_vector()

    gs1 = _fake_store()
    client1 = _client(MAP_PAYLOAD, USER_LOGIN_DOC, INVOICING_DOC)
    build_feature_docs(_req(repo, bundle), _deps(client1, gs1, vs, embedder))

    _write_repo(tmp_path, login_source=LOGIN_V2)  # only auth/login.js changes
    gs2 = _fake_store()
    client2 = _client(MAP_PAYLOAD, USER_LOGIN_DOC)  # only one doc-gen call expected (user-login)
    r2 = build_feature_docs(_req(repo, bundle), _deps(client2, gs2, vs, embedder))
    assert r2.generated == 1 and r2.cached == 1
    assert client2.chat.completions.create.call_count == 2  # 1 map + 1 doc-gen


# --- human preserve / stale ---------------------------------------------------


def _human_record(members_hash: str, stale: bool = False) -> dict:
    content = (
        "# My Custom Title\n\n## Overview\nCustom human overview.\n\n"
        "## Business Rules\n- Custom rule.\n\n## Process Flow\n1. A.\n2. B.\n\n"
        "## Key Entities & Data\n_None identified._\n\n## Entry Points\n_None identified._\n\n"
        "## Dependencies & Integrations\n_None identified._\n\n"
        "## Edge Cases & Error Handling\n_None identified._\n\n## Open Questions\n_None._\n"
    )
    return {
        "wid": "wid-user-login", "feature_id": "fid-login", "slug": "user-login", "source": "human",
        "members_hash": members_hash, "edited_members_hash": members_hash, "content": content,
        "stale": stale, "stale_since": "2026-01-03T00:00:00Z" if stale else None,
        "title": "My Custom Title", "description": "Custom desc", "kind": "user-facing",
        "tags": ["custom"], "generated_at": "2026-01-01T00:00:00Z", "edited_at": "2026-01-02T00:00:00Z",
    }


def test_human_page_unchanged_code_is_preserved_and_not_stale(tmp_path):
    repo = _write_repo(tmp_path)
    bundle = tmp_path / "bundle"
    baseline = _real_hash(repo, ["auth/login.js"])
    gs = _fake_store([_human_record(baseline)])
    vs, embedder = _fake_vector()
    client = _client(MAP_PAYLOAD, INVOICING_DOC)  # no doc-gen call for the preserved human page
    result = build_feature_docs(_req(repo, bundle), _deps(client, gs, vs, embedder))
    assert result.kept_human == 1 and result.stale == 0

    body = (bundle / "feature" / "user-login.md").read_text()
    assert "My Custom Title" in body
    assert "Custom human overview" in body
    assert "stale: false" in body


def test_human_page_changed_code_is_marked_stale_content_untouched(tmp_path):
    repo = _write_repo(tmp_path)
    bundle = tmp_path / "bundle"
    baseline = _real_hash(repo, ["auth/login.js"])
    _write_repo(tmp_path, login_source=LOGIN_V2)  # drift after the baseline was captured

    gs = _fake_store([_human_record(baseline)])
    vs, embedder = _fake_vector()
    client = _client(MAP_PAYLOAD, INVOICING_DOC)
    result = build_feature_docs(_req(repo, bundle), _deps(client, gs, vs, embedder))
    assert result.kept_human == 1 and result.stale == 1

    body = (bundle / "feature" / "user-login.md").read_text()
    assert "My Custom Title" in body  # content still untouched
    assert "stale: true" in body

    saved_nodes = gs.upsert_nodes.call_args.args[0]
    node = next(n for n in saved_nodes if n["properties"]["slug"] == "user-login")
    assert node["properties"]["stale"] is True
    assert node["properties"]["stale_since"]  # set on this transition
    assert node["properties"]["content"] == _human_record(baseline)["content"]


# --- orphans -------------------------------------------------------------


def test_orphan_llm_feature_is_deleted_from_both_stores(tmp_path):
    repo = tmp_path
    (repo / "auth").mkdir()
    (repo / "auth" / "login.js").write_text(LOGIN_V1)
    bundle = tmp_path / "bundle"
    orphan = {
        "wid": "wid-old", "feature_id": "fid-old", "slug": "old-feature", "source": "llm",
        "members_hash": "x", "edited_members_hash": None, "content": "old body",
        "stale": False, "stale_since": None, "title": "Old Feature", "description": "",
        "kind": "other", "tags": [], "generated_at": "t", "edited_at": None,
    }
    gs = _fake_store([orphan])
    vs, embedder = _fake_vector()
    map_only = {"features": [{"slug": "user-login", "title": "User Login", "member_files": ["auth/login.js"]}]}
    client = _client(map_only, USER_LOGIN_DOC)
    result = build_feature_docs(_req(repo, bundle), _deps(client, gs, vs, embedder))
    assert result.deleted == 1
    gs.query_graph.assert_any_call("MATCH (w:WikiPage {id:$wid}) DETACH DELETE w", {"wid": "wid-old"})
    vs.delete_by_symbol_id.assert_any_call("fid-old")


def test_orphan_human_feature_is_kept_and_marked_stale(tmp_path):
    repo = tmp_path
    (repo / "auth").mkdir()
    (repo / "auth" / "login.js").write_text(LOGIN_V1)
    bundle = tmp_path / "bundle"
    orphan = {
        "wid": "wid-old-h", "feature_id": "fid-old-h", "slug": "old-human-feature", "source": "human",
        "members_hash": "x", "edited_members_hash": "x", "content": "old human body",
        "stale": False, "stale_since": None, "title": "Old Human Feature", "description": "",
        "kind": "other", "tags": [], "generated_at": "t", "edited_at": "t2",
    }
    gs = _fake_store([orphan])
    vs, embedder = _fake_vector()
    map_only = {"features": [{"slug": "user-login", "title": "User Login", "member_files": ["auth/login.js"]}]}
    client = _client(map_only, USER_LOGIN_DOC)
    result = build_feature_docs(_req(repo, bundle), _deps(client, gs, vs, embedder))
    assert result.deleted == 0
    assert any("no longer maps" in w for w in result.warnings)
    saved_nodes = gs.upsert_nodes.call_args.args[0]
    node = next(n for n in saved_nodes if n["properties"]["slug"] == "old-human-feature")
    assert node["properties"]["stale"] is True
    assert node["properties"]["member_files"] == []
    assert node["properties"]["content"] == "old human body"


# --- --only partial run -------------------------------------------------------


def test_only_flag_does_not_touch_unrelated_bundle_files(tmp_path):
    repo = _write_repo(tmp_path)
    bundle = tmp_path / "bundle"
    (bundle / "feature").mkdir(parents=True)
    (bundle / "feature" / "untouched.md").write_text("must survive a --only run")

    gs = _fake_store()
    vs, embedder = _fake_vector()
    client = _client(MAP_PAYLOAD, USER_LOGIN_DOC)
    build_feature_docs(_req(repo, bundle, only_slugs=["user-login"]), _deps(client, gs, vs, embedder))

    assert (bundle / "feature" / "untouched.md").exists()
    assert (bundle / "feature" / "user-login.md").exists()
    assert not (bundle / "feature" / "invoicing.md").exists()


# --- embedder unavailable -----------------------------------------------------


def test_needs_reembed_when_embedder_is_none(tmp_path):
    repo = tmp_path
    (repo / "auth").mkdir()
    (repo / "auth" / "login.js").write_text(LOGIN_V1)
    bundle = tmp_path / "bundle"
    gs = _fake_store()
    map_only = {"features": [{"slug": "user-login", "title": "User Login", "member_files": ["auth/login.js"]}]}
    client = _client(map_only, USER_LOGIN_DOC)
    vs = MagicMock()
    result = build_feature_docs(_req(repo, bundle), _deps(client, gs, vs, None))
    assert result.needs_reembed == 1
    assert result.chunks == 0
    saved_nodes = gs.upsert_nodes.call_args.args[0]
    node = next(n for n in saved_nodes if n["properties"]["slug"] == "user-login")
    assert node["properties"]["needs_reembed"] is True
