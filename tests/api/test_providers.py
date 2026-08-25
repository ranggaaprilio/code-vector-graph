"""Tests for the chat providers: tool conversion, streaming, and provider selection."""

import asyncio
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from code_vector_graph.api.providers import (  # noqa: E402
    DEFAULT_DEEPSEEK_BASE_URL,
    build_provider,
    get_provider,
    reset_provider_cache,
    resolve_provider_name,
)
from code_vector_graph.api.providers.anthropic_provider import AnthropicProvider  # noqa: E402
from code_vector_graph.api.providers.openai_provider import OpenAIProvider  # noqa: E402

# The shape MCPSessionManager.get_tool_schemas() returns.
MCP_TOOLS = [
    {
        "name": "search_code_json",
        "description": "Search indexed code.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "top_k": {"type": "integer"}},
            "required": ["query"],
        },
    },
    # A tool with no description / no schema at all.
    {"name": "check_health"},
]

EMPTY_SCHEMA = {"type": "object", "properties": {}}


def drain(agen) -> list:
    """Collect an async generator into a list (no pytest-asyncio in this project)."""

    async def _run():
        return [ev async for ev in agen]

    return asyncio.run(_run())


# --------------------------------------------------------------------------- #
# convert_tools
# --------------------------------------------------------------------------- #


def test_anthropic_convert_tools_passthrough():
    tools = AnthropicProvider(api_key="k", model="m").convert_tools(MCP_TOOLS)

    assert tools == [
        {
            "name": "search_code_json",
            "description": "Search indexed code.",
            "input_schema": MCP_TOOLS[0]["input_schema"],
        },
        {"name": "check_health", "description": "", "input_schema": EMPTY_SCHEMA},
    ]


def test_openai_convert_tools_wraps_in_function_envelope():
    tools = OpenAIProvider(api_key="k", model="m").convert_tools(MCP_TOOLS)

    assert tools == [
        {
            "type": "function",
            "function": {
                "name": "search_code_json",
                "description": "Search indexed code.",
                "parameters": MCP_TOOLS[0]["input_schema"],
            },
        },
        {
            "type": "function",
            "function": {
                "name": "check_health",
                "description": "",
                "parameters": EMPTY_SCHEMA,
            },
        },
    ]


def test_convert_tools_handles_empty_list():
    assert AnthropicProvider(api_key="k", model="m").convert_tools([]) == []
    assert OpenAIProvider(api_key="k", model="m").convert_tools([]) == []


# --------------------------------------------------------------------------- #
# OpenAI-compatible streaming
# --------------------------------------------------------------------------- #


def chunk(content=None, tool_calls=None, finish_reason=None, reasoning=None):
    delta = SimpleNamespace(
        content=content, tool_calls=tool_calls or None, reasoning_content=reasoning
    )
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)])


def tc(index, call_id=None, name=None, arguments=None):
    return SimpleNamespace(
        index=index, id=call_id, function=SimpleNamespace(name=name, arguments=arguments)
    )


class FakeStream:
    def __init__(self, chunks):
        self._chunks = list(chunks)

    def __aiter__(self):
        async def gen():
            for c in self._chunks:
                yield c

        return gen()


class FakeCompletions:
    def __init__(self, chunks):
        self.chunks = chunks
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return FakeStream(self.chunks)


class FakeOpenAIClient:
    def __init__(self, chunks):
        self.completions = FakeCompletions(chunks)
        self.chat = SimpleNamespace(completions=self.completions)


def openai_events(chunks, tools=None):
    client = FakeOpenAIClient(chunks)
    provider = OpenAIProvider(api_key="k", model="gpt-test", client=client)
    events = drain(provider.stream_turn("sys", [{"role": "user", "content": "hi"}], tools or []))
    return events, client


