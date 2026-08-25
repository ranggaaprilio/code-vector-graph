"""Provider-agnostic chat/tool-use primitives for the dashboard chat.

`ChatProvider` hides the wire differences between the Anthropic Messages API and
OpenAI-compatible chat completions (OpenAI, DeepSeek). `api/llm.py` drives the
tool-use loop purely in terms of these primitives:

    messages = provider.init_messages(system, history, user)
    tools    = provider.convert_tools(mcp.get_tool_schemas())
    async for ev in provider.stream_turn(system, messages, tools): ...
    messages += provider.assistant_turn(text, calls, raw)
    messages += provider.tool_results([(call, result), ...])
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class ToolCall:
    """A tool invocation requested by the model."""

    id: str
    name: str
    arguments: dict = field(default_factory=dict)


@dataclass
class LLMEvent:
    """One event from `ChatProvider.stream_turn`.

    - "text":      `text` is a real streamed delta (not a re-chunked final answer).
    - "tool_call": `tool_call` is a fully assembled request (arguments parsed).
    - "stop":      the turn is complete; `stop_reason` is the provider's native reason
                   and `raw` the provider's final message object (if any).
    """

    type: Literal["text", "tool_call", "stop"]
    text: str = ""
    tool_call: ToolCall | None = None
    stop_reason: str | None = None
    raw: Any = None


class ChatProvider(ABC):
    """Interface implemented by `anthropic_provider` and `openai_provider`."""

    #: "anthropic" | "openai" | "deepseek"
    name: str
    #: Model identifier sent to the API.
    model: str

    @abstractmethod
    def is_configured(self) -> tuple[bool, str]:
        """Return (ok, reason). `reason` names the missing env var when not ok."""

    @abstractmethod
    def init_messages(self, system: str, history: list[dict], user: str) -> list[dict]:
        """Build the initial message list from `[{"role","content"}]` history + user turn."""

    @abstractmethod
    def convert_tools(self, mcp_tools: list[dict]) -> list[dict]:
        """Convert `{name, description, input_schema}` (MCPSessionManager.get_tool_schemas())
        into the provider's native tool definition shape."""

    @abstractmethod
    def stream_turn(
        self, system: str, messages: list[dict], tools: list[dict]
    ) -> AsyncIterator[LLMEvent]:
        """Run one model turn, yielding `LLMEvent`s; must end with a "stop" event."""

    @abstractmethod
    def assistant_turn(self, text: str, calls: list[ToolCall], raw: Any) -> list[dict]:
        """Messages to append representing the assistant turn just streamed."""

    @abstractmethod
    def tool_results(self, results: list[tuple[ToolCall, str]]) -> list[dict]:
        """Messages to append carrying tool outputs back to the model."""
