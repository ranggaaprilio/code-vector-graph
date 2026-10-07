"""Fixtures for dashboard API tests.

The FastAPI app is exercised with `TestClient(app)` *without* the context manager, so
the lifespan (which spawns the MCP server subprocess) never runs. All external
stores are replaced through `app.dependency_overrides` (see api/deps.py).
"""

import json
import os
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402
from qdrant_client import QdrantClient  # noqa: E402

# api.config calls load_dotenv() at import. Resolve the core config first (so its
# module constants such as DEFAULT_MODEL_ID come from the real environment, not the
# developer's .env), then undo anything load_dotenv() added so it cannot leak into
# the rest of the suite (e.g. EMBEDDING_MODEL_ID flipping the embedder default).
import code_vector_graph.config  # noqa: E402,F401

_env_before = set(os.environ)
from code_vector_graph.api.app import app  # noqa: E402
from code_vector_graph.api.deps import (  # noqa: E402
    get_graph,
    get_mcp,
    get_qdrant,
    get_registry,
)
from code_vector_graph.api.providers.base import (  # noqa: E402
    ChatProvider,
    LLMEvent,
    ToolCall,
)
from code_vector_graph.api.services.apps import (  # noqa: E402
    ApplicationRegistry,
    AppInfo,
    AppScope,
    RepoInfo,
)

for _key in set(os.environ) - _env_before:
    del os.environ[_key]
del _env_before


class FakeNode(dict):
    """Dict-backed stand-in for a neo4j Node (props via dict, plus labels/element_id)."""

    def __init__(self, props=None, labels=(), element_id=None):
        super().__init__(props or {})
        self.labels = list(labels)
        self.element_id = element_id or f"4:fake:{self.get('id', id(self))}"


class FakeRel:
    def __init__(self, start, end, rel_type, element_id=None):
        self.start_node = start
        self.end_node = end
        self.type = rel_type
        self.element_id = element_id or f"5:fake:{id(self)}"


