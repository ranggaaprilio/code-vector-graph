"""Tests for the provider-agnostic tool-use loop in api/llm.py."""

import asyncio
import json

import pytest

pytest.importorskip("fastapi")

from code_vector_graph.api.llm import (  # noqa: E402
    BASE_SYSTEM_PROMPT,
    MAX_TOOL_ROUNDS,
    _parse_sources,
    apply_tool_defaults,
    build_system_prompt,
    chat_complete,
    chat_stream,
)

from .conftest import (  # noqa: E402
    ONEBID_ROOTS,
    FakeMCP,
    FakeProvider,
    make_repo,
    make_scope,
)

REPO_NAMES = list(ONEBID_ROOTS)
SEARCH = "search_code_json"


def run(coro):
    return asyncio.run(coro)


def collect(**kwargs) -> list[dict]:
    async def _run():
        return [ev async for ev in chat_stream(**kwargs)]

    return run(_run())


def types_of(events) -> list[str]:
    return [e["type"] for e in events]


def only(events, kind) -> list[dict]:
    return [e for e in events if e["type"] == kind]


def two_round_provider(tool_args=None, first_text="Looking…", final_text="The answer."):
    """Round 1: text + one search tool call. Round 2: the final answer."""
    return FakeProvider(
        [
            [
                FakeProvider.text(first_text),
                FakeProvider.call(SEARCH, tool_args if tool_args is not None else {"query": "x"}),
                FakeProvider.stop("tool_use"),
            ],
            [FakeProvider.text(final_text), FakeProvider.stop("end_turn")],
        ]
    )


def mcp_with_results(results) -> FakeMCP:
    mcp = FakeMCP()
    mcp.reply(SEARCH, {"results": results})
    return mcp


CODE_HIT = {
    "id": "c1",
    "score": 0.9,
    "file_path": f"{ONEBID_ROOTS[REPO_NAMES[0]]}/src/auth.ts",
    "start_line": 10,
    "end_line": 30,
    "function_name": "login",
    "repo": REPO_NAMES[0],
}
WIKI_HIT = {
    "id": "w1",
    "score": 0.8,
    "source": "wiki",
    "term": "AuthService",
    "summary": "Handles login and token refresh.",
    "file_path": "src/auth.ts",
    "start_line": None,
    "repo": REPO_NAMES[1],
}


# --------------------------------------------------------------------------- #
# build_system_prompt
# --------------------------------------------------------------------------- #


def test_build_system_prompt_without_scope_is_the_base_prompt():
    prompt = build_system_prompt(None)

    assert prompt == BASE_SYSTEM_PROMPT
    assert "search_code_json" in prompt
    assert "repos=" not in prompt


def test_build_system_prompt_names_app_repos_and_roots():
    prompt = build_system_prompt(make_scope())

    assert prompt.startswith(BASE_SYSTEM_PROMPT)
    assert "application `onebid`" in prompt
    assert "2 repositories" in prompt
    for name in REPO_NAMES:
        assert f"`{name}`" in prompt
        assert ONEBID_ROOTS[name] in prompt
    assert f"repos={json.dumps(REPO_NAMES)}" in prompt
    # derived repos → the prompt also asks for repo_roots
    assert "repo_roots=" in prompt
    assert "identity derived from file paths" in prompt


def test_build_system_prompt_single_repo_scope():
    scope = make_scope(repos=[make_repo(REPO_NAMES[0])])
    prompt = build_system_prompt(scope)

    assert f"repository `{REPO_NAMES[0]}` of application `onebid`" in prompt
    assert "2 repositories" not in prompt


def test_build_system_prompt_recorded_scope_omits_repo_roots():
    scope = make_scope(repos=[make_repo(n, source="recorded") for n in REPO_NAMES])
    prompt = build_system_prompt(scope)

    assert "repo_roots=" not in prompt
    assert "identity derived from file paths" not in prompt
    assert f"repos={json.dumps(REPO_NAMES)}" in prompt


def test_build_system_prompt_survives_a_scope_without_repo_objects():
    class BareScope:
        app = "onebid"
        repos: list = []
        repo_names = ["solo"]

    prompt = build_system_prompt(BareScope())

    assert "`solo`" in prompt
    assert 'repos=["solo"]' in prompt


# --------------------------------------------------------------------------- #
# apply_tool_defaults
# --------------------------------------------------------------------------- #


def test_apply_tool_defaults_injects_scope_and_options():
    args = apply_tool_defaults(
        {"query": "auth"}, make_scope(), {"mode": "hybrid", "top_k": 8, "source": "all"}, SEARCH
    )

    assert args["query"] == "auth"
    assert args["repos"] == REPO_NAMES
    assert args["repo_roots"] == [ONEBID_ROOTS[n] for n in REPO_NAMES]
    assert args["mode"] == "hybrid"
    assert args["top_k"] == 8
    assert args["source"] == "all"


