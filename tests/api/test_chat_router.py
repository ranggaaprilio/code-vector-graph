"""Tests for /api/chat, /api/chat/stream and /api/chat/config."""

import json

import pytest

pytest.importorskip("fastapi")

from code_vector_graph.api.routers import chat as chat_router  # noqa: E402

from .conftest import ONEBID_ROOTS, FakeProvider  # noqa: E402

# StubRegistry builds its AppInfo through AppInfo.aggregate(), which sorts repos by name.
REPO_NAMES = sorted(ONEBID_ROOTS)
SEARCH = "search_code_json"


@pytest.fixture
def use_provider(monkeypatch):
    """Install a provider for the chat router (bypasses the env-driven lru_cache)."""

    def _install(provider):
        monkeypatch.setattr(chat_router, "get_provider", lambda: provider)
        return provider

    return _install


def answering_provider(text="Hello from the fake model.") -> FakeProvider:
    return FakeProvider([[FakeProvider.text(text), FakeProvider.stop()]])


def searching_provider() -> FakeProvider:
    """Round 1 calls search_code_json, round 2 answers."""
    return FakeProvider(
        [
            [FakeProvider.text("Looking…"), FakeProvider.call(SEARCH, {"query": "auth"}),
             FakeProvider.stop("tool_use")],
            [FakeProvider.text("Done."), FakeProvider.stop()],
        ]
    )


# --------------------------------------------------------------------------- #
# GET /api/chat/config
# --------------------------------------------------------------------------- #


def test_chat_config_reports_a_configured_provider(client, use_provider):
    use_provider(answering_provider())

    body = client.get("/api/chat/config").json()

    assert body == {
        "provider": "fake",
        "model": "fake-model-1",
        "configured": True,
        "reason": None,
    }


def test_chat_config_reports_the_missing_key_reason(client, use_provider):
    use_provider(FakeProvider(configured=(False, "DEEPSEEK_API_KEY is not set")))

    body = client.get("/api/chat/config").json()

    assert body["provider"] == "fake"
    assert body["configured"] is False
    assert body["reason"] == "DEEPSEEK_API_KEY is not set"


def test_chat_config_reports_an_unsupported_provider(client, monkeypatch):
    def boom():
        raise ValueError("CVG_CHAT_PROVIDER='llamafile' is not supported")

    monkeypatch.setattr(chat_router, "get_provider", boom)

    body = client.get("/api/chat/config").json()

    assert body == {
        "provider": None,
        "model": None,
        "configured": False,
        "reason": "CVG_CHAT_PROVIDER='llamafile' is not supported",
    }


# --------------------------------------------------------------------------- #
# POST /api/chat
# --------------------------------------------------------------------------- #


def test_chat_answers_and_reports_provider_and_model(client, use_provider):
    use_provider(answering_provider("42."))

    resp = client.post("/api/chat", json={"message": "the answer?"})

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["answer"] == "42."
    assert body["provider"] == "fake" and body["model"] == "fake-model-1"
    assert body["sources"] == []
    assert body["error"] is None


def test_chat_returns_scoped_sources(client, use_provider, fake_mcp):
    use_provider(searching_provider())
    fake_mcp.reply(
        SEARCH,
        {"results": [{
            "id": "w1", "score": 0.9, "source": "wiki", "term": "AuthService",
            "summary": "Handles login.", "file_path": "src/auth.ts", "repo": REPO_NAMES[0],
        }]},
    )

    body = client.post(
        "/api/chat", json={"message": "auth?", "options": {"app": "onebid", "top_k": 4}}
    ).json()

    (source,) = body["sources"]
    assert source["source"] == "wiki"
    assert source["title"] == "AuthService"
    assert source["repo"] == REPO_NAMES[0]

    _name, args = fake_mcp.calls[-1]
    assert args["repos"] == REPO_NAMES
    assert args["top_k"] == 4


def test_chat_400_when_the_provider_is_not_configured(client, use_provider):
    use_provider(FakeProvider(configured=(False, "ANTHROPIC_API_KEY is not set")))

    resp = client.post("/api/chat", json={"message": "hi"})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "ANTHROPIC_API_KEY is not set"


def test_chat_400_when_the_provider_name_is_unsupported(client, monkeypatch):
    def boom():
        raise ValueError("CVG_CHAT_PROVIDER='nope' is not supported")

    monkeypatch.setattr(chat_router, "get_provider", boom)

    resp = client.post("/api/chat", json={"message": "hi"})

    assert resp.status_code == 400
    assert "not supported" in resp.json()["detail"]


