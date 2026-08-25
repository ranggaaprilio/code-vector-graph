"""Chat provider selection for the dashboard.

    provider = CVG_CHAT_PROVIDER            (anthropic | openai | deepseek)
             or auto: anthropic if ANTHROPIC_API_KEY, else deepseek if DEEPSEEK_API_KEY,
                      else openai
    model    = CVG_CHAT_MODEL   or per-provider default
    base_url = CVG_CHAT_BASE_URL or DEEPSEEK_BASE_URL (deepseek) / OPENAI_BASE_URL (openai)
    api_key  = CVG_CHAT_API_KEY  or the provider's own key variable

Settings are re-read from the environment on each `get_provider()` cache miss so
tests can monkeypatch `os.environ` and call `reset_provider_cache()`.
"""

from __future__ import annotations

import os
from functools import lru_cache

from code_vector_graph.api.providers.base import ChatProvider, LLMEvent, ToolCall

PROVIDERS = ("anthropic", "openai", "deepseek")

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o-mini",
    "deepseek": "deepseek-v4-flash",
}
KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
}
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"


def _settings() -> dict[str, str]:
    """Snapshot of the chat-related environment (after .env has been loaded)."""
    # Importing api.config guarantees load_dotenv() has run; values are then read
    # from os.environ (not the module constants) so runtime/test overrides win.
    import code_vector_graph.api.config  # noqa: F401

    env = os.environ
    return {
        "CVG_CHAT_PROVIDER": env.get("CVG_CHAT_PROVIDER", "").strip().lower(),
        "CVG_CHAT_MODEL": env.get("CVG_CHAT_MODEL", "").strip(),
        "CVG_CHAT_BASE_URL": env.get("CVG_CHAT_BASE_URL", "").strip(),
        "CVG_CHAT_API_KEY": env.get("CVG_CHAT_API_KEY", "").strip(),
        "ANTHROPIC_API_KEY": env.get("ANTHROPIC_API_KEY", "").strip(),
        "ANTHROPIC_MODEL": env.get("ANTHROPIC_MODEL", "").strip() or DEFAULT_MODELS["anthropic"],
        "OPENAI_API_KEY": env.get("OPENAI_API_KEY", "").strip(),
        "OPENAI_BASE_URL": env.get("OPENAI_BASE_URL", "").strip(),
        "DEEPSEEK_API_KEY": env.get("DEEPSEEK_API_KEY", "").strip(),
        "DEEPSEEK_BASE_URL": env.get("DEEPSEEK_BASE_URL", "").strip() or DEFAULT_DEEPSEEK_BASE_URL,
    }


def resolve_provider_name(s: dict[str, str]) -> str:
    name = s["CVG_CHAT_PROVIDER"]
    if name:
        if name not in PROVIDERS:
            raise ValueError(
                f"CVG_CHAT_PROVIDER={name!r} is not supported; use one of {', '.join(PROVIDERS)}"
            )
        return name
    if s["ANTHROPIC_API_KEY"]:
        return "anthropic"
    if s["DEEPSEEK_API_KEY"]:
        return "deepseek"
    return "openai"


def build_provider(s: dict[str, str] | None = None) -> ChatProvider:
    """Construct (uncached) the provider described by the settings snapshot."""
    s = s or _settings()
    name = resolve_provider_name(s)
    key_env = KEY_ENV[name]
    api_key = s["CVG_CHAT_API_KEY"] or s[key_env]

    if name == "anthropic":
        from code_vector_graph.api.providers.anthropic_provider import AnthropicProvider

        model = s["CVG_CHAT_MODEL"] or s["ANTHROPIC_MODEL"]
        return AnthropicProvider(
            api_key=api_key, model=model, base_url=s["CVG_CHAT_BASE_URL"] or None, key_env=key_env,
        )

    from code_vector_graph.api.providers.openai_provider import OpenAIProvider

    model = s["CVG_CHAT_MODEL"] or DEFAULT_MODELS[name]
    if name == "deepseek":
        base_url = s["CVG_CHAT_BASE_URL"] or s["DEEPSEEK_BASE_URL"]
    else:
        base_url = s["CVG_CHAT_BASE_URL"] or s["OPENAI_BASE_URL"] or None
    return OpenAIProvider(api_key=api_key, model=model, base_url=base_url, name=name, key_env=key_env)


@lru_cache(maxsize=1)
def get_provider() -> ChatProvider:
    """Process-wide provider instance (raises ValueError on an unknown CVG_CHAT_PROVIDER)."""
    return build_provider()


def reset_provider_cache() -> None:
    """Forget the cached provider (tests; after changing env at runtime)."""
    get_provider.cache_clear()


__all__ = [
    "ChatProvider", "LLMEvent", "ToolCall",
    "PROVIDERS", "DEFAULT_MODELS", "KEY_ENV",
    "build_provider", "get_provider", "reset_provider_cache", "resolve_provider_name",
]
