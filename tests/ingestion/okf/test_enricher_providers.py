"""OKF enrichment provider selection: DeepSeek (cloud) vs oMLX (local).

No network: the OpenAI SDK client is replaced with a fake where needed.
"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from code_vector_graph.config import okf_llm_settings
from code_vector_graph.ingestion.okf.enricher import _call_llm, _parse_json_reply, make_client

_ENV_KEYS = (
    "OKF_LLM_PROVIDER", "OMLX_API_KEY", "OMLX_BASE_URL", "OMLX_MODEL",
    "OKF_MODEL_FLASH", "OKF_MODEL_PRO", "OKF_CONCURRENCY",
    "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL",
)


@pytest.fixture
def env(monkeypatch):
    for k in _ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def _resp(content: str, finish_reason: str = "stop"):
    return MagicMock(choices=[MagicMock(message=MagicMock(content=content), finish_reason=finish_reason)])


def _client(content: str = '{"summary": "ok"}'):
    client = MagicMock()
    client.chat.completions.create.return_value = _resp(content)
    return client


# --- settings resolution ---------------------------------------------------

def test_settings_default_to_deepseek(env):
    env.setenv("DEEPSEEK_API_KEY", "ds")
    s = okf_llm_settings()
    assert s.provider == "deepseek" and s.local is False
    assert s.api_key == "ds" and s.key_env == "DEEPSEEK_API_KEY"
    assert s.base_url == "https://api.deepseek.com"
    assert (s.model_flash, s.model_pro) == ("deepseek-v4-flash", "deepseek-v4-pro")
    assert s.concurrency == 6


def test_settings_omlx_defaults(env):
    env.setenv("OKF_LLM_PROVIDER", "omlx")
    s = okf_llm_settings()
    assert s.provider == "omlx" and s.local is True
    assert s.key_env == "OMLX_API_KEY" and s.api_key == ""
    assert s.base_url == "http://localhost:8000/v1"
    # one local model serves both tiers
    assert s.model_flash == s.model_pro == "gemma-4-e2b-it-4bit"
    assert s.concurrency == 2


def test_settings_omlx_overrides(env):
    env.setenv("OKF_LLM_PROVIDER", "OMLX")  # case-insensitive
    env.setenv("OMLX_MODEL", "Qwen3-8B-4bit")
    env.setenv("OKF_MODEL_PRO", "gemma-4-e2b-it-4bit")
    env.setenv("OMLX_BASE_URL", "http://10.0.0.5:8000/v1")
    env.setenv("OMLX_API_KEY", "k")
    env.setenv("OKF_CONCURRENCY", "4")
    s = okf_llm_settings()
    assert s.provider == "omlx"
    assert s.model_flash == "Qwen3-8B-4bit"       # OMLX_MODEL is the tier default
    assert s.model_pro == "gemma-4-e2b-it-4bit"   # explicit tier wins
    assert s.base_url == "http://10.0.0.5:8000/v1" and s.api_key == "k"
    assert s.concurrency == 4


def test_settings_reject_unknown_provider(env):
    env.setenv("OKF_LLM_PROVIDER", "ollama")
    with pytest.raises(ValueError, match="OKF_LLM_PROVIDER"):
        okf_llm_settings()


# --- JSON reply parsing (local models are less strict) -------------------

@pytest.mark.parametrize("content", [
    '{"summary": "x"}',
    '```json\n{"summary": "x"}\n```',
    '```\n{"summary": "x"}\n```',
    'Here is the entry:\n{"summary": "x"}\nHope this helps!',
])
def test_parse_json_reply_recovers_object(content):
    assert _parse_json_reply(content) == {"summary": "x"}


@pytest.mark.parametrize("content", ["", "   ", "not json", "[1, 2]", "```json\n```"])
def test_parse_json_reply_raises_when_unrecoverable(content):
    with pytest.raises(json.JSONDecodeError):
        _parse_json_reply(content)


# --- per-provider request shaping -----------------------------------------

def test_call_llm_deepseek_request_shape():
    client = _client()
    _call_llm(client, "deepseek-v4-flash", "sys", "usr", provider="deepseek",
              thinking=True, reasoning_effort="low")
    kw = client.chat.completions.create.call_args.kwargs
    assert kw["extra_body"] == {"thinking": {"type": "enabled"}}
    assert kw["reasoning_effort"] == "low"
    assert kw["response_format"] == {"type": "json_object"}


def test_call_llm_omlx_request_shape():
    client = _client()
    _call_llm(client, "gemma-4-e2b-it-4bit", "sys", "usr", provider="omlx",
              thinking=True, reasoning_effort="low")
    kw = client.chat.completions.create.call_args.kwargs
    # oMLX: thinking is a chat-template kwarg; DeepSeek-only fields are not sent
    assert kw["extra_body"] == {"chat_template_kwargs": {"enable_thinking": True}}
    assert "reasoning_effort" not in kw
    assert kw["response_format"] == {"type": "json_object"}
    assert kw["model"] == "gemma-4-e2b-it-4bit"


def test_call_llm_defaults_thinking_off_for_omlx():
    client = _client()
    _call_llm(client, "m", "sys", "usr", provider="omlx")
    assert client.chat.completions.create.call_args.kwargs["extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False}
    }


def test_call_llm_provider_comes_from_env(env):
    env.setenv("OKF_LLM_PROVIDER", "omlx")
    client = _client()
    _call_llm(client, "m", "sys", "usr")
    assert "chat_template_kwargs" in client.chat.completions.create.call_args.kwargs["extra_body"]


def test_call_llm_accepts_fenced_json():
    client = _client('```json\n{"summary": "fenced"}\n```')
    assert _call_llm(client, "m", "sys", "usr", provider="omlx") == {"summary": "fenced"}


def test_call_llm_truncation_is_a_decode_error():
    client = MagicMock()
    client.chat.completions.create.return_value = _resp('{"summary": "cut', finish_reason="length")
    with pytest.raises(json.JSONDecodeError, match="truncated"):
        _call_llm(client, "m", "sys", "usr", provider="omlx")


# --- make_client ------------------------------------------------------------

class _FakeOpenAI:
    """Stand-in for openai.OpenAI capturing constructor kwargs and serving /models."""
    instances: list = []
    models_result = None      # list[str] | Exception

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.models = SimpleNamespace(list=self._list)
        _FakeOpenAI.instances.append(self)

    def _list(self):
        r = _FakeOpenAI.models_result
        if isinstance(r, Exception):
            raise r
        return SimpleNamespace(data=[SimpleNamespace(id=m) for m in (r or [])])


@pytest.fixture
def fake_openai(monkeypatch):
    pytest.importorskip("openai")
    _FakeOpenAI.instances = []
    _FakeOpenAI.models_result = ["gemma-4-e2b-it-4bit", "Qwen3-8B-4bit"]
    monkeypatch.setattr("openai.OpenAI", _FakeOpenAI)
    return _FakeOpenAI


def test_make_client_deepseek_requires_key(env, fake_openai):
    with pytest.raises(ValueError) as exc:
        make_client()
    assert "DEEPSEEK_API_KEY" in str(exc.value) and "OKF_LLM_PROVIDER=omlx" in str(exc.value)
    assert fake_openai.instances == []


def test_make_client_deepseek_does_not_probe(env, fake_openai):
    env.setenv("DEEPSEEK_API_KEY", "ds")
    fake_openai.models_result = RuntimeError("must not be called")
    client = make_client()
    assert client.kwargs == {"api_key": "ds", "base_url": "https://api.deepseek.com"}


def test_make_client_omlx_uses_placeholder_key_and_probes(env, fake_openai):
    env.setenv("OKF_LLM_PROVIDER", "omlx")
    client = make_client()
    assert client.kwargs == {"api_key": "omlx", "base_url": "http://localhost:8000/v1"}


def test_make_client_omlx_unknown_model(env, fake_openai):
    env.setenv("OKF_LLM_PROVIDER", "omlx")
    env.setenv("OMLX_MODEL", "llama-3-8b")
    with pytest.raises(ValueError, match="not served") as exc:
        make_client()
    assert "gemma-4-e2b-it-4bit" in str(exc.value)  # lists what IS available


def test_make_client_omlx_server_down(env, fake_openai):
    env.setenv("OKF_LLM_PROVIDER", "omlx")
    fake_openai.models_result = ConnectionError("refused")
    with pytest.raises(ValueError, match="is the server running"):
        make_client()


def test_make_client_omlx_bad_key(env, fake_openai):
    env.setenv("OKF_LLM_PROVIDER", "omlx")
    env.setenv("OMLX_API_KEY", "wrong")
    err = RuntimeError("401")
    err.status_code = 401
    fake_openai.models_result = err
    with pytest.raises(ValueError, match="OMLX_API_KEY"):
        make_client()


def test_make_client_probe_can_be_disabled(env, fake_openai):
    env.setenv("OKF_LLM_PROVIDER", "omlx")
    fake_openai.models_result = ConnectionError("refused")
    client = make_client(probe=False)  # e.g. dashboard startup
    assert client.kwargs["base_url"] == "http://localhost:8000/v1"
