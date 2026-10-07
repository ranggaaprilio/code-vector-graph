# Web Dashboard (`cvg-serve`)

A FastAPI backend plus a dependency-free static SPA for exploring the index and
asking questions about the code. It does **not** re-implement retrieval: search
and chat both go through the same MCP server an AI client would use, so what you
see in the browser is what a model sees.

```bash
cvg-serve                              # http://127.0.0.1:8001
cvg-serve --host 0.0.0.0 --port 9000   # bind elsewhere
cvg-serve --reload                     # auto-reload during development
```

Requires the `serve` extra (`pip install -e ".[serve]"`) and, for the chat tab, a
configured LLM provider (see [Chat providers](#chat-providers)).

## Applications, not just "the index"

The dashboard is organised around **applications**. An application is a product;
it may span several repositories. `onebid`, for example, is one application made
of `backend_nodejs_global_tnlm` and `backend_nodejs_data_sync_onebid`.

A scope selector in the sidebar picks the active application and, optionally, one
of its repositories. Vectors, Graph and Chat all honour that scope, and the scope
lives in the URL (`#/vectors?app=onebid&repo=…`) so any view is shareable.

How applications are discovered, in order:

1. **Recorded** — `Application`/`Repository` nodes and the `repo`/`app` payload
   fields written by `cvg-ingest` (see [graph schema](graph-schema.md)).
2. **Derived** — for data indexed before that existed, repository roots are
   inferred from `File.path` prefixes and grouped into applications using
   `CVG_REPOS_ROOT` (or an explicit `CVG_APP_MAP`). Such rows are badged
   *derived* in the UI.

```bash
# .env — makes /Users/you/Repository/onebid/backend/{a,b} one "onebid" application
CVG_REPOS_ROOT=/Users/you/Repository
# or be explicit:
CVG_APP_MAP={"onebid": ["backend_nodejs_global_tnlm", "backend_nodejs_data_sync_onebid"]}
```

To turn derived identity into recorded identity without re-embedding anything,
run `cvg-backfill-repo` (see [ingestion](ingestion.md)).

## Views

| View | What it does |
|---|---|
| Applications | Cards per application: repos, file/chunk counts, language mix |
| Application page | Overview (architecture prose or fallback stats), Files (tree → file → symbols, chunks, wiki), Docs (Feature pages + manually-authored Documents — create, edit, reindex, delete, all with a live indexing-progress panel), Wiki (OKF pages) |
| Vectors | Semantic search and raw payload browse, scoped, with code/wiki badges |
| Graph | Svelte Flow (@xyflow/svelte) rendering of the Neo4j ontology with ELK layered layout; read-only Cypher |
| Chat | An LLM answers questions, calling `search_code_json` scoped to the active application |
| Editor | Standalone Markdown editor (toolbar, split preview, drag-drop/Open/Download a `.md` file, browser-local autosave draft) with a "Save to Docs…" panel that creates an indexed Document for any application |
| System | Health of Qdrant, Neo4j and the MCP session; collection and graph stats |

The Overview tab shows the OKF architecture overview when one exists. If it does
not, it shows statistics plus the command that generates it:

```bash
cvg-okf-build --repo-path <root> --app-name <app> && cvg-okf-sync
```

## API

All endpoints are under `/api`, and the OpenAPI docs are at `/docs`.

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Component status + active collection/model/chat provider. `?deep=true` also loads the embedder |
| `GET /api/apps` | Applications with their repositories, counts and languages |
| `POST /api/apps/refresh` | Re-run discovery, bypassing the cache |
| `GET /api/apps/{app}` | Summary: counts, languages, per-repo overview and top modules, top wiki pages |
| `GET /api/apps/{app}/tree` | Repository list (no `repo`) or one directory level (`?repo=&path=`) |
| `GET /api/apps/{app}/files/{repo}/{path}` | One file: symbols, code chunks, wiki pages, glossary |
| `GET /api/apps/{app}/wiki` | OKF pages in scope (`?repo=&type=&q=&limit=&offset=`) |
| `GET /api/apps/{app}/wiki/{concept_id}` | One page with what it documents and its cross-references |
| `GET /api/apps/{app}/docs` | Feature/Document pages in scope (`?repo=&q=&stale=&source=&kind=&type=Feature\|Document\|all&limit=&offset=`) |
| `POST /api/apps/{app}/docs` | Create a manually-authored Document (`{title?, markdown, repo?, tags?, category?, source_file?}`) — `202`, returns a `job_id` (see [Manual documents](okf-wiki.md#manual-documents)) |
| `GET /api/apps/{app}/docs/{id}` | One page: content, `members` (Feature) or `mentions` (Document), and its latest indexing `job` if any |
| `PUT /api/apps/{app}/docs/{id}` | Edit a page's Markdown; a Document edit re-indexes asynchronously and also returns a `job_id` |
| `POST /api/apps/{app}/docs/{id}/reindex` | Re-embed a page's vectors and (for a Document) re-link its `MENTIONS` edges — `202` |
| `DELETE /api/apps/{app}/docs/{id}` | Delete a Document (Feature pages are managed by "Generate docs" and can't be deleted here) |
| `GET /api/apps/{app}/docs/jobs[/{job_id}]` | Background job status: `kind` (`generate`\|`index_document`), `stage`, `stages`, `progress`, `message`, `result` |
| `GET /api/qdrant/collections` | List Qdrant collections |
| `GET /api/qdrant/collection` | Point count, vector size, distance metric |
| `GET /api/qdrant/points` | Paginated point browse (`?app=&repo=&source=&file_prefix=&language=`) |
| `GET /api/graph/stats` | Node-label and relationship-type counts (`?app=&repo=`) |
| `GET /api/graph/nodes` | Nodes of one label (`?label=&app=&repo=`) |
| `GET /api/graph/subgraph` | Neighbourhood of a node (`?node_id=&depth=1..3`) |
| `POST /api/graph/edges` | Relationships among the given node ids (`{ids: [...]}`, max 200) — the graph view calls this after Load nodes / Visualize so relations between visible nodes are drawn without fetching new nodes |
| `POST /api/graph/cypher` | Run a Cypher query — **read-only**; writes are rejected |
| `POST /api/search` | Semantic search via the MCP `search_code_json` tool (`app`/`repo` scope, wiki results included) |
| `GET /api/chat/config` | Active chat provider/model and whether it is configured |
| `POST /api/chat` | Non-streaming chat completion |
| `POST /api/chat/stream` | SSE token stream (`status`, `token`, `sources`, `done`, `error`) |

Scoping is enforced twice: as a Qdrant `repo` filter when the repositories are
recorded, and as a path-prefix post-filter for derived (legacy) data — which is
why a scoped search over legacy data over-fetches and then trims.

## Chat providers

Chat works with Anthropic or any OpenAI-compatible endpoint (OpenAI, DeepSeek):

```bash
# .env — pick one; auto-detected from the available key when unset
CVG_CHAT_PROVIDER=deepseek        # anthropic | openai | deepseek
# CVG_CHAT_MODEL=deepseek-v4-flash
# CVG_CHAT_BASE_URL=https://api.deepseek.com
# CVG_CHAT_API_KEY=...            # else ANTHROPIC_API_KEY / OPENAI_API_KEY / DEEPSEEK_API_KEY
```

`GET /api/chat/config` reports what was resolved; when nothing is configured the
composer is disabled and the endpoint returns 400 naming the missing variable.

The system prompt tells the model which application and repositories it is
answering about, and the scope is injected into every `search_code_json` call the
model makes, so answers stay inside the selected application.

## How it reaches the MCP server

`api/config.py` resolves the server by preferring the installed `cvg-mcp` console
script (via `shutil.which`), then falling back to
`python -m code_vector_graph.mcp_server.server` on the running interpreter.
`CVG_MCP_PYTHON` overrides the interpreter if you need a specific one. The
subprocess inherits the dashboard's collection/model/store settings, so the two
processes can never disagree about which index they are reading.

The session is opened once at app startup and reused (`api/mcp_client.py`),
because loading the embedding model costs seconds. If a tool call fails the
session is reset and the error surfaced — the dashboard starts in degraded mode
rather than failing outright when the MCP server is unavailable.

## Architecture

```
browser — SvelteKit SPA (frontend/), @xyflow/svelte + elkjs + highlight.js as npm deps
   │  fetch /api/*
   ▼
FastAPI (api/app.py) ── routers/{apps,health,qdrant,graph,search,chat}.py
   │                        │
   │                        ├─ services/apps.py ── ApplicationRegistry (recorded ∪ derived)
   │                        ├─ deps.py ─── QdrantClient, GraphStore (direct reads)
   │                        └─ mcp_client.py ── stdio ──► cvg-mcp
   │                                                        │
   └─ llm.py ── provider tool-use loop ─────────────────────┘
        └─ providers/{anthropic,openai}.py
```

### Frontend

The UI lives in `frontend/` as a SvelteKit SPA (Svelte 5 runes, TypeScript,
`@sveltejs/adapter-static` with `fallback: 'index.html'`). `npm run build` writes
straight into `src/code_vector_graph/api/static/`, which ships as package data,
so the dashboard works from an installed wheel and not just a source checkout.
`api/app.py` serves that directory through a single catch-all route registered
after the `/api/*` routers, so client-side deep links survive a hard refresh.
The `static/` directory is gitignored: run `npm run build` after cloning and
before building a wheel, otherwise `cvg-serve` has no UI to serve.

```
cd frontend
npm install
npm run dev     # Vite on :5173, /api proxied to 127.0.0.1:8001 (run cvg-serve too)
npm run build   # -> ../src/code_vector_graph/api/static/
npm run check   # svelte-check (strict)
npm run test    # vitest — the frontend unit suite
```

Styling is hand-written CSS driven by design tokens in
`frontend/src/lib/styles/tokens.css`, which implement the `Design.md` visual
system (closed palette, zero radius, hard borders, single light theme). The three
deliberate deviations from that document — interaction states, a modernised body
type scale, and display tracking — are documented in the token file itself.
Literal colour values live only in `tokens.css` and `frontend/src/lib/utils/tints.ts`;
everything else references tokens.
