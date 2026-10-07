"""Tests for feature-map discovery (client fully mocked — no network)."""

import json
from pathlib import Path
from unittest.mock import MagicMock

from code_vector_graph.ingestion.okf.features.inventory import build_inventory, chunk_inventory
from code_vector_graph.ingestion.okf.features.mapper import (
    INFRA_SLUG,
    _cap_members,
    _cap_total_features,
    _coerce_feature_specs,
    _ensure_coverage,
    _reuse_prior_slugs,
    discover_features,
    structural_fallback,
)
from code_vector_graph.ingestion.okf.features.models import FeatureMap, FeatureSpec
from code_vector_graph.ingestion.okf.skeleton import build_skeleton


def _resp(content: str):
    return MagicMock(choices=[MagicMock(message=MagicMock(content=content))])


def _client(payload: dict):
    client = MagicMock()
    client.chat.completions.create.return_value = _resp(json.dumps(payload))
    return client


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "auth").mkdir()
    (tmp_path / "billing").mkdir()
    (tmp_path / "auth" / "login.js").write_text(
        "export function login(user, pass) { return checkPassword(user, pass); }\n"
        "function checkPassword(u,p) { return true; }\n"
    )
    (tmp_path / "billing" / "invoice.js").write_text(
        "export function createInvoice(order) { return sendEmail(order); }\n"
        "function sendEmail(o) { return true; }\n"
    )
    return tmp_path


def _inventory(tmp_path: Path):
    sk = build_skeleton(str(_repo(tmp_path)))
    return build_inventory(sk, {})


# --- build_inventory / chunk_inventory --------------------------------------


def test_build_inventory_computes_rel_path_and_top_dir(tmp_path):
    inv = _inventory(tmp_path)
    rel_paths = sorted(f.rel_path for f in inv)
    assert rel_paths == ["auth/login.js", "billing/invoice.js"]
    top_dirs = {f.rel_path: f.top_dir for f in inv}
    assert top_dirs["auth/login.js"] == "auth"
    assert top_dirs["billing/invoice.js"] == "billing"


def test_build_inventory_captures_exports_and_symbols(tmp_path):
    inv = _inventory(tmp_path)
    login = next(f for f in inv if f.rel_path == "auth/login.js")
    # File-level `exports` tracking is the extractor's own concern (empty for
    # this simple named-export style); child symbol lines are what we control.
    assert any("login" in s and "[exported]" in s for s in login.symbols)
    assert any("checkPassword" in s and "[exported]" not in s for s in login.symbols)


def test_chunk_inventory_groups_by_top_dir_and_respects_max_files(tmp_path):
    inv = _inventory(tmp_path)
    chunks = chunk_inventory(inv, max_files=1, max_chars=10_000)
    assert len(chunks) == 2
    assert all(len(c) == 1 for c in chunks)


def test_chunk_inventory_packs_small_dirs_together(tmp_path):
    inv = _inventory(tmp_path)
    chunks = chunk_inventory(inv, max_files=250, max_chars=1_000_000)
    assert len(chunks) == 1
    assert len(chunks[0]) == 2


# --- coercion ----------------------------------------------------------------


def test_coerce_feature_specs_drops_paths_outside_allowed_set():
    raw = {"features": [{"slug": "x", "title": "X", "member_files": ["a.js", "not-allowed.js"]}]}
    specs = _coerce_feature_specs(raw, allowed_paths={"a.js"})
    assert len(specs) == 1
    assert specs[0].member_files == ["a.js"]


def test_coerce_feature_specs_drops_feature_with_no_valid_members():
    raw = {"features": [{"slug": "x", "title": "X", "member_files": ["ghost.js"]}]}
    specs = _coerce_feature_specs(raw, allowed_paths={"a.js"})
    assert specs == []


def test_coerce_feature_specs_merges_duplicate_slugs():
    raw = {"features": [
        {"slug": "x", "title": "X", "member_files": ["a.js"]},
        {"slug": "x", "title": "X", "member_files": ["b.js"]},
    ]}
    specs = _coerce_feature_specs(raw, allowed_paths={"a.js", "b.js"})
    assert len(specs) == 1
    assert sorted(specs[0].member_files) == ["a.js", "b.js"]


def test_coerce_feature_specs_defaults_invalid_kind_to_other():
    raw = {"features": [{"slug": "x", "title": "X", "kind": "bogus", "member_files": ["a.js"]}]}
    specs = _coerce_feature_specs(raw, allowed_paths={"a.js"})
    assert specs[0].kind == "other"


def test_coerce_feature_specs_ignores_malformed_items():
    raw = {"features": [{"title": ""}, "not-a-dict", {"slug": "", "title": "X"}]}
    assert _coerce_feature_specs(raw, allowed_paths={"a.js"}) == []


# --- deterministic post-pass --------------------------------------------------


def test_ensure_coverage_adds_infra_bucket_for_missing_files():
    specs = [FeatureSpec(slug="a", title="A", member_files=["x.js"])]
    out = _ensure_coverage(specs, {"x.js", "y.js"})
    infra = next(s for s in out if s.slug == INFRA_SLUG)
    assert infra.member_files == ["y.js"]


