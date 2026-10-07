"""Tests for /api/search and /api/health."""

import pytest

pytest.importorskip("fastapi")

from code_vector_graph.api.config import MODEL_ID, QDRANT_COLLECTION  # noqa: E402

from .conftest import ONEBID_ROOTS  # noqa: E402

GLOBAL = "backend_nodejs_global_tnlm"
DATASYNC = "backend_nodejs_data_sync_onebid"


def test_search_accepts_graph_hit_without_file_path(client, fake_mcp):
    fake_mcp.reply("search_code_json", {"results": [{"id": "x", "score": 1.0, "source": "code"}]})

    resp = client.post("/api/search", json={"query": "doThing", "mode": "graph"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["query"] == "doThing"
    assert body["results"][0]["id"] == "x"
    assert body["results"][0]["file_path"] == ""
    assert body["results"][0]["language"] == ""
    assert body["results"][0]["source"] == "code"


def test_search_forwards_source_and_include_wiki(client, fake_mcp):
    fake_mcp.reply("search_code_json", {"results": []})

    resp = client.post(
        "/api/search",
        json={"query": "auth", "source": "wiki", "include_wiki": False, "app": "onebid"},
    )
    assert resp.status_code == 200
    name, args = fake_mcp.calls[-1]
    assert name == "search_code_json"
    assert args["source"] == "wiki"
    assert args["include_wiki"] is False
    # A known app resolves to a scope, forwarded as repo names/roots (not the
    # singular request-level "app"/"repo" fields — those never reach the MCP call).
    assert "app" not in args and "repo" not in args
    assert sorted(args["repos"]) == sorted([DATASYNC, GLOBAL])
    assert args["repo_roots"]


def test_search_unknown_app_is_404(client, fake_mcp):
    resp = client.post("/api/search", json={"query": "auth", "app": "nope"})
    assert resp.status_code == 404


def test_search_fills_in_app_and_rel_path_for_a_scoped_legacy_hit(client, fake_mcp):
    """Regression: `setdefault` doesn't fire when the MCP item already carries
    the key with a None value — every legacy hit does, since `search_code_json`
    always includes `"app"`/`"rel_path"` in its items."""
    fake_mcp.reply(
        "search_code_json",
        {
            "results": [
                {
                    "id": "c1",
                    "score": 0.9,
                    "source": "code",
                    "file_path": f"{ONEBID_ROOTS[GLOBAL]}/src/webhooks/guard.ts",
                    "language": "typescript",
                    "app": None,
                    "repo": None,
                    "rel_path": None,
                }
            ]
        },
    )

    resp = client.post("/api/search", json={"query": "webhook", "app": "onebid", "repo": GLOBAL})

    assert resp.status_code == 200
    hit = resp.json()["results"][0]
    assert hit["app"] == "onebid"
    assert hit["repo"] == GLOBAL
    assert hit["rel_path"] == "src/webhooks/guard.ts"


def test_search_keeps_wiki_fields(client, fake_mcp):
    fake_mcp.reply(
        "search_code_json",
        {
            "results": [
                {
                    "id": "w1",
                    "score": 0.9,
                    "source": "wiki",
                    "summary": "Handles login.",
                    "term": "AuthService",
                    "file_path": "src/auth.ts",
                    "language": "typescript",
                },
                {
                    "id": "c1",
                    "score": 0.8,
                    "file_path": "/abs/src/auth.ts",
                    "language": "typescript",
                    "wiki_context": {"title": "AuthService", "summary": "Handles login."},
                },
            ]
        },
    )
    body = client.post("/api/search", json={"query": "login"}).json()
    wiki, code = body["results"]
    assert wiki["source"] == "wiki" and wiki["term"] == "AuthService" and wiki["summary"]
    assert code["source"] == "code" and code["wiki_context"]["title"] == "AuthService"


def test_search_503_when_mcp_down(client, fake_mcp):
    fake_mcp.is_alive = False
    assert client.post("/api/search", json={"query": "x"}).status_code == 503


def test_search_500_on_tool_error(client, fake_mcp):
    fake_mcp.reply("search_code_json", {"error": "boom", "results": []})
    resp = client.post("/api/search", json={"query": "x"})
    assert resp.status_code == 500
    assert resp.json()["detail"] == "boom"


def test_health_reports_active_config(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["config"]["collection"] == QDRANT_COLLECTION
    assert body["config"]["model_id"] == MODEL_ID
    assert body["config"]["chat_provider"]
    assert body["config"]["chat_model"]
    assert body["qdrant"]["ok"] is True
    assert body["neo4j"]["ok"] is True
    assert body["mcp_session"]["ok"] is True
