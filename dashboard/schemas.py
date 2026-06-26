"""Pydantic request/response models for the dashboard API."""

from typing import Any

from pydantic import BaseModel, Field


# --- Chat ---

class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = Field(default_factory=list)
    options: dict[str, Any] | None = None


class SourceItem(BaseModel):
    file_path: str
    start_line: int | None = None
    end_line: int | None = None
    function_name: str | None = None
    score: float | None = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceItem] = Field(default_factory=list)
    error: str | None = None


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


class SearchResult(BaseModel):
    id: str
    score: float
    file_path: str
    language: str
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


class SearchResponse(BaseModel):
    results: list[SearchResult]
    query: str


# --- Graph Cypher ---

class CypherRequest(BaseModel):
    cypher: str
    params: dict[str, Any] = Field(default_factory=dict)
    limit: int = 100