def test_apply_tool_defaults_omits_repo_roots_for_recorded_scope():
    scope = make_scope(repos=[make_repo(n, source="recorded") for n in REPO_NAMES])
    args = apply_tool_defaults({"query": "auth"}, scope, {}, SEARCH)

    assert args["repos"] == REPO_NAMES
    assert "repo_roots" not in args


def test_apply_tool_defaults_never_overrides_the_model():
    args = apply_tool_defaults(
        {"query": "auth", "repos": ["only_this"], "top_k": 3, "mode": "graph"},
        make_scope(),
        {"top_k": 25, "mode": "vector", "source": "wiki"},
        SEARCH,
    )

    assert args["repos"] == ["only_this"]
    assert args["top_k"] == 3
    assert args["mode"] == "graph"
    assert args["source"] == "wiki"  # the model left this one out


def test_apply_tool_defaults_skips_empty_options_and_non_search_tools():
    assert apply_tool_defaults({"q": 1}, make_scope(), {}, "check_health") == {"q": 1}
    assert "mode" not in apply_tool_defaults({}, None, {"mode": "", "top_k": None}, SEARCH)
    assert apply_tool_defaults(None, None, None, SEARCH) == {}


# --------------------------------------------------------------------------- #
# chat_stream: happy path
# --------------------------------------------------------------------------- #


def test_chat_stream_two_rounds_event_order_and_scope_injection():
    provider = two_round_provider()
    mcp = mcp_with_results([CODE_HIT])

    events = collect(
        message="how does login work?",
        history=[{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}],
        mcp=mcp,
        options={"top_k": 7, "mode": "hybrid"},
        scope=make_scope(),
        provider=provider,
    )

    assert types_of(events) == ["token", "status", "token", "sources", "done"]
    assert events[0]["text"] == "Looking…"
    assert "search_code_json" in events[1]["text"]
    assert events[2]["text"] == "The answer."
    assert events[-1] == {"type": "done", "provider": "fake", "model": "fake-model-1"}

    tool_name, args = mcp.calls[-1]
    assert tool_name == SEARCH
    assert args["query"] == "x"
    assert args["repos"] == REPO_NAMES
    assert args["repo_roots"] == [ONEBID_ROOTS[n] for n in REPO_NAMES]
    assert args["top_k"] == 7 and args["mode"] == "hybrid"

    # Round 2 got the scoped system prompt plus assistant + tool messages.
    assert len(provider.turns) == 2
    system, messages, _tools = provider.turns[1]
    assert "application `onebid`" in system
    assert [m["role"] for m in messages][-2:] == ["assistant", "tool"]


def test_chat_stream_recorded_scope_sends_repos_without_repo_roots():
    scope = make_scope(repos=[make_repo(n, source="recorded") for n in REPO_NAMES])
    mcp = mcp_with_results([])

    collect(message="q", history=[], mcp=mcp, options=None, scope=scope, provider=two_round_provider())

    _name, args = mcp.calls[-1]
    assert args["repos"] == REPO_NAMES
    assert "repo_roots" not in args


def test_chat_stream_without_scope_sends_only_the_model_arguments():
    mcp = mcp_with_results([])

    collect(message="q", history=[], mcp=mcp, options={}, scope=None, provider=two_round_provider())

    _name, args = mcp.calls[-1]
    assert args == {"query": "x"}


def test_chat_stream_does_not_override_model_supplied_options():
    mcp = mcp_with_results([])
    provider = two_round_provider(tool_args={"query": "x", "top_k": 3, "mode": "graph"})

    collect(
        message="q",
        history=[],
        mcp=mcp,
        options={"top_k": 50, "mode": "vector"},
        scope=make_scope(),
        provider=provider,
    )

    _name, args = mcp.calls[-1]
    assert args["top_k"] == 3
    assert args["mode"] == "graph"


def test_chat_stream_single_round_answer_has_no_status_event():
    provider = FakeProvider([[FakeProvider.text("No tools needed."), FakeProvider.stop()]])

    events = collect(message="hi", history=[], mcp=FakeMCP(), options=None, provider=provider)

    assert types_of(events) == ["token", "sources", "done"]
    assert only(events, "sources")[0]["data"] == []


# --------------------------------------------------------------------------- #
# sources
# --------------------------------------------------------------------------- #


def test_chat_stream_sources_include_wiki_items_and_dedupe():
    mcp = mcp_with_results([CODE_HIT, dict(CODE_HIT), WIKI_HIT])

    events = collect(
        message="q", history=[], mcp=mcp, options=None, scope=make_scope(),
        provider=two_round_provider(),
    )
    sources = only(events, "sources")[0]["data"]

    assert len(sources) == 2  # the duplicated code hit collapsed
    code, wiki = sources
    assert code["source"] == "code"
    assert code["file_path"] == CODE_HIT["file_path"]
    assert code["function_name"] == "login"
    assert code["repo"] == REPO_NAMES[0]

    assert wiki["source"] == "wiki"
    assert wiki["title"] == "AuthService"
    assert wiki["summary"] == "Handles login and token refresh."
    assert wiki["repo"] == REPO_NAMES[1]


