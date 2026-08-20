"""Tests for the DeepSeek enrichment agent (client fully mocked — no network)."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.okf import cache as okf_cache
from src.okf.skeleton import build_skeleton
from src.okf.enricher import (
    _build_context,
    enrich_all,
    enrich_concept,
    fallback_enrichment,
)

VALID = json.dumps({
    "summary": "Does a thing.",
    "overview": "An overview.",
    "how_it_works": "Steps.",
    "parameters": [{"name": "x", "description": "an arg"}],
    "tags": ["util"],
    "related": ["format"],
})


def _resp(content: str):
    return MagicMock(choices=[MagicMock(message=MagicMock(content=content))])


def _client(return_value=None, side_effect=None):
    client = MagicMock()
    if side_effect is not None:
        client.chat.completions.create.side_effect = side_effect
    else:
        client.chat.completions.create.return_value = _resp(return_value or VALID)
    return client


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "a.js").write_text(
        "export function greet(name) { return format(name); }\n"
        "function format(x) { return 'hi ' + x; }\n"
    )
    return tmp_path


# --- context building -----------------------------------------------------

def test_build_context_includes_neighbors(tmp_path):
    sk = build_skeleton(str(_repo(tmp_path)))
    greet_id = next(i for i in sk.concept_ids
                    if sk.nodes[i]["label"] == "Function"
                    and sk.nodes[i]["properties"]["name"] == "greet")
    ctx = _build_context(sk, sk.nodes[greet_id], {})
    assert "Function" in ctx and "greet" in ctx
    assert "Calls: format" in ctx  # grounded call site


# --- single-concept enrichment -------------------------------------------

def test_enrich_concept_parses_json():
    client = _client(VALID)
    node = {"label": "Function", "id": "x", "properties": {"name": "f"}, "_file": {"path": ""}}
    out = enrich_concept(client, "deepseek-v4-flash", node, "ctx", "code")
    assert out["summary"] == "Does a thing."
    assert out["parameters"] == [{"name": "x", "description": "an arg"}]
    # JSON mode requested
    kwargs = client.chat.completions.create.call_args.kwargs
    assert kwargs["response_format"] == {"type": "json_object"}
    # source code is included in the user message
    user_msg = kwargs["messages"][-1]["content"]
    assert "code" in user_msg


def test_enrich_concept_retries_bad_json_then_succeeds():
    client = _client(side_effect=[_resp("not json at all"), _resp(VALID)])
    node = {"label": "Function", "id": "x", "properties": {"name": "f"}, "_file": {"path": ""}}
    out = enrich_concept(client, "m", node, "ctx", "code")
    assert out["summary"] == "Does a thing."
    assert client.chat.completions.create.call_count == 2


def test_enrich_concept_falls_back_on_persistent_failure():
    client = _client(side_effect=RuntimeError("boom"))
    node = {"label": "Function", "id": "x",
            "properties": {"name": "f", "visibility": "public", "parameters": ["a"]},
            "_file": {"path": ""}}
    out = enrich_concept(client, "m", node, "ctx", "code")
    # fallback shape: summary derived from metadata, params preserved
    assert "f" in out["summary"]
    assert out["parameters"] == [{"name": "a", "description": ""}]


# --- fallback -------------------------------------------------------------

def test_fallback_enrichment_shape():
    node = {"label": "Class", "id": "c", "properties": {"name": "Foo", "visibility": "public"}}
    fb = fallback_enrichment(node)
    assert set(fb) == {"summary", "overview", "how_it_works", "parameters", "tags", "related"}
    assert "Foo" in fb["summary"]


# --- orchestration + incremental cache -----------------------------------

def test_enrich_all_dry_run_makes_no_calls(tmp_path):
    sk = build_skeleton(str(_repo(tmp_path)))
    client = _client(VALID)
    enr, ov, cache = enrich_all(sk, client, model_flash="f", model_pro="p", dry_run=True)
    assert client.chat.completions.create.call_count == 0
    assert len(enr) == len(sk.concept_ids)


def test_enrich_all_uses_cache_on_second_run(tmp_path):
    sk = build_skeleton(str(_repo(tmp_path)))
    client = _client(VALID)

    enr, ov, cache = enrich_all(sk, client, model_flash="f", model_pro="p", concurrency=2, cache={})
    # one call per concept + one for the overview
    assert client.chat.completions.create.call_count == len(sk.concept_ids) + 1
    assert len(cache) == len(sk.concept_ids)

    client.chat.completions.create.reset_mock()
    client.chat.completions.create.return_value = _resp(VALID)
    enr2, ov2, cache2 = enrich_all(sk, client, model_flash="f", model_pro="p", cache=cache)
    # concepts are cached -> only the (uncached) overview is regenerated
    assert client.chat.completions.create.call_count == 1
    assert enr2 == enr


def test_concept_hash_changes_with_content(tmp_path):
    sk = build_skeleton(str(_repo(tmp_path)))
    nid = sk.concept_ids[0]
    node = sk.nodes[nid]
    h1 = okf_cache.concept_hash(node)
    node2 = {**node, "_file": {**node["_file"], "file_hash": "different"}}
    assert okf_cache.concept_hash(node2) != h1
