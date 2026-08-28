"""Pydantic request/response models for the dashboard API."""

from typing import Any

from pydantic import BaseModel, Field, model_validator
from pydantic.fields import FieldInfo


def _keeps_none(field: FieldInfo | None) -> bool:
    """True when ``None`` is the field's own default (an unknown key is passed through
    so validation still reports it) — anything else has a real default to fall back on."""
    if field is None:
        return True
    return field.default is None and field.default_factory is None


class _MCPItem(BaseModel):
    """Base for models built straight from an MCP tool's JSON items.

    The wiki layer sends an explicit ``null`` where the code layer sends a list
    or a string (``imports``, ``file_path``, …). A field default only applies to
    a *missing* key, so those nulls would fail validation against the declared
    ``list[str]`` / ``str``. Drop them and let the defaults fill in.
    """

    @model_validator(mode="before")
    @classmethod
    def _drop_nulls(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        fields = cls.model_fields
        return {k: v for k, v in data.items() if v is not None or _keeps_none(fields.get(k))}


# --- Chat ---

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = Field(default_factory=list)
    # Optional knobs: {"app": str, "repo": str, "mode": "hybrid"|"vector"|"graph",
    # "top_k": int, "source": "all"|"code"|"wiki"}. `app`/`repo` scope retrieval to an
    # indexed application (404 when unknown); the rest are forwarded to the search
    # tools when the model leaves them unset.
    options: dict[str, Any] | None = None


class SourceItem(_MCPItem):
    file_path: str = ""
    start_line: int | None = None
    end_line: int | None = None
    function_name: str | None = None
    score: float | None = None
    source: str = "code"          # "code" | "wiki"
    title: str | None = None
    summary: str | None = None
    repo: str | None = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceItem] = Field(default_factory=list)
    error: str | None = None
    # LLM provider ("anthropic" | "openai" | "deepseek") and model that answered.
    provider: str | None = None
    model: str | None = None


# --- Search ---

class SearchRequest(BaseModel):
    query: str
    mode: str = "hybrid"
    top_k: int = 10
    language: str | None = None
    file_pattern: str | None = None
    min_score: float = 0.0
    vector_weight: float = 0.7
    graph_weight: float = 0.3
    source: str = "all"           # "all" | "code" | "wiki"
    include_wiki: bool = True
    # Application / repository scope. Resolved to MCP `repos`/`repo_roots` in Phase 1.
    app: str | None = None
    repo: str | None = None


class SearchResult(_MCPItem):
    id: str
    score: float
    # Graph-mode hits (and wiki pages) may carry no file_path/language.
    file_path: str = ""
    language: str = ""
    start_line: int | None = None
    end_line: int | None = None
    function_name: str | None = None
    class_name: str | None = None
    node_type: str | None = None
    text_content: str = ""
    imports: list[str] = Field(default_factory=list)
    exports: list[str] = Field(default_factory=list)
    symbols_defined: list[str] = Field(default_factory=list)
    call_sites: list[str] = Field(default_factory=list)
    token_count: int | None = None
    # Layer + OKF wiki enrichment (see mcp_server.search_code_json).
    source: str = "code"          # "code" | "wiki"
    summary: str | None = None
    term: str | None = None
    wiki_context: dict[str, Any] | None = None
    # Application / repository identity (populated once Phase 1/4 land).
    app: str | None = None
    repo: str | None = None
    rel_path: str | None = None
    concept_id: str | None = None


class SearchResponse(BaseModel):
    results: list[SearchResult]
    query: str


# --- Graph Cypher ---

class CypherRequest(BaseModel):
    cypher: str
    params: dict[str, Any] = Field(default_factory=dict)
    limit: int = 100


class EdgesRequest(BaseModel):
    """Body for POST /graph/edges: complete the relationships among visible nodes."""

    ids: list[str] = Field(..., max_length=200, description="Node `id` properties currently on the canvas")
    limit: int = Field(default=500, ge=1, le=2000)
