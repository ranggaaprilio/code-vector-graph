"""Provider-agnostic LLM tool-use loop over the MCP session.

The loop streams real token deltas from the configured `ChatProvider` (Anthropic,
OpenAI or DeepSeek — see `api/providers`), executes the model's tool calls against
the MCP session, and yields SSE-friendly event dicts:

    {"type": "token",   "text": "..."}
    {"type": "status",  "text": "..."}
    {"type": "sources", "data": [...]}
    {"type": "done",    "provider": "...", "model": "..."}
    {"type": "error",   "text": "..."}

When an application/repository scope is active the system prompt names the app and
its repos, and `apply_tool_defaults` injects `repos`/`repo_roots` (plus the user's
`mode`/`top_k`/`source` options) into search tool calls the model left unscoped.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from code_vector_graph.api.mcp_client import MCPSessionManager
from code_vector_graph.api.providers import ChatProvider, ToolCall, get_provider

logger = logging.getLogger(__name__)

BASE_SYSTEM_PROMPT = (
    "You are a code assistant for repositories indexed in a vector + graph store. "
    "Always call the `search_code_json` tool to retrieve relevant code before answering; "
    "run more than one search when the first is inconclusive. "
    "Results carry `source` = \"code\" (a code chunk) or \"wiki\" (an LLM-written explanation "
    "page); code results may include `wiki_context` with a related explanation. "
    "Cite every claim as `file_path:start_line-end_line`. "
    "If the tools return nothing relevant, say so — do not invent answers."
)

# Kept for backwards compatibility with callers/tests importing the old name.
SYSTEM_PROMPT = BASE_SYSTEM_PROMPT

MAX_TOOL_ROUNDS = 100

# Tools whose arguments accept the repo scope / retrieval options.
SEARCH_TOOLS = frozenset({"search_code", "search_code_json"})
# Chat options forwarded to the search tools when the model did not set them.
FORWARDED_OPTIONS = ("mode", "top_k", "source")


def build_system_prompt(scope: Any | None = None) -> str:
    """Base prompt, plus an application/repository scope block when one is active."""
    if scope is None:
        return BASE_SYSTEM_PROMPT

    repos = list(getattr(scope, "repos", None) or [])
    names = list(getattr(scope, "repo_names", None) or [r.name for r in repos])
    lines = [BASE_SYSTEM_PROMPT, ""]
    if len(names) == 1:
        lines.append(
            f"You are answering about repository `{names[0]}` of application `{scope.app}`:"
        )
    else:
        lines.append(
            f"You are answering about application `{scope.app}`, which consists of "
            f"{len(names)} repositories:"
        )
    for r in repos:
        src = getattr(r, "source", "")
        suffix = " (identity derived from file paths)" if src == "derived" else ""
        lines.append(f"- `{r.name}` at `{r.root}`{suffix}")
    if not repos:
        for n in names:
            lines.append(f"- `{n}`")
    repos_json = json.dumps(names)
    lines.append("")
    lines.append(
        f"Always pass `repos={repos_json}` to `search_code_json` so results stay within this scope"
    )
    if not getattr(scope, "all_recorded", True):
        roots_json = json.dumps(list(getattr(scope, "repo_roots", None) or []))
        lines[-1] += f", and also `repo_roots={roots_json}` (some repos are only identified by path)"
    lines[-1] += ". When several repositories are in scope, say which repository each finding belongs to."
    return "\n".join(lines)


def apply_tool_defaults(
    args: dict | None,
    scope: Any | None = None,
    options: dict | None = None,
    tool_name: str | None = None,
) -> dict:
    """Fill in scope + user options the model omitted from a search tool call.

    Only keys absent from `args` are added — the model's explicit choices win.
    Non-search tools (`tool_name` not in SEARCH_TOOLS) are returned untouched.
    """
    out = dict(args or {})
    if tool_name is not None and tool_name not in SEARCH_TOOLS:
        return out
    if scope is not None:
        names = list(getattr(scope, "repo_names", None) or [])
        if names and "repos" not in out:
            out["repos"] = names
        if not getattr(scope, "all_recorded", True) and "repo_roots" not in out:
            roots = list(getattr(scope, "repo_roots", None) or [])
            if roots:
                out["repo_roots"] = roots
    for key in FORWARDED_OPTIONS:
        val = (options or {}).get(key)
        if val is not None and val != "" and key not in out:
            out[key] = val
    return out


def _parse_sources(tool_results: list[dict]) -> list[dict]:
    """Extract deduplicated source citations from search_code_json results."""
    sources: list[dict] = []
    seen: set[tuple] = set()
    for tr in tool_results:
        if tr.get("tool") != "search_code_json":
            continue
        try:
            data = json.loads(tr.get("raw") or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        for r in data.get("results", []) or []:
            if not isinstance(r, dict):
                continue
            source = "wiki" if r.get("source") == "wiki" else "code"
            title = r.get("term") or r.get("title")
            if not title and source == "wiki":
                title = r.get("function_name") or r.get("class_name")
            key = (source, r.get("file_path"), r.get("start_line"), title if source == "wiki" else None)
            if key in seen:
                continue
            seen.add(key)
            item = {
                "file_path": r.get("file_path", "") or "",
                "start_line": r.get("start_line"),
                "end_line": r.get("end_line"),
                "function_name": r.get("function_name"),
                "score": r.get("score"),
                "source": source,
                "title": title,
                "summary": r.get("summary"),
                "repo": r.get("repo"),
            }
            if r.get("wiki_context"):
                item["wiki_context"] = r["wiki_context"]
            sources.append(item)
    return sources


def _describe_call(call: ToolCall) -> str:
    return f"Searching code: {call.name}({json.dumps(call.arguments)[:120]})"


async def chat_stream(
    message: str,
    history: list[dict],
    mcp: MCPSessionManager,
    options: dict | None = None,
    scope: Any | None = None,
    provider: ChatProvider | None = None,
) -> AsyncGenerator[dict[str, Any], None]:
    """Drive the multi-round tool-use loop and yield event dicts (see module docstring)."""
    try:
        provider = provider or get_provider()
    except ValueError as exc:
        yield {"type": "error", "text": str(exc)}
        return
    ok, reason = provider.is_configured()
    if not ok:
        yield {"type": "error", "text": reason}
        return

    opts = options or {}
    system = build_system_prompt(scope)
    tools = provider.convert_tools(mcp.get_tool_schemas())
    messages = provider.init_messages(system, history, message)
    tool_log: list[dict] = []

    for _round in range(MAX_TOOL_ROUNDS):
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        raw: Any = None
        try:
            async for ev in provider.stream_turn(system, messages, tools):
                if ev.type == "text":
                    if ev.text:
                        text_parts.append(ev.text)
                        yield {"type": "token", "text": ev.text}
                elif ev.type == "tool_call" and ev.tool_call is not None:
                    calls.append(ev.tool_call)
                elif ev.type == "stop":
                    raw = ev.raw
        except Exception as exc:  # network / auth / model errors
            logger.exception("LLM stream failed (%s/%s)", provider.name, provider.model)
            yield {"type": "error", "text": f"LLM error: {exc}"}
            return

        if not calls:
            break  # final answer streamed above

        results: list[tuple[ToolCall, str]] = []
        for call in calls:
            call.arguments = apply_tool_defaults(call.arguments, scope, opts, tool_name=call.name)
            yield {"type": "status", "text": _describe_call(call)}
            try:
                output = await mcp.call_tool(call.name, call.arguments)
            except Exception as exc:
                logger.warning("tool %s failed: %s", call.name, exc)
                output = json.dumps({"error": str(exc), "results": []})
                yield {"type": "status", "text": f"Tool error: {exc}"}
            tool_log.append({"tool": call.name, "raw": output})
            results.append((call, output))

        messages.extend(provider.assistant_turn("".join(text_parts), calls, raw))
        messages.extend(provider.tool_results(results))
    else:
        # Exhausted every round still requesting tools — force one final,
        # tool-less turn so the model must synthesize from what it already
        # gathered instead of leaving the user with nothing.
        yield {"type": "status", "text": "Reached the search limit — summarizing what was found so far."}
        try:
            async for ev in provider.stream_turn(system, messages, []):
                if ev.type == "text" and ev.text:
                    yield {"type": "token", "text": ev.text}
        except Exception as exc:
            logger.exception("Final synthesis failed (%s/%s)", provider.name, provider.model)
            yield {"type": "error", "text": f"LLM error: {exc}"}
            return

    yield {"type": "sources", "data": _parse_sources(tool_log)}
    yield {"type": "done", "provider": provider.name, "model": provider.model}


async def chat_complete(
    message: str,
    history: list[dict],
    mcp: MCPSessionManager,
    options: dict | None = None,
    scope: Any | None = None,
    provider: ChatProvider | None = None,
) -> dict:
    """Non-streaming variant: collect every event into one response dict."""
    tokens: list[str] = []
    sources: list[dict] = []
    error: str | None = None
    prov_name: str | None = None
    model: str | None = None

    async for event in chat_stream(message, history, mcp, options, scope=scope, provider=provider):
        t = event["type"]
        if t == "token":
            tokens.append(event["text"])
        elif t == "sources":
            sources = event["data"]
        elif t == "error":
            error = event["text"]
        elif t == "done":
            prov_name = event.get("provider")
            model = event.get("model")

    return {
        "answer": "".join(tokens),
        "sources": sources,
        "error": error,
        "provider": prov_name,
        "model": model,
    }