def test_openai_stream_accumulates_fragmented_tool_arguments():
    """Text deltas interleave with a tool call whose arguments arrive in three pieces."""
    chunks = [
        chunk(content="Looking"),
        chunk(tool_calls=[tc(0, call_id="call_abc", name="search_code_json", arguments='{"query": "au')]),
        chunk(content=" for it"),
        chunk(tool_calls=[tc(0, arguments='th", "top_k"')]),
        chunk(content="…"),
        chunk(tool_calls=[tc(0, arguments=": 5}")], finish_reason="tool_calls"),
        SimpleNamespace(choices=[]),  # trailing usage-only chunk
    ]
    events, client = openai_events(chunks, tools=[{"type": "function", "function": {"name": "x"}}])

    assert [e.type for e in events] == ["text", "text", "text", "tool_call", "stop"]
    assert [e.text for e in events[:3]] == ["Looking", " for it", "…"]

    call = events[3].tool_call
    assert call.id == "call_abc"
    assert call.name == "search_code_json"
    assert call.arguments == {"query": "auth", "top_k": 5}

    assert events[-1].stop_reason == "tool_calls"
    assert client.completions.kwargs["stream"] is True
    assert client.completions.kwargs["model"] == "gpt-test"
    assert "tools" in client.completions.kwargs


def test_openai_stream_omits_empty_tools_and_text_only_turn():
    events, client = openai_events([chunk(content="done"), chunk(finish_reason="stop")])

    assert [e.type for e in events] == ["text", "stop"]
    assert events[-1].stop_reason == "stop"
    assert "tools" not in client.completions.kwargs


def test_openai_stream_invalid_json_arguments_become_empty_dict():
    chunks = [
        chunk(tool_calls=[tc(0, call_id="c1", name="search_code_json", arguments='{"query": ')]),
        chunk(finish_reason="tool_calls"),
    ]
    events, _ = openai_events(chunks)

    assert [e.type for e in events] == ["tool_call", "stop"]
    assert events[0].tool_call.arguments == {}
    assert events[0].tool_call.name == "search_code_json"


def test_openai_stream_non_object_arguments_become_empty_dict():
    chunks = [chunk(tool_calls=[tc(0, call_id="c1", name="t", arguments="[1, 2]")])]
    events, _ = openai_events(chunks)

    assert events[0].tool_call.arguments == {}
    # No finish_reason in the stream: inferred from the pending tool calls.
    assert events[-1].stop_reason == "tool_calls"


def test_openai_stream_ignores_reasoning_content():
    """DeepSeek v4 thinking models emit reasoning_content; it must not become tokens."""
    chunks = [
        chunk(reasoning="the user wants auth code"),
        chunk(content="Answer."),
        chunk(reasoning="more thinking", finish_reason="stop"),
    ]
    events, _ = openai_events(chunks)

    assert [e.type for e in events] == ["text", "stop"]
    assert events[0].text == "Answer."


def test_openai_stream_multiple_tool_calls_keep_index_order():
    chunks = [
        chunk(tool_calls=[tc(1, call_id="b", name="two", arguments='{"i": 2}')]),
        chunk(tool_calls=[tc(0, call_id="a", name="one", arguments='{"i": 1}')]),
        chunk(finish_reason="tool_calls"),
    ]
    events, _ = openai_events(chunks)

    calls = [e.tool_call for e in events if e.type == "tool_call"]
    assert [c.name for c in calls] == ["one", "two"]
    assert [c.arguments["i"] for c in calls] == [1, 2]


def test_openai_stream_tool_call_without_index_or_id():
    chunks = [chunk(tool_calls=[tc(None, name="one", arguments="{}")], finish_reason="tool_calls")]
    events, _ = openai_events(chunks)

    call = events[0].tool_call
    assert call.arguments == {}
    assert call.id == "call_0"  # synthesised


# --------------------------------------------------------------------------- #
# Anthropic streaming
# --------------------------------------------------------------------------- #


