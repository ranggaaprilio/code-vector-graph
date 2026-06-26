"""Anthropic Claude tool-use loop over the MCP session."""

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

import anthropic

from dashboard.mcp_client import MCPSessionManager
from dashboard.settings import ANTHROPIC_API_KEY, ANTHROPIC_MODEL

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a code assistant for an indexed repository. "
    "Use the `search_code_json` tool to retrieve relevant code before answering. "
    "After searching, cite the file paths and line numbers in your answer. "
    "If the tools return nothing relevant, say so — do not invent answers."
)

MAX_TOOL_ROUNDS = 5


def _make_client() -> anthropic.AsyncAnthropic:
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY is not set")
    return anthropic.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)


def _parse_sources(tool_results: list[dict]) -> list[dict]:
    """Extract structured source citations from search_code_json results."""
    sources = []
    seen = set()
    for tr in tool_results:
        if tr.get("tool") != "search_code_json":
            continue
        try:
            data = json.loads(tr.get("raw", "{}"))
            for r in data.get("results", []):
                key = (r.get("file_path"), r.get("start_line"))
                if key not in seen:
                    seen.add(key)
                    sources.append({
                        "file_path": r.get("file_path", ""),
                        "start_line": r.get("start_line"),
                        "end_line": r.get("end_line"),
                        "function_name": r.get("function_name"),
                        "score": r.get("score"),
                    })
        except (json.JSONDecodeError, TypeError):
            pass
    return sources


async def chat_stream(
    message: str,
    history: list[dict],
    mcp: MCPSessionManager,
    options: dict | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """
    Drive a multi-turn Claude tool-use loop and yield SSE-friendly event dicts:
      {"type": "status", "text": "..."}
      {"type": "token",  "text": "..."}
      {"type": "sources", "data": [...]}
      {"type": "done"}
      {"type": "error", "text": "..."}
    """
    client = _make_client()
    tools = mcp.get_tool_schemas()
    opts = options or {}

    messages: list[dict] = list(history)
    messages.append({"role": "user", "content": message})

    tool_results_log: list[dict] = []

    for round_num in range(MAX_TOOL_ROUNDS):
        try:
            resp = await client.messages.create(
                model=ANTHROPIC_MODEL,
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=tools,
                max_tokens=4096,
            )
        except Exception as exc:
            yield {"type": "error", "text": f"LLM error: {exc}"}
            return

        # Collect assistant content
        assistant_content = resp.content

        # Check stop reason
        if resp.stop_reason == "end_turn":
            # Final text answer — stream it token-by-token (simulate; resp is not streaming here)
            for block in assistant_content:
                if block.type == "text":
                    yield {"type": "token", "text": block.text}
            break

        if resp.stop_reason != "tool_use":
            # Unexpected; emit whatever text we have
            for block in assistant_content:
                if block.type == "text":
                    yield {"type": "token", "text": block.text}
            break

        # Process tool calls
        tool_result_blocks = []
        for block in assistant_content:
            if block.type != "tool_use":
                continue
            tool_name = block.name
            tool_input = block.input

            yield {"type": "status", "text": f"Searching code: {tool_name}({json.dumps(tool_input)[:120]})"}

            try:
                raw_result = await mcp.call_tool(tool_name, tool_input)
            except Exception as exc:
                raw_result = json.dumps({"error": str(exc), "results": []})
                yield {"type": "status", "text": f"Tool error: {exc}"}

            tool_results_log.append({"tool": tool_name, "raw": raw_result})
            tool_result_blocks.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": raw_result,
            })

        # Append assistant turn + tool results
        messages.append({"role": "assistant", "content": assistant_content})
        messages.append({"role": "user", "content": tool_result_blocks})

    else:
        yield {"type": "error", "text": "Reached maximum tool-use rounds without a final answer."}
        return

    sources = _parse_sources(tool_results_log)
    yield {"type": "sources", "data": sources}
    yield {"type": "done"}


async def chat_complete(
    message: str,
    history: list[dict],
    mcp: MCPSessionManager,
    options: dict | None = None,
) -> dict:
    """Non-streaming version — collect all events and return a single response dict."""
    tokens = []
    sources = []
    error = None

    async for event in chat_stream(message, history, mcp, options):
        t = event["type"]
        if t == "token":
            tokens.append(event["text"])
        elif t == "sources":
            sources = event["data"]
        elif t == "error":
            error = event["text"]

    return {
        "answer": "".join(tokens),
        "sources": sources,
        "error": error,
    }
