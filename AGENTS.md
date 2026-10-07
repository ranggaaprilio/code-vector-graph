# AGENTS.md — code-vector-graph

Orientation for agents working in this repo. Human documentation lives in
[docs/](docs/README.md); this file covers only what an agent needs to work here
correctly.

## What this is

A Python tool that indexes JS/TS repositories into Qdrant (vector embeddings)
and Neo4j (a code ontology), then serves retrieval over MCP, a CLI, and a web
dashboard. Tree-sitter does the parsing; embedding models run locally.

## Structure

Organised by **role**, one package per concern. Full annotated tree in
[docs/project-structure.md](docs/project-structure.md).

```
src/code_vector_graph/
├── config.py          settings (models, chunking, stores, DeepSeek/OKF)
├── logging_setup.py   setup_logging()
├── parsing/           scanner, parser, chunker, graph_extractor, glossary
├── embeddings/        embedder, download
├── stores/            vector_store (Qdrant), graph_store (Neo4j), graph_schema
├── retrieval/         hybrid (RRF fusion)
├── ingestion/         pipeline, reinit_graph, okf/
├── mcp_server/        server (MCP tools)
├── api/               FastAPI dashboard + static SPA
└── cli/               console-script entry points
```

## Where to look

| Task | Start here |
|---|---|
| Change how files are found/skipped | `parsing/scanner.py` |
| Change AST metadata or comment stripping | `parsing/parser.py` |
| Change chunk boundaries or token counting | `parsing/chunker.py` |
| Change what lands in Neo4j | `parsing/graph_extractor.py`, `stores/graph_schema.py` |
| Change Qdrant payloads or ids | `stores/vector_store.py` |
| Change search ranking | `retrieval/hybrid.py` |
| Add/modify an MCP tool | `mcp_server/server.py` |
| Add a dashboard endpoint | `api/routers/`, `api/schemas.py` |
| Add a CLI flag | `cli/<command>.py` |
| Add a setting | `config.py` (+ document it in `.env.example`) |

## Conventions

**Dependencies:** `pyproject.toml`. Role-scoped extras (`ingest`, `serve`,
`query`, `mcp`, `dev`) — put a dependency in the extra that actually needs it
rather than the base set. `requirements.txt` is a compatibility shim pointing at
`-e .[...]`; don't add packages there.

**Install:** `pip install -e ".[ingest,serve,query,mcp,dev]"`.

**Imports:** absolute, from the package root —
`from code_vector_graph.parsing.parser import parse_file`. No relative imports,
no `sys.path` manipulation, and never import by bare module name.

**Entry points:** every user-facing command is a console script declared in
`pyproject.toml` and implemented under `cli/`. Don't add runnable scripts at the
repo root. Entry modules must call `load_dotenv()` **before** importing
`config`, which reads the environment at import time.

**Logging:** `logger = logging.getLogger(__name__)`; configure via
`logging_setup.setup_logging(verbose)`.

**CLI pattern:**
```python
args = parse_args()
setup_logging(args.verbose)
run_pipeline(args)
```

**Error handling:** health checks fail fast with `sys.exit(1)` and an actionable
message; argument validation goes through `parser.error()` in `parse_args()`.

**Tests:** mirror the package layout. Resolve paths via `tests/conftest.py`
(`FIXTURES_DIR`, `PROJECT_ROOT`) — never a cwd-relative literal. Anything that
downloads a real model or needs live services belongs in `tests/manual/`, which
is excluded from the default run.

## Anti-patterns

| Pattern | Why |
|---|---|
| Module-level mutable global state | Breaks under batching and parallel processing |
| Bare `except Exception` around control flow | Masks real errors; catch specific exceptions |
| Chunks over the model's token limit | Silently truncated — data loss; `embeddings/embedder.py` warns |
| Secrets in source | Everything goes through `os.getenv` + `.env.example` |
| Re-implementing retrieval per surface | The dashboard routes through the MCP tools on purpose; keep one read path |
| cwd-relative paths in library code | Breaks the installed package; resolve from `__file__` or config |

## Commands

```bash
# Setup
python -m venv .venv && source .venv/bin/activate
pip install -e ".[ingest,serve,query,mcp,dev]"
docker-compose up -d

# Run
cvg-ingest --repo-path /path/to/repo --verbose
cvg-ingest --repo-path /path/to/repo --dry-run     # no embeddings, no writes
cvg-query --question "..." --retrieval hybrid
cvg-serve
cvg-mcp

# Test
pytest
pytest --cov=code_vector_graph --cov-report=term-missing
```

## Notes

- **Switching embedding models requires re-indexing** — the Qdrant collection
  name embeds the model name and dimension count, so `nomic` and `jina` data
  never mix.
- **Neo4j is the source of truth for the graph.** Qdrant payloads deliberately
  carry flat chunk metadata rather than a copy of the graph; `cvg-reinit-graph`
  reconstructs the graph from those payloads.
- **Tree-sitter is error-tolerant**: `parse_file()` returns a tree containing
  ERROR nodes for invalid syntax rather than failing. See the known-failing test
  noted in [docs/testing.md](docs/testing.md).
- Dashboard static assets ship as package data, so the SPA works from an
  installed wheel — reference them relative to `__file__`, not the repo root.
