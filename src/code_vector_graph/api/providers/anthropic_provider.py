"""Anthropic Messages API provider (real token streaming + tool use)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from code_vector_graph.api.providers.base import ChatProvider, LLMEvent, ToolCall

logger = logging.getLogger(__name__)

MAX_TOKENS = 4096


class AnthropicProvider(ChatProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str, base_url: str | None = None,
                 key_env: str = "ANTHROPIC_API_KEY", client: Any = None):
        self.api_key = api_key or ""
        self.model = model
        self.base_url = base_url or None
        self.key_env = key_env
        self._client = client

    # -- configuration -------------------------------------------------------

    def is_configured(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, f"{self.key_env} is not set"
        return True, ""

    def _get_client(self):
        if self._client is None:
            import anthropic  # lazy: only needed when chat is actually used

            kwargs: dict[str, Any] = {"api_key": self.api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = anthropic.AsyncAnthropic(**kwargs)
        return self._client

    # -- message shaping -----------------------------------------------------

    def init_messages(self, system: str, history: list[dict], user: str) -> list[dict]:
        # System prompt is a top-level parameter for Anthropic, not a message.
        messages = [{"role": m["role"], "content": m["content"]} for m in history]
        messages.append({"role": "user", "content": user})
        return messages

    def convert_tools(self, mcp_tools: list[dict]) -> list[dict]:
        return [
            {
                "name": t["name"],
                "description": t.get("description") or "",
                "input_schema": t.get("input_schema") or {"type": "object", "properties": {}},
            }
            for t in mcp_tools
        ]

    # -- streaming -----------------------------------------------------------

    async def stream_turn(
        self, system: str, messages: list[dict], tools: list[dict]
    ) -> AsyncIterator[LLMEvent]:
        client = self._get_client()
        kwargs: dict[str, Any] = {
            "model": self.model,
            "system": system,
            "messages": messages,
            "max_tokens": MAX_TOKENS,
        }
        if tools:  # the API rejects an empty tools list
            kwargs["tools"] = tools

        async with client.messages.stream(**kwargs) as stream:
            async for event in stream:
                if getattr(event, "type", None) != "content_block_delta":
                    continue
                delta = getattr(event, "delta", None)
                if getattr(delta, "type", None) == "text_delta" and delta.text:
                    yield LLMEvent(type="text", text=delta.text)
            final = await stream.get_final_message()

        for block in getattr(final, "content", []) or []:
            if getattr(block, "type", None) == "tool_use":
                yield LLMEvent(
                    type="tool_call",
                    tool_call=ToolCall(id=block.id, name=block.name, arguments=dict(block.input or {})),
                )
        yield LLMEvent(type="stop", stop_reason=getattr(final, "stop_reason", None), raw=final)

    # -- history -------------------------------------------------------------

    def assistant_turn(self, text: str, calls: list[ToolCall], raw: Any) -> list[dict]:
        content = getattr(raw, "content", None)
        if content:
            # Keep the SDK's own content blocks (text + tool_use) verbatim.
            return [{"role": "assistant", "content": content}]
        blocks: list[dict] = []
        if text:
            blocks.append({"type": "text", "text": text})
        for c in calls:
            blocks.append({"type": "tool_use", "id": c.id, "name": c.name, "input": c.arguments})
        return [{"role": "assistant", "content": blocks}] if blocks else []

    def tool_results(self, results: list[tuple[ToolCall, str]]) -> list[dict]:
        if not results:
            return []
        return [{
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": call.id, "content": output}
                for call, output in results
            ],
        }]
