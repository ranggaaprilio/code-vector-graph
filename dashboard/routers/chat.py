"""AI chat endpoints — non-streaming and SSE streaming."""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from sse_starlette.sse import EventSourceResponse

from dashboard.deps import get_mcp
from dashboard.llm import chat_complete, chat_stream
from dashboard.mcp_client import MCPSessionManager
from dashboard.schemas import ChatRequest, ChatResponse, SourceItem
from dashboard.settings import ANTHROPIC_API_KEY

router = APIRouter()
logger = logging.getLogger(__name__)


def _check_prereqs(mcp: MCPSessionManager):
    if not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=400, detail="ANTHROPIC_API_KEY is not configured")
    if not mcp.is_alive:
        raise HTTPException(status_code=503, detail="MCP session is not running")


def _history_to_dicts(req: ChatRequest) -> list[dict]:
    return [{"role": m.role, "content": m.content} for m in req.history]


@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, mcp: MCPSessionManager = Depends(get_mcp)):
    _check_prereqs(mcp)
    result = await chat_complete(
        message=req.message,
        history=_history_to_dicts(req),
        mcp=mcp,
        options=req.options,
    )
    if result.get("error") and not result.get("answer"):
        raise HTTPException(status_code=500, detail=result["error"])
    return ChatResponse(
        answer=result["answer"],
        sources=[SourceItem(**s) for s in result["sources"]],
        error=result.get("error"),
    )


@router.post("/chat/stream")
async def chat_stream_endpoint(req: ChatRequest, mcp: MCPSessionManager = Depends(get_mcp)):
    _check_prereqs(mcp)

    async def event_generator():
        try:
            async for event in chat_stream(
                message=req.message,
                history=_history_to_dicts(req),
                mcp=mcp,
                options=req.options,
            ):
                event_type = event["type"]
                if event_type == "token":
                    yield {"event": "token", "data": json.dumps({"text": event["text"]})}
                elif event_type == "status":
                    yield {"event": "status", "data": json.dumps({"text": event["text"]})}
                elif event_type == "sources":
                    yield {"event": "sources", "data": json.dumps({"sources": event["data"]})}
                elif event_type == "done":
                    yield {"event": "done", "data": "{}"}
                elif event_type == "error":
                    yield {"event": "error", "data": json.dumps({"text": event["text"]})}
        except Exception as e:
            logger.exception("chat stream error")
            yield {"event": "error", "data": json.dumps({"text": str(e)})}

    return EventSourceResponse(event_generator())