class FakeGraph:
    """Records every query_graph() call; answers from a per-test script of record lists."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []
        self.script: list[list] = []
        self.healthy = True

    def queue(self, records: list):
        self.script.append(records)
        return self

    def query_graph(self, cypher, params=None):
        self.calls.append((cypher, dict(params or {})))
        records = self.script.pop(0) if self.script else []
        return SimpleNamespace(records=records)

    def check_health(self):
        return self.healthy

    @property
    def last_cypher(self) -> str:
        return self.calls[-1][0] if self.calls else ""


class FakeMCP:
    """Stand-in for MCPSessionManager: scripted tool replies, no subprocess."""

    def __init__(self):
        self.is_alive = True
        self.calls: list[tuple[str, dict]] = []
        self.replies: dict[str, str] = {}

    def reply(self, tool: str, payload) -> "FakeMCP":
        self.replies[tool] = payload if isinstance(payload, str) else json.dumps(payload)
        return self

    def get_tool_schemas(self):
        return []

    async def call_tool(self, name: str, arguments: dict) -> str:
        self.calls.append((name, dict(arguments)))
        return self.replies.get(name, "")

    async def call_tool_json(self, name: str, arguments: dict):
        return json.loads(await self.call_tool(name, arguments))


@pytest.fixture
def fake_graph() -> FakeGraph:
    return FakeGraph()


@pytest.fixture
def fake_mcp() -> FakeMCP:
    return FakeMCP()


@pytest.fixture
def fake_qdrant() -> QdrantClient:
    return QdrantClient(":memory:")


REPOS_ROOT = "/Users/x/Repository"
ONEBID_ROOTS = {
    "backend_nodejs_global_tnlm": f"{REPOS_ROOT}/onebid/backend/backend_nodejs_global_tnlm",
    "backend_nodejs_data_sync_onebid": f"{REPOS_ROOT}/onebid/backend/backend_nodejs_data_sync_onebid",
}


def make_repo(name, app="onebid", source="derived", **kw) -> RepoInfo:
    return RepoInfo(
        name=name,
        root=kw.pop("root", None) or ONEBID_ROOTS.get(name, f"{REPOS_ROOT}/{name}"),
        app=app,
        source=source,
        **kw,
    )


def make_scope(app="onebid", repos=None) -> AppScope:
    return AppScope(app=app, repos=list(repos or [make_repo(n) for n in ONEBID_ROOTS]))


class StubRegistry:
    """Registry with a fixed app list — no store access at all."""

    def __init__(self, apps=None):
        self.apps = list(apps if apps is not None else [AppInfo.aggregate("onebid", [make_repo(n) for n in ONEBID_ROOTS])])
        self.files_by_key: dict[tuple, list] = {}
        self.cached_at = "2026-08-25T00:00:00Z"

    def list(self, refresh: bool = False):
        return list(self.apps)

    def get(self, app: str) -> AppInfo:
        for a in self.apps:
            if a.name == app:
                return a
        raise KeyError(f"Unknown application '{app}'")

    def scope(self, app: str, repo: str | None = None) -> AppScope:
        info = self.get(app)
        scope = AppScope(app=info.name, repos=list(info.repos))
        return scope.for_repo(repo) if repo else scope

    def files(self, app: str, repo: str | None = None, refresh: bool = False):
        self.scope(app, repo)
        return self.files_by_key.get((app, repo or ""), [])


@pytest.fixture
def stub_registry() -> StubRegistry:
    return StubRegistry()


@pytest.fixture
def real_registry(fake_graph, fake_qdrant) -> ApplicationRegistry:
    """The real discovery logic, driven by the fake graph/qdrant (for registry tests)."""
    return ApplicationRegistry(
        graph=fake_graph,
        qdrant=fake_qdrant,
        collection="test_collection",
        ttl=0,
        repos_root=REPOS_ROOT,
    )


class FakeProvider(ChatProvider):
    """Scripted ChatProvider: `rounds` is one list of LLMEvent per model turn.

    Records every stream_turn() call in `.turns` so tests can inspect the system
    prompt and the message history the loop built.
    """

    name = "fake"
    model = "fake-model-1"

    def __init__(self, rounds=None, configured=(True, "")):
        self.rounds = [list(r) for r in (rounds or [])]
        self.configured = configured
        self.turns: list[tuple[str, list[dict], list[dict]]] = []
        self.converted_tools: list[dict] | None = None

    # -- scripting helpers --------------------------------------------------
    @staticmethod
    def text(s: str) -> LLMEvent:
        return LLMEvent(type="text", text=s)

    @staticmethod
    def call(name: str, arguments: dict, call_id: str = "call_1") -> LLMEvent:
        return LLMEvent(
            type="tool_call", tool_call=ToolCall(id=call_id, name=name, arguments=dict(arguments))
        )

    @staticmethod
    def stop(reason: str = "stop") -> LLMEvent:
        return LLMEvent(type="stop", stop_reason=reason)

    # -- ChatProvider -------------------------------------------------------
    def is_configured(self):
        return self.configured

    def init_messages(self, system, history, user):
        msgs = [{"role": "system", "content": system}]
        msgs.extend({"role": m["role"], "content": m["content"]} for m in history)
        msgs.append({"role": "user", "content": user})
        return msgs

    def convert_tools(self, mcp_tools):
        self.converted_tools = [{"fake_tool": t["name"]} for t in mcp_tools]
        return self.converted_tools

    async def stream_turn(self, system, messages, tools):
        self.turns.append((system, [dict(m) for m in messages], list(tools)))
        events = self.rounds.pop(0) if self.rounds else [self.stop()]
        for ev in events:
            yield ev

    def assistant_turn(self, text, calls, raw):
        return [{"role": "assistant", "content": text, "tool_calls": [c.name for c in calls]}]

    def tool_results(self, results):
        return [{"role": "tool", "tool_call_id": c.id, "content": out} for c, out in results]


@pytest.fixture
def fake_provider() -> FakeProvider:
    """One-round provider that just answers (no tool calls)."""
    return FakeProvider([[FakeProvider.text("Hi from the fake model."), FakeProvider.stop()]])


@pytest.fixture
def client(fake_graph, fake_mcp, fake_qdrant, stub_registry):
    app.dependency_overrides[get_graph] = lambda: fake_graph
    app.dependency_overrides[get_mcp] = lambda: fake_mcp
    app.dependency_overrides[get_qdrant] = lambda: fake_qdrant
    app.dependency_overrides[get_registry] = lambda: stub_registry
    try:
        # No `with`: lifespan (MCP spawn) must not run.
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