class FakeAnthropicStream:
    def __init__(self, events, final):
        self._events = list(events)
        self._final = final
        self.entered = False
        self.exited = False

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, *exc):
        self.exited = True
        return False

    def __aiter__(self):
        async def gen():
            for e in self._events:
                yield e

        return gen()

    async def get_final_message(self):
        return self._final


class FakeAnthropicMessages:
    def __init__(self, stream):
        self._stream = stream
        self.kwargs = None

    def stream(self, **kwargs):
        self.kwargs = kwargs
        return self._stream


class FakeAnthropicClient:
    def __init__(self, stream):
        self.messages = FakeAnthropicMessages(stream)


def text_delta(text):
    return SimpleNamespace(
        type="content_block_delta", delta=SimpleNamespace(type="text_delta", text=text)
    )


def test_anthropic_stream_maps_text_then_tool_use_then_stop():
    events_in = [
        SimpleNamespace(type="message_start"),
        text_delta("Let me "),
        # partial tool JSON deltas are not text and must be ignored
        SimpleNamespace(
            type="content_block_delta",
            delta=SimpleNamespace(type="input_json_delta", partial_json='{"query"'),
        ),
        text_delta("search."),
        SimpleNamespace(type="message_stop"),
    ]
    final = SimpleNamespace(
        content=[
            SimpleNamespace(type="text", text="Let me search."),
            SimpleNamespace(
                type="tool_use", id="toolu_1", name="search_code_json", input={"query": "auth"}
            ),
        ],
        stop_reason="tool_use",
    )
    stream = FakeAnthropicStream(events_in, final)
    provider = AnthropicProvider(api_key="k", model="claude-test", client=FakeAnthropicClient(stream))

    events = drain(provider.stream_turn("SYSTEM", [{"role": "user", "content": "hi"}], [{"name": "t"}]))

    assert [e.type for e in events] == ["text", "text", "tool_call", "stop"]
    assert [e.text for e in events[:2]] == ["Let me ", "search."]
    call = events[2].tool_call
    assert (call.id, call.name, call.arguments) == ("toolu_1", "search_code_json", {"query": "auth"})
    assert events[-1].stop_reason == "tool_use"
    assert events[-1].raw is final
    assert stream.entered and stream.exited

    kwargs = provider._client.messages.kwargs
    assert kwargs["system"] == "SYSTEM"
    assert kwargs["model"] == "claude-test"
    assert kwargs["tools"] == [{"name": "t"}]


def test_anthropic_stream_omits_empty_tools_and_handles_text_only_final():
    final = SimpleNamespace(content=[SimpleNamespace(type="text", text="hi")], stop_reason="end_turn")
    stream = FakeAnthropicStream([text_delta("hi")], final)
    provider = AnthropicProvider(api_key="k", model="m", client=FakeAnthropicClient(stream))

    events = drain(provider.stream_turn("s", [], []))

    assert [e.type for e in events] == ["text", "stop"]
    assert "tools" not in provider._client.messages.kwargs


def test_anthropic_init_messages_keeps_system_out_of_messages():
    provider = AnthropicProvider(api_key="k", model="m")
    msgs = provider.init_messages("SYS", [{"role": "user", "content": "old"}], "new")

    assert msgs == [{"role": "user", "content": "old"}, {"role": "user", "content": "new"}]
    assert all(m["role"] != "system" for m in msgs)


def test_openai_init_messages_prepends_system():
    provider = OpenAIProvider(api_key="k", model="m")
    msgs = provider.init_messages("SYS", [{"role": "assistant", "content": "old"}], "new")

    assert msgs[0] == {"role": "system", "content": "SYS"}
    assert msgs[-1] == {"role": "user", "content": "new"}


# --------------------------------------------------------------------------- #
# Provider selection
# --------------------------------------------------------------------------- #

CHAT_ENV = (
    "CVG_CHAT_PROVIDER",
    "CVG_CHAT_MODEL",
    "CVG_CHAT_BASE_URL",
    "CVG_CHAT_API_KEY",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
)


