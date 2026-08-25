"""Manages the persistent stdio MCP session with mcp_server.py."""

import asyncio
import json
import logging
import os
from contextlib import AsyncExitStack

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from code_vector_graph.api.config import MCP_ARGS, MCP_COMMAND, MCP_ENV_OVERRIDES

logger = logging.getLogger(__name__)


class MCPSessionManager:
    def __init__(self):
        self._stack: AsyncExitStack | None = None
        self.session: ClientSession | None = None
        self.lock = asyncio.Lock()
        self._tool_schemas: list[dict] = []

    async def start(self):
        params = StdioServerParameters(
            command=MCP_COMMAND,
            args=MCP_ARGS,
            # Force the child MCP server onto the same model/collection/stores the
            # dashboard resolved, so search results match what the UI browses.
            env={**os.environ, **MCP_ENV_OVERRIDES},
        )
        self._stack = AsyncExitStack()
        try:
            read, write = await self._stack.enter_async_context(stdio_client(params))
            self.session = await self._stack.enter_async_context(ClientSession(read, write))
            await self.session.initialize()
            tools_resp = await self.session.list_tools()
            self._tool_schemas = tools_resp.tools
            logger.info("MCP session started; tools: %s", [t.name for t in self._tool_schemas])
        except Exception:
            await self._stack.aclose()
            self._stack = None
            self.session = None
            raise

    async def stop(self):
        if self._stack:
            await self._stack.aclose()
            self._stack = None
            self.session = None

    async def reset(self):
        logger.warning("Resetting MCP session")
        await self.stop()
        await self.start()

    @property
    def is_alive(self) -> bool:
        return self.session is not None

    def get_tool_schemas(self) -> list[dict]:
        """Return Anthropic-compatible tool definitions."""
        schemas = []
        for t in self._tool_schemas:
            schemas.append({
                "name": t.name,
                "description": t.description or "",
                "input_schema": t.inputSchema,
            })
        return schemas

    async def call_tool(self, name: str, arguments: dict) -> str:
        """Call a tool on the MCP session (holds lock for the duration)."""
        async with self.lock:
            if not self.session:
                raise RuntimeError("MCP session is not running")
            try:
                result = await self.session.call_tool(name, arguments)
            except Exception as exc:
                logger.exception("call_tool %s failed", name)
                try:
                    await self.reset()
                except Exception:
                    pass
                raise exc
            # Concatenate all TextContent blocks
            parts = []
            for block in result.content:
                text = getattr(block, "text", None)
                if text is not None:
                    parts.append(text)
            text_out = "".join(parts)
            if result.isError:
                detail = text_out.strip() or "(no detail returned)"
                raise RuntimeError(f"MCP tool {name!r} returned an error: {detail}")
            return text_out

    async def call_tool_json(self, name: str, arguments: dict) -> dict | list:
        """Call a tool that returns JSON and parse the result."""
        raw = await self.call_tool(name, arguments)
        return json.loads(raw)


_manager: MCPSessionManager | None = None


def get_mcp_manager() -> MCPSessionManager:
    if _manager is None:
        raise RuntimeError("MCP manager not initialized")
    return _manager


async def init_mcp_manager() -> MCPSessionManager:
    global _manager
    _manager = MCPSessionManager()
    await _manager.start()
    return _manager


async def shutdown_mcp_manager():
    global _manager
    if _manager:
        await _manager.stop()
        _manager = None
