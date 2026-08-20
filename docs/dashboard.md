# Web Dashboard (`cvg-serve`)

A FastAPI backend plus a dependency-free static SPA for exploring the index and
asking questions about the code. It does **not** re-implement retrieval: search
and chat both go through the same MCP server an AI client would use, so what you
see in the browser is what a model sees.

```bash
cvg-serve                              # http://127.0.0.1:8000
cvg-serve --host 0.0.0.0 --port 9000   # bind elsewhere
cvg-serve --reload                     # auto-reload during development
```

Requires the `serve` extra (`pip install -e ".[serve]"`) and, for the chat tab,
`ANTHROPIC_API_KEY` in `.env`.

## Views

| View | What it does |
|---|---|
| Overview | Health of Qdrant, Neo4j and the MCP session; collection stats |
| Vectors | Browse and filter raw Qdrant points with their payloads |
| Graph | Cytoscape rendering of the Neo4j ontology; run read-only Cypher |
| Chat | Claude answers questions, calling `search_code_json` as a tool and citing file paths |

## API

All endpoints are under `/api`, and the OpenAPI docs are at `/docs`.

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Component status. `?deep=true` also loads the embedder to verify it |
| `GET /api/qdrant/collections` | List Qdrant collections |
| `GET /api/qdrant/collection` | Point count, vector size, distance metric |
| `GET /api/qdrant/points` | Paginated point browse with payload filters |
| `GET /api/graph/stats` | Node-label and relationship-type counts |
| `POST /api/graph/cypher` | Run a Cypher query — **read-only**; writes are rejected |
| `POST /api/search` | Semantic search, proxied to the MCP `search_code_json` tool |
| `POST /api/chat` | Non-streaming chat completion |
| `POST /api/chat/stream` | SSE token stream |

## How it reaches the MCP server

`api/config.py` resolves the server by preferring the installed `cvg-mcp`
console script (via `shutil.which`), then falling back to
`python -m code_vector_graph.mcp_server.server` on the running interpreter.
`CVG_MCP_PYTHON` overrides the interpreter if you need a specific one.

The session is opened once at app startup and reused (`api/mcp_client.py`),
because loading the embedding model costs seconds. If a tool call fails the
session is reset and the error surfaced — the dashboard starts in degraded mode
rather than failing outright when the MCP server is unavailable.

## Architecture

```
browser (Alpine.js + Cytoscape + Tailwind, all vendored — no CDN)
   │  fetch /api/*
   ▼
FastAPI (api/app.py) ── routers/{health,qdrant,graph,search,chat}.py
   │                        │
   │                        ├─ deps.py ─── QdrantClient, GraphStore (direct reads)
   │                        └─ mcp_client.py ── stdio ──► cvg-mcp
   │                                                        │
   └─ llm.py ── Anthropic tool-use loop ────────────────────┘
```

Static assets ship as package data under `api/static/`, so the dashboard works
from an installed wheel and not just a source checkout.