@pytest.fixture
def chat_env(monkeypatch):
    """Empty chat environment; the provider cache is cleared before and after."""
    for var in CHAT_ENV:
        monkeypatch.delenv(var, raising=False)
    reset_provider_cache()
    yield monkeypatch
    reset_provider_cache()


def test_explicit_anthropic_provider(chat_env):
    chat_env.setenv("CVG_CHAT_PROVIDER", "anthropic")

    provider = get_provider()

    assert isinstance(provider, AnthropicProvider)
    assert provider.name == "anthropic"
    assert provider.model == "claude-sonnet-4-6"
    assert provider.base_url is None
    assert provider.is_configured() == (False, "ANTHROPIC_API_KEY is not set")


def test_explicit_deepseek_provider_uses_openai_client_and_default_base_url(chat_env):
    chat_env.setenv("CVG_CHAT_PROVIDER", "deepseek")
    chat_env.setenv("DEEPSEEK_API_KEY", "ds-key")

    provider = get_provider()

    assert isinstance(provider, OpenAIProvider)
    assert provider.name == "deepseek"
    assert provider.model == "deepseek-v4-flash"
    assert provider.base_url == DEFAULT_DEEPSEEK_BASE_URL
    assert provider.api_key == "ds-key"
    assert provider.is_configured() == (True, "")


def test_explicit_openai_provider(chat_env):
    chat_env.setenv("CVG_CHAT_PROVIDER", "openai")
    chat_env.setenv("OPENAI_API_KEY", "oa-key")
    chat_env.setenv("OPENAI_BASE_URL", "https://proxy.internal/v1")

    provider = get_provider()

    assert isinstance(provider, OpenAIProvider)
    assert provider.name == "openai"
    assert provider.model == "gpt-4o-mini"
    assert provider.base_url == "https://proxy.internal/v1"
    assert provider.is_configured() == (True, "")


def test_unsupported_provider_raises(chat_env):
    chat_env.setenv("CVG_CHAT_PROVIDER", "llamafile")

    with pytest.raises(ValueError, match="CVG_CHAT_PROVIDER"):
        get_provider()


def test_provider_name_is_case_insensitive(chat_env):
    chat_env.setenv("CVG_CHAT_PROVIDER", "  DeepSeek ")
    chat_env.setenv("DEEPSEEK_API_KEY", "ds")

    assert get_provider().name == "deepseek"


@pytest.mark.parametrize(
    "env, expected",
    [
        ({"ANTHROPIC_API_KEY": "a", "DEEPSEEK_API_KEY": "d", "OPENAI_API_KEY": "o"}, "anthropic"),
        ({"DEEPSEEK_API_KEY": "d", "OPENAI_API_KEY": "o"}, "deepseek"),
        ({"OPENAI_API_KEY": "o"}, "openai"),
        ({}, "openai"),
    ],
)
def test_auto_detect_order(chat_env, env, expected):
    for k, v in env.items():
        chat_env.setenv(k, v)

    assert get_provider().name == expected


def test_auto_detect_without_any_key_reports_missing_openai_key(chat_env):
    provider = get_provider()

    assert provider.name == "openai"
    assert provider.is_configured() == (False, "OPENAI_API_KEY is not set")


def test_anthropic_missing_key_reason_names_env_var(chat_env):
    chat_env.setenv("CVG_CHAT_PROVIDER", "anthropic")
    ok, reason = get_provider().is_configured()

    assert ok is False and reason == "ANTHROPIC_API_KEY is not set"


def test_deepseek_missing_key_reason_names_env_var(chat_env):
    chat_env.setenv("CVG_CHAT_PROVIDER", "deepseek")
    ok, reason = get_provider().is_configured()

    assert ok is False and reason == "DEEPSEEK_API_KEY is not set"