def test_chat_stream_sources_carry_wiki_context():
    hit = dict(CODE_HIT, wiki_context={"title": "AuthService", "summary": "Handles login."})
    mcp = mcp_with_results([hit])

    events = collect(message="q", history=[], mcp=mcp, options=None, provider=two_round_provider())
    source = only(events, "sources")[0]["data"][0]

    assert source["wiki_context"]["title"] == "AuthService"


def test_parse_sources_ignores_other_tools_and_bad_payloads():
    assert _parse_sources([{"tool": "check_health", "raw": json.dumps({"results": [CODE_HIT]})}]) == []
    assert _parse_sources([{"tool": SEARCH, "raw": "not json"}]) == []
    assert _parse_sources([{"tool": SEARCH, "raw": json.dumps(["a"])}]) == []
    assert _parse_sources([{"tool": SEARCH, "raw": json.dumps({"results": ["nope"]})}]) == []
    assert _parse_sources([{"tool": SEARCH, "raw": None}]) == []


def test_parse_sources_titles_a_wiki_hit_without_a_term():
    raw = json.dumps({"results": [{"source": "wiki", "function_name": "login", "file_path": "a.ts"}]})

    (item,) = _parse_sources([{"tool": SEARCH, "raw": raw}])

    assert item["source"] == "wiki" and item["title"] == "login"


# --------------------------------------------------------------------------- #
# failure paths
# --------------------------------------------------------------------------- #


class BoomMCP(FakeMCP):
    async def call_tool(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        raise RuntimeError("mcp exploded")


def test_chat_stream_reports_tool_errors_and_keeps_going():
    provider = two_round_provider(final_text="Sorry, the search failed.")

    events = collect(
        message="q", history=[], mcp=BoomMCP(), options=None, scope=make_scope(), provider=provider
    )

    statuses = [e["text"] for e in only(events, "status")]
    assert any("Tool error: mcp exploded" in s for s in statuses)
    assert types_of(events)[-2:] == ["sources", "done"]
    assert only(events, "token")[-1]["text"] == "Sorry, the search failed."
    # the failed tool output was still fed back to the model
    _system, messages, _tools = provider.turns[1]
    assert json.loads(messages[-1]["content"]) == {"error": "mcp exploded", "results": []}


def test_chat_stream_forces_a_final_answer_after_max_tool_rounds():
    rounds = [
        [FakeProvider.call(SEARCH, {"query": f"q{i}"}, call_id=f"c{i}"), FakeProvider.stop("tool_use")]
        for i in range(MAX_TOOL_ROUNDS)
    ]
    rounds.append([FakeProvider.text("Here's what I found so far."), FakeProvider.stop("end_turn")])
    mcp = mcp_with_results([])
    provider = FakeProvider(rounds)

    events = collect(message="q", history=[], mcp=mcp, options=None, provider=provider)

    assert types_of(events) == ["status"] * MAX_TOOL_ROUNDS + ["status", "token", "sources", "done"]
    assert only(events, "token")[-1]["text"] == "Here's what I found so far."
    assert len(mcp.calls) == MAX_TOOL_ROUNDS
    # the forced final turn must not offer tools, so the model can't loop again
    _system, _messages, final_tools = provider.turns[-1]
    assert final_tools == []


def test_chat_stream_errors_when_the_provider_is_not_configured():
    provider = FakeProvider(configured=(False, "DEEPSEEK_API_KEY is not set"))

    events = collect(message="q", history=[], mcp=FakeMCP(), options=None, provider=provider)

    assert events == [{"type": "error", "text": "DEEPSEEK_API_KEY is not set"}]
    assert provider.turns == []


def test_chat_stream_errors_when_the_model_call_raises():
    class ExplodingProvider(FakeProvider):
        async def stream_turn(self, system, messages, tools):
            raise RuntimeError("401 unauthorized")
            yield  # pragma: no cover

    events = collect(message="q", history=[], mcp=FakeMCP(), options=None,
                     provider=ExplodingProvider())

    assert types_of(events) == ["error"]
    assert "401 unauthorized" in events[0]["text"]


# --------------------------------------------------------------------------- #
# chat_complete
# --------------------------------------------------------------------------- #


def test_chat_complete_collects_tokens_sources_and_provider():
    mcp = mcp_with_results([WIKI_HIT])

    result = run(
        chat_complete(
            message="q",
            history=[],
            mcp=mcp,
            options=None,
            scope=make_scope(),
            provider=two_round_provider(first_text="A", final_text="B"),
        )
    )

    assert result["answer"] == "AB"
    assert result["error"] is None
    assert result["provider"] == "fake" and result["model"] == "fake-model-1"
    assert result["sources"][0]["title"] == "AuthService"


def test_chat_complete_surfaces_the_error():
    provider = FakeProvider(configured=(False, "OPENAI_API_KEY is not set"))

    result = run(chat_complete(message="q", history=[], mcp=FakeMCP(), options=None, provider=provider))

    assert result["answer"] == ""
    assert result["error"] == "OPENAI_API_KEY is not set"
