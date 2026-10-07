"""OpenAI-compatible chat completions provider (OpenAI, DeepSeek, …).

DeepSeek exposes an OpenAI-compatible endpoint, so one implementation covers both;
`name` distinguishes them for `/api/chat/config`. Streaming specifics handled here:

- `delta.content` fragments are forwarded as "text" events.
- `delta.tool_calls` arrive fragmented: the first delta for an `index` carries `id`
  and `function.name`; subsequent deltas append to `function.arguments`. They are
  accumulated per index and parsed as JSON when the turn finishes.
- `delta.reasoning_content` (DeepSeek thinking models) is ignored.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from code_vector_graph.api.providers.base import ChatProvider, LLMEvent, ToolCall

logger = logging.getLogger(__name__)


class OpenAIProvider(ChatProvider):
    def __init__(self, api_key: str, model: str, base_url: str | None = None,
                 name: str = "openai", key_env: str = "OPENAI_API_KEY", client: Any = None):
        self.name = name
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
            from openai import AsyncOpenAI  # lazy: only needed when chat is actually used

            kwargs: dict[str, Any] = {"api_key": self.api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = AsyncOpenAI(**kwargs)
        return self._client

    # -- message shaping -----------------------------------------------------

    def init_messages(self, system: str, history: list[dict], user: str) -> list[dict]:
        messages: list[dict] = [{"role": "system", "content": system}]
        messages.extend({"role": m["role"], "content": m["content"]} for m in history)
        messages.append({"role": "user", "content": user})
        return messages

    def convert_tools(self, mcp_tools: list[dict]) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description") or "",
                    "parameters": t.get("input_schema") or {"type": "object", "properties": {}},
                },
            }
            for t in mcp_tools
        ]

    # -- streaming -----------------------------------------------------------

    async def stream_turn(
        self, system: str, messages: list[dict], tools: list[dict]
    ) -> AsyncIterator[LLMEvent]:
        # `system` is already the first message (see init_messages).
        client = self._get_client()
        kwargs: dict[str, Any] = {"model": self.model, "messages": messages, "stream": True}
        if tools:
            kwargs["tools"] = tools

        pending: dict[int, dict[str, Any]] = {}  # index -> {id, name, arguments}
        finish_reason: str | None = None

        stream = await client.chat.completions.create(**kwargs)
        async for chunk in stream:
            choices = getattr(chunk, "choices", None) or []
            if not choices:
                continue  # e.g. trailing usage-only chunk
            choice = choices[0]
            delta = getattr(choice, "delta", None)
            if delta is not None:
                content = getattr(delta, "content", None)
                if content:
                    yield LLMEvent(type="text", text=content)
                for tc in getattr(delta, "tool_calls", None) or []:
                    idx = getattr(tc, "index", None)
                    idx = len(pending) if idx is None else idx
                    slot = pending.setdefault(idx, {"id": None, "name": "", "arguments": ""})
                    if getattr(tc, "id", None):
                        slot["id"] = tc.id
                    fn = getattr(tc, "function", None)
                    if fn is not None:
                        if getattr(fn, "name", None):
                            slot["name"] = fn.name
                        if getattr(fn, "arguments", None):
                            slot["arguments"] += fn.arguments
            if getattr(choice, "finish_reason", None):
                finish_reason = choice.finish_reason

        for idx in sorted(pending):
            slot = pending[idx]
            yield LLMEvent(
                type="tool_call",
                tool_call=ToolCall(
                    id=slot["id"] or f"call_{idx}",
                    name=slot["name"],
                    arguments=self._parse_arguments(slot["arguments"], slot["name"]),
                ),
            )
        if finish_reason is None:
            finish_reason = "tool_calls" if pending else "stop"
        yield LLMEvent(type="stop", stop_reason=finish_reason, raw=None)

    @staticmethod
    def _parse_arguments(raw: str, tool_name: str) -> dict:
        raw = (raw or "").strip()
        if not raw:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Tool call %s: could not parse arguments %r; using {}", tool_name, raw[:200])
            return {}
        if not isinstance(parsed, dict):
            logger.warning("Tool call %s: arguments are not an object (%r); using {}", tool_name, raw[:200])
            return {}
        return parsed

    # -- history -------------------------------------------------------------

    def assistant_turn(self, text: str, calls: list[ToolCall], raw: Any) -> list[dict]:
        msg: dict[str, Any] = {"role": "assistant", "content": text or None}
        if calls:
            msg["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": json.dumps(c.arguments)},
                }
                for c in calls
            ]
        return [msg]

    def tool_results(self, results: list[tuple[ToolCall, str]]) -> list[dict]:
        return [
            {"role": "tool", "tool_call_id": call.id, "content": output}
            for call, output in results
        ]