def test_cvg_chat_overrides_win_over_provider_specific_env(chat_env):
    chat_env.setenv("CVG_CHAT_PROVIDER", "deepseek")
    chat_env.setenv("DEEPSEEK_API_KEY", "ds-key")
    chat_env.setenv("DEEPSEEK_BASE_URL", "https://deepseek.example")
    chat_env.setenv("CVG_CHAT_API_KEY", "override-key")
    chat_env.setenv("CVG_CHAT_MODEL", "deepseek-v4-pro")
    chat_env.setenv("CVG_CHAT_BASE_URL", "https://gateway.internal")

    provider = get_provider()

    assert provider.api_key == "override-key"
    assert provider.model == "deepseek-v4-pro"
    assert provider.base_url == "https://gateway.internal"


def test_anthropic_model_env_used_when_cvg_chat_model_unset(chat_env):
    chat_env.setenv("CVG_CHAT_PROVIDER", "anthropic")
    chat_env.setenv("ANTHROPIC_API_KEY", "a")
    chat_env.setenv("ANTHROPIC_MODEL", "claude-opus-4-1")

    assert get_provider().model == "claude-opus-4-1"

    reset_provider_cache()
    chat_env.setenv("CVG_CHAT_MODEL", "claude-haiku-4-5")
    assert get_provider().model == "claude-haiku-4-5"


def test_deepseek_base_url_env_used_when_cvg_chat_base_url_unset(chat_env):
    chat_env.setenv("CVG_CHAT_PROVIDER", "deepseek")
    chat_env.setenv("DEEPSEEK_API_KEY", "ds")
    chat_env.setenv("DEEPSEEK_BASE_URL", "https://deepseek.example")

    assert get_provider().base_url == "https://deepseek.example"


def test_get_provider_is_cached_until_reset(chat_env):
    chat_env.setenv("CVG_CHAT_PROVIDER", "openai")
    chat_env.setenv("OPENAI_API_KEY", "o")

    first = get_provider()
    assert get_provider() is first

    chat_env.setenv("CVG_CHAT_PROVIDER", "anthropic")
    assert get_provider() is first  # env change alone does not invalidate

    reset_provider_cache()
    second = get_provider()
    assert second is not first and second.name == "anthropic"


def test_build_provider_accepts_an_explicit_settings_snapshot():
    provider = build_provider(
        {
            "CVG_CHAT_PROVIDER": "openai",
            "CVG_CHAT_MODEL": "gpt-5",
            "CVG_CHAT_BASE_URL": "",
            "CVG_CHAT_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
            "ANTHROPIC_MODEL": "claude-sonnet-4-6",
            "OPENAI_API_KEY": "sk-test",
            "OPENAI_BASE_URL": "",
            "DEEPSEEK_API_KEY": "",
            "DEEPSEEK_BASE_URL": DEFAULT_DEEPSEEK_BASE_URL,
        }
    )

    assert (provider.name, provider.model, provider.api_key) == ("openai", "gpt-5", "sk-test")
    assert provider.base_url is None


@pytest.mark.parametrize(
    "settings, expected",
    [
        ({"CVG_CHAT_PROVIDER": "openai", "ANTHROPIC_API_KEY": "a", "DEEPSEEK_API_KEY": "d"}, "openai"),
        ({"CVG_CHAT_PROVIDER": "", "ANTHROPIC_API_KEY": "a", "DEEPSEEK_API_KEY": ""}, "anthropic"),
        ({"CVG_CHAT_PROVIDER": "", "ANTHROPIC_API_KEY": "", "DEEPSEEK_API_KEY": "d"}, "deepseek"),
        ({"CVG_CHAT_PROVIDER": "", "ANTHROPIC_API_KEY": "", "DEEPSEEK_API_KEY": ""}, "openai"),
    ],
)
def test_resolve_provider_name(settings, expected):
    assert resolve_provider_name(settings) == expected
