# Project Structure

The package is organised by **role**: what ingests, what faces the user, what
downloads models, and what acts as the MCP server.

```
code-vector-graph/
├── pyproject.toml              # deps (role-scoped extras) + 8 console scripts
├── docker-compose.yml          # Qdrant + Neo4j
├── .env.example                # every supported environment variable
├── .mcp.json                   # MCP server registration for AI clients
├── docs/                       # all documentation (you are here)
├── examples/sample-repo/       # tiny JS/TS repo used by the docs' examples
├── scripts/run_mac_mps_24gb.sh # tuned end-to-end run for a 24 GB Apple Silicon Mac
├── tests/                      # mirrors the package layout; see docs/testing.md
└── src/code_vector_graph/
    ├── config.py               # models, chunking, store + DeepSeek/OKF settings
    ├── logging_setup.py        # shared logging configuration
    │
    ├── parsing/                # ── source code → structured data
    │   ├── scanner.py          #    file discovery + SHA256 hashing
    │   ├── parser.py           #    Tree-sitter parse, comment stripping, AST metadata
    │   ├── chunker.py          #    token-aware sliding-window chunking
    │   ├── graph_extractor.py  #    AST → graph nodes and relationships
    │   └── glossary.py         #    manual + comment glossary extraction
    │
    ├── embeddings/             # ── MODEL DOWNLOAD + vector generation
    │   ├── embedder.py         #    HuggingFace inference (Nomic + Jina prefixes)
    │   └── download.py         #    pre-fetch weights (`cvg-download-model`)
    │
    ├── stores/                 # ── persistence
    │   ├── vector_store.py     #    Qdrant, deterministic UUID5 ids
    │   ├── graph_store.py      #    Neo4j CRUD with batching
    │   └── graph_schema.py     #    node/relationship schema + validation
    │
    ├── retrieval/              # ── read path
    │   └── hybrid.py           #    vector + graph fusion (RRF)
    │
    ├── ingestion/              # ── INGESTION (write path)
    │   ├── pipeline.py         #    the indexing pipeline
    │   ├── reinit_graph.py     #    rebuild Neo4j from Qdrant payloads
    │   └── okf/                #    OKF LLM-wiki layer
    │       ├── skeleton.py     #      concept graph from Tree-sitter
    │       ├── enricher.py     #      DeepSeek enrichment (bottom-up, JSON mode)
    │       ├── render.py       #      write the OKF bundle (Markdown + YAML)
    │       ├── cache.py        #      incremental enrichment cache
    │       └── sync.py         #      bundle → Qdrant + Neo4j
    │
    ├── mcp_server/             # ── MCP
    │   └── server.py           #    search_code, search_code_json, check_health
    │
    ├── api/                    # ── FRONT-FACING (web)
    │   ├── app.py              #    FastAPI app + lifespan-managed MCP session
    │   ├── config.py           #    dashboard settings, MCP launch resolution
    │   ├── deps.py             #    DI providers (Qdrant, Neo4j, MCP)
    │   ├── mcp_client.py       #    persistent stdio MCP session
    │   ├── llm.py              #    Anthropic tool-use loop
    │   ├── schemas.py          #    Pydantic request/response models
    │   ├── routers/            #    health, qdrant, graph, search, chat
    │   └── static/             #    the SPA (vendored deps, no CDN)
    │
    └── cli/                    # ── FRONT-FACING (terminal)
        ├── ingest.py           #    cvg-ingest
        ├── query.py            #    cvg-query
        ├── serve.py            #    cvg-serve
        ├── download_model.py   #    cvg-download-model
        ├── okf_build.py        #    cvg-okf-build
        ├── okf_sync.py         #    cvg-okf-sync
        └── reinit_graph.py     #    cvg-reinit-graph
```

## Console scripts

`pip install -e .` puts these on your `PATH`; each maps to a module under `cli/`.

| Command | Role | Module |
|---|---|---|
| `cvg-ingest` | Ingestion | `cli.ingest` |
| `cvg-query` | Front-facing (CLI) | `cli.query` |
| `cvg-serve` | Front-facing (web) | `cli.serve` |
| `cvg-mcp` | MCP | `mcp_server.server` |
| `cvg-download-model` | Model download | `cli.download_model` |
| `cvg-okf-build` | Ingestion (wiki phase 1) | `cli.okf_build` |
| `cvg-okf-sync` | Ingestion (wiki phase 2) | `cli.okf_sync` |
| `cvg-reinit-graph` | Ingestion (recovery) | `cli.reinit_graph` |

## Dependency extras

Base install covers parsing and store access. The heavy or role-specific pieces
are opt-in, so serving the dashboard does not require the multi-GB PyTorch
wheels:

| Extra | Pulls in | Needed for |
|---|---|---|
| `ingest` | torch, transformers | generating embeddings (indexing *or* querying) |
| `serve` | fastapi, uvicorn, sse-starlette, anthropic | `cvg-serve` |
| `query` | openai | RAG answers in `cvg-query`, OKF enrichment |
| `mcp` | mcp[cli] | `cvg-mcp` |
| `dev` | pytest, pytest-cov | running the test suite |
