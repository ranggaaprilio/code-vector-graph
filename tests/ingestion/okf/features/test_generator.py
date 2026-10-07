"""Tests for per-feature doc generation (client fully mocked — no network)."""

import json
from pathlib import Path
from unittest.mock import MagicMock

from code_vector_graph.ingestion.okf.features.generator import (
    _source_excerpts,
    fallback_feature_doc,
    generate_feature_doc,
)
from code_vector_graph.ingestion.okf.features.inventory import build_inventory
from code_vector_graph.ingestion.okf.features.models import FeatureSpec
from code_vector_graph.ingestion.okf.features.validate import validate_feature_body
from code_vector_graph.ingestion.okf.skeleton import build_skeleton


def _resp(content: str):
    return MagicMock(choices=[MagicMock(message=MagicMock(content=content))])


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "auth").mkdir()
    (tmp_path / "auth" / "login.js").write_text(
        "export function login(user, pass) { return checkPassword(user, pass); }\n"
        "function checkPassword(u, p) { return true; }\n"
    )
    return tmp_path


def _setup(tmp_path: Path):
    sk = build_skeleton(str(_repo(tmp_path)))
    inv = build_inventory(sk, {})
    spec = FeatureSpec(
        slug="user-login", title="User Login", description="Handles login.",
        kind="user-facing", member_files=["auth/login.js"],
    )
    return sk, inv, spec


GOOD_JSON = json.dumps({
    "title": "User Login",
    "description": "Handles login.",
    "overview": "Lets users authenticate with a username and password.",
    "business_rules": ["Password must match the stored hash."],
    "process_flow": ["User submits credentials.", "Server verifies the password."],
    "entities": [{"name": "User", "description": "username/password"}],
    "entry_points": [{"kind": "Function", "name": "login", "file": "auth/login.js", "line": 1}],
    "dependencies": [],
    "edge_cases": ["Wrong password: rejected."],
    "open_questions": [],
    "tags": ["auth"],
})

# Raw HTML defeats the renderer's built-in "always valid" fallbacks (unlike an
# empty list, which the template safely fills in) — a reliable way to force a
# real validation failure for the retry/fallback tests below.
BAD_JSON = json.dumps({
    "title": "User Login",
    "overview": "<script>hack</script>",
    "business_rules": ["x"],
    "process_flow": ["a", "b"],
})


def test_fallback_without_client():
    spec = FeatureSpec(slug="s", title="S", member_files=[])
    doc = fallback_feature_doc(spec, [])
    assert doc.title == "S"
    assert doc.open_questions


def test_generate_returns_fallback_when_client_is_none(tmp_path):
    sk, inv, spec = _setup(tmp_path)
    body, used_fallback, warnings = generate_feature_doc(None, "m", spec, sk, inv)
    assert used_fallback
    result = validate_feature_body(body, title="User Login")
    assert result.ok, result.errors


def test_generate_accepts_good_llm_output_on_first_try(tmp_path):
    sk, inv, spec = _setup(tmp_path)
    client = MagicMock()
    client.chat.completions.create.return_value = _resp(GOOD_JSON)
    body, used_fallback, warnings = generate_feature_doc(client, "deepseek-v4-pro", spec, sk, inv)
    assert not used_fallback
    assert client.chat.completions.create.call_count == 1
    result = validate_feature_body(body, title="User Login")
    assert result.ok, result.errors


def test_generate_includes_source_excerpt_in_prompt(tmp_path):
    sk, inv, spec = _setup(tmp_path)
    client = MagicMock()
    client.chat.completions.create.return_value = _resp(GOOD_JSON)
    generate_feature_doc(client, "deepseek-v4-pro", spec, sk, inv)
    user_msg = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "login" in user_msg
    assert "auth/login.js" in user_msg


def test_generate_retries_once_then_recovers(tmp_path):
    sk, inv, spec = _setup(tmp_path)
    client = MagicMock()
    client.chat.completions.create.side_effect = [_resp(BAD_JSON), _resp(GOOD_JSON)]
    body, used_fallback, warnings = generate_feature_doc(client, "deepseek-v4-pro", spec, sk, inv)
    assert not used_fallback
    assert client.chat.completions.create.call_count == 2
    result = validate_feature_body(body, title="User Login")
    assert result.ok, result.errors


def test_generate_falls_back_after_repeated_validation_failures(tmp_path):
    sk, inv, spec = _setup(tmp_path)
    client = MagicMock()
    client.chat.completions.create.return_value = _resp(BAD_JSON)
    body, used_fallback, warnings = generate_feature_doc(client, "deepseek-v4-pro", spec, sk, inv)
    assert used_fallback
    assert client.chat.completions.create.call_count == 3  # initial attempt + 2 retries
    assert any("fallback" in w for w in warnings)
    result = validate_feature_body(body, title="User Login")
    assert result.ok, result.errors


def test_generate_falls_back_on_repeated_call_errors(tmp_path):
    sk, inv, spec = _setup(tmp_path)
    client = MagicMock()
    client.chat.completions.create.side_effect = RuntimeError("boom")
    body, used_fallback, warnings = generate_feature_doc(client, "deepseek-v4-pro", spec, sk, inv)
    assert used_fallback
    result = validate_feature_body(body, title="User Login")
    assert result.ok, result.errors
    assert any("call failed" in w for w in warnings)


def test_source_excerpts_respects_budget(tmp_path):
    sk, inv, spec = _setup(tmp_path)
    members = [f for f in inv if f.rel_path == "auth/login.js"]
    excerpt = _source_excerpts(sk, members, budget=10)
    assert len(excerpt) < 200  # header + a small truncated slice, not the whole file


def test_source_excerpts_prioritizes_exported_symbols(tmp_path):
    sk, inv, spec = _setup(tmp_path)
    members = [f for f in inv if f.rel_path == "auth/login.js"]
    excerpt = _source_excerpts(sk, members, budget=100_000)
    # both symbols fit; the exported one should appear first
    assert excerpt.index("login") < excerpt.index("checkPassword")