def test_ensure_coverage_extends_existing_infra_bucket():
    specs = [FeatureSpec(slug=INFRA_SLUG, title="Other", member_files=["x.js"])]
    out = _ensure_coverage(specs, {"x.js", "y.js"})
    assert len(out) == 1
    assert sorted(out[0].member_files) == ["x.js", "y.js"]


def test_cap_members_moves_overflow_to_infra():
    specs = [FeatureSpec(slug="big", title="Big", member_files=[f"f{i}.js" for i in range(5)])]
    out, warnings = _cap_members(specs, max_members=3)
    big = next(s for s in out if s.slug == "big")
    infra = next(s for s in out if s.slug == INFRA_SLUG)
    assert len(big.member_files) == 3
    assert len(infra.member_files) == 2
    assert warnings


def test_cap_total_features_folds_smallest_into_infra():
    specs = [FeatureSpec(slug=f"f{i}", title=f"F{i}", member_files=[f"{i}.js"]) for i in range(5)]
    out = _cap_total_features(specs, max_features=3)
    assert len(out) == 3
    assert any(s.slug == INFRA_SLUG for s in out)


def test_reuse_prior_slugs_matches_by_member_overlap():
    prior = FeatureMap(app="a", repo="r", generated_at="t", model="m", features=[
        FeatureSpec(slug="invoicing", title="Invoicing", member_files=["billing/invoice.js"]),
    ])
    specs = [FeatureSpec(slug="billing-stuff", title="Billing Stuff", member_files=["billing/invoice.js"])]
    out = _reuse_prior_slugs(specs, prior)
    assert out[0].slug == "invoicing"
    assert out[0].title == "Invoicing"


def test_reuse_prior_slugs_ignores_low_overlap():
    prior = FeatureMap(app="a", repo="r", generated_at="t", model="m", features=[
        FeatureSpec(slug="invoicing", title="Invoicing", member_files=["billing/invoice.js", "billing/a.js", "billing/b.js"]),
    ])
    specs = [FeatureSpec(slug="new-thing", title="New Thing", member_files=["billing/invoice.js"])]
    out = _reuse_prior_slugs(specs, prior)
    assert out[0].slug == "new-thing"


# --- structural fallback (dry-run / call failure) -----------------------------


def test_structural_fallback_covers_every_file(tmp_path):
    inv = _inventory(tmp_path)
    specs = structural_fallback(inv)
    covered = {p for s in specs for p in s.member_files}
    assert covered == {f.rel_path for f in inv}


# --- discover_features end-to-end (client mocked) -----------------------------


def test_discover_features_dry_run_is_structural(tmp_path):
    inv = _inventory(tmp_path)
    fmap, warnings = discover_features(None, "x", inv, app="demo", repo="demo", dry_run=True)
    assert fmap.model == "structural"
    assert warnings == []
    covered = {p for f in fmap.features for p in f.member_files}
    assert covered == {f.rel_path for f in inv}


def test_discover_features_single_chunk_uses_map_call_only(tmp_path):
    inv = _inventory(tmp_path)
    client = _client({"features": [
        {"slug": "user-login", "title": "User Login", "member_files": ["auth/login.js"]},
        {"slug": "invoicing", "title": "Invoicing", "member_files": ["billing/invoice.js"]},
    ]})
    fmap, _ = discover_features(client, "deepseek-v4-pro", inv, app="demo", repo="demo")
    assert client.chat.completions.create.call_count == 1  # no merge call needed for a single chunk
    assert {f.slug for f in fmap.features} == {"user-login", "invoicing"}


def test_discover_features_multi_chunk_triggers_merge_call(tmp_path):
    inv = _inventory(tmp_path)
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _resp(json.dumps({"features": [{"slug": "user-login", "title": "User Login", "member_files": ["auth/login.js"]}]})),
        _resp(json.dumps({"features": [{"slug": "invoicing", "title": "Invoicing", "member_files": ["billing/invoice.js"]}]})),
        _resp(json.dumps({"features": [
            {"slug": "user-login", "title": "User Login", "member_files": ["auth/login.js"]},
            {"slug": "invoicing", "title": "Invoicing", "member_files": ["billing/invoice.js"]},
        ]})),
    ]
    fmap, _ = discover_features(client, "deepseek-v4-pro", inv, app="demo", repo="demo", max_files=1)
    assert client.chat.completions.create.call_count == 3  # 2 map calls + 1 merge call
    assert {f.slug for f in fmap.features} == {"user-login", "invoicing"}


def test_discover_features_falls_back_to_structural_on_llm_failure(tmp_path):
    inv = _inventory(tmp_path)
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("boom")
    fmap, warnings = discover_features(client, "deepseek-v4-pro", inv, app="demo", repo="demo")
    covered = {p for f in fmap.features for p in f.member_files}
    assert covered == {f.rel_path for f in inv}
