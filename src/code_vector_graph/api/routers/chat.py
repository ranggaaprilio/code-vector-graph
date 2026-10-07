"""AI chat endpoints — provider config, non-streaming answer, and SSE streaming.

SSE contract (unchanged event names; `data` is always a JSON object):
    event: token    data: {"text": "..."}
    event: status   data: {"text": "..."}
    event: sources  data: {"sources": [SourceItem, ...]}
    event: done     data: {"provider": "...", "model": "..."}
    event: error    data: {"text": "..."}

`ChatRequest.options` may carry `{"app", "repo", "mode", "top_k", "source"}`: `app`
(+ optional `repo`) scopes retrieval to an indexed application; the rest are
forwarded to the search tools when the model leaves them unset.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from code_vector_graph.api.deps import get_mcp, get_registry
from code_vector_graph.api.llm import chat_complete, chat_stream
from code_vector_graph.api.mcp_client import MCPSessionManager
from code_vector_graph.api.providers import ChatProvider, get_provider
from code_vector_graph.api.schemas import ChatRequest, ChatResponse, SourceItem
from code_vector_graph.api.services.apps import ApplicationRegistry

router = APIRouter()
logger = logging.getLogger(__name__)


def _load_provider() -> ChatProvider:
    try:
        return get_provider()
    except ValueError as exc:  # unsupported CVG_CHAT_PROVIDER
        raise HTTPException(status_code=400, detail=str(exc))


def _check_prereqs(mcp: MCPSessionManager) -> ChatProvider:
    provider = _load_provider()
    ok, reason = provider.is_configured()
    if not ok:
        raise HTTPException(status_code=400, detail=reason)
    if not mcp.is_alive:
        raise HTTPException(status_code=503, detail="MCP session is not running")
    return provider


def _resolve_scope(options: dict | None, registry: ApplicationRegistry) -> Any | None:
    """Turn `options.app` / `options.repo` into an AppScope (404 when unknown)."""
    opts = options or {}
    app = (opts.get("app") or "").strip() if isinstance(opts.get("app"), str) else opts.get("app")
    repo = opts.get("repo") or None
    if not app:
        return None
    try:
        return registry.scope(app, repo)
    except KeyError as exc:
        what = f"application {app!r}" if not repo else f"repository {repo!r} in application {app!r}"
        raise HTTPException(status_code=404, detail=f"Unknown {what}: {exc}")


def _history_to_dicts(req: ChatRequest) -> list[dict]:
    return [{"role": m.role, "content": m.content} for m in req.history]


@router.get("/chat/config")
def chat_config():
    """Which LLM provider/model the chat uses and whether it is ready."""
    try:
        provider = get_provider()
    except ValueError as exc:
        return {"provider": None, "model": None, "configured": False, "reason": str(exc)}
    ok, reason = provider.is_configured()
    return {
        "provider": provider.name,
        "model": provider.model,
        "configured": ok,
        "reason": None if ok else reason,
    }


@router.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    mcp: MCPSessionManager = Depends(get_mcp),
    registry: ApplicationRegistry = Depends(get_registry),
):
    provider = _check_prereqs(mcp)
    scope = _resolve_scope(req.options, registry)
    result = await chat_complete(
        message=req.message,
        history=_history_to_dicts(req),
        mcp=mcp,
        options=req.options,
        scope=scope,
        provider=provider,
    )
    if result.get("error") and not result.get("answer"):
        raise HTTPException(status_code=500, detail=result["error"])
    return ChatResponse(
        answer=result["answer"],
        sources=[SourceItem(**s) for s in result["sources"]],
        error=result.get("error"),
        provider=result.get("provider") or provider.name,
        model=result.get("model") or provider.model,
    )


@router.post("/chat/stream")
async def chat_stream_endpoint(
    req: ChatRequest,
    mcp: MCPSessionManager = Depends(get_mcp),
    registry: ApplicationRegistry = Depends(get_registry),
):
    provider = _check_prereqs(mcp)
    scope = _resolve_scope(req.options, registry)

    async def event_generator():
        try:
            async for event in chat_stream(
                message=req.message,
                history=_history_to_dicts(req),
                mcp=mcp,
                options=req.options,
                scope=scope,
                provider=provider,
            ):
                event_type = event["type"]
                if event_type == "token":
                    yield {"event": "token", "data": json.dumps({"text": event["text"]})}
                elif event_type == "status":
                    yield {"event": "status", "data": json.dumps({"text": event["text"]})}
                elif event_type == "sources":
                    yield {"event": "sources", "data": json.dumps({"sources": event["data"]})}
                elif event_type == "done":
                    yield {
                        "event": "done",
                        "data": json.dumps({
                            "provider": event.get("provider"),
                            "model": event.get("model"),
                        }),
                    }
                elif event_type == "error":
                    yield {"event": "error", "data": json.dumps({"text": event["text"]})}
        except Exception as e:
            logger.exception("chat stream error")
            yield {"event": "error", "data": json.dumps({"text": str(e)})}

    return EventSourceResponse(event_generator())