def test_chat_503_when_mcp_is_down(client, use_provider, fake_mcp):
    use_provider(answering_provider())
    fake_mcp.is_alive = False

    assert client.post("/api/chat", json={"message": "hi"}).status_code == 503


def test_chat_404_for_an_unknown_app(client, use_provider):
    use_provider(answering_provider())

    resp = client.post("/api/chat", json={"message": "hi", "options": {"app": "nope"}})

    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert "application 'nope'" in detail


def test_chat_404_for_an_unknown_repo_in_a_known_app(client, use_provider):
    use_provider(answering_provider())

    resp = client.post(
        "/api/chat", json={"message": "hi", "options": {"app": "onebid", "repo": "nope"}}
    )

    assert resp.status_code == 404
    assert "repository 'nope'" in resp.json()["detail"]


def test_chat_ignores_a_blank_app_option(client, use_provider, fake_mcp):
    use_provider(searching_provider())
    fake_mcp.reply(SEARCH, {"results": []})

    resp = client.post("/api/chat", json={"message": "hi", "options": {"app": "  ", "repo": ""}})

    assert resp.status_code == 200
    _name, args = fake_mcp.calls[-1]
    assert "repos" not in args


def test_chat_500_when_the_loop_only_produces_an_error(client, use_provider):
    class ExplodingProvider(FakeProvider):
        async def stream_turn(self, system, messages, tools):
            raise RuntimeError("upstream 500")
            yield  # pragma: no cover

    use_provider(ExplodingProvider())

    resp = client.post("/api/chat", json={"message": "hi"})

    assert resp.status_code == 500
    assert "upstream 500" in resp.json()["detail"]


# --------------------------------------------------------------------------- #
# POST /api/chat/stream
# --------------------------------------------------------------------------- #


def sse_events(text: str) -> list[tuple[str, dict]]:
    """Parse an SSE body into [(event, data)] (sse-starlette uses \\r\\n separators)."""
    events = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        name, payload = None, []
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                payload.append(line[len("data:"):].strip())
        if name:
            events.append((name, json.loads("\n".join(payload)) if payload else None))
    return events


def test_chat_stream_emits_token_and_done_events(client, use_provider):
    use_provider(answering_provider("Streamed answer."))

    resp = client.post("/api/chat/stream", json={"message": "hi"})

    assert resp.status_code == 200
    assert "event: token" in resp.text
    events = sse_events(resp.text)
    assert [name for name, _ in events] == ["token", "sources", "done"]
    assert events[0][1] == {"text": "Streamed answer."}
    assert events[-1][1] == {"provider": "fake", "model": "fake-model-1"}


def test_chat_stream_emits_status_and_sources_for_a_scoped_tool_call(client, use_provider, fake_mcp):
    use_provider(searching_provider())
    fake_mcp.reply(
        SEARCH,
        {"results": [{"id": "c1", "score": 0.7, "file_path": f"{ONEBID_ROOTS[REPO_NAMES[0]]}/a.ts",
                      "start_line": 1, "end_line": 5}]},
    )

    resp = client.post(
        "/api/chat/stream", json={"message": "auth?", "options": {"app": "onebid"}}
    )

    events = sse_events(resp.text)
    assert [name for name, _ in events] == ["token", "status", "token", "sources", "done"]
    assert SEARCH in events[1][1]["text"]
    assert events[3][1]["sources"][0]["file_path"].endswith("/a.ts")

    _name, args = fake_mcp.calls[-1]
    assert args["repos"] == REPO_NAMES
    assert args["repo_roots"] == [ONEBID_ROOTS[n] for n in REPO_NAMES]


def test_chat_stream_400_when_the_provider_is_not_configured(client, use_provider):
    use_provider(FakeProvider(configured=(False, "OPENAI_API_KEY is not set")))

    resp = client.post("/api/chat/stream", json={"message": "hi"})

    assert resp.status_code == 400
    assert resp.json()["detail"] == "OPENAI_API_KEY is not set"


def test_chat_stream_404_for_an_unknown_app(client, use_provider):
    use_provider(answering_provider())

    resp = client.post("/api/chat/stream", json={"message": "hi", "options": {"app": "nope"}})

    assert resp.status_code == 404


def test_chat_stream_503_when_mcp_is_down(client, use_provider, fake_mcp):
    use_provider(answering_provider())
    fake_mcp.is_alive = False

    assert client.post("/api/chat/stream", json={"message": "hi"}).status_code == 503
