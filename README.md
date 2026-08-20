# Code Vector Graph

Turns JavaScript/TypeScript repositories into a searchable knowledge graph that
combines **vector embeddings** (Qdrant) with a **code ontology** (Neo4j).
Tree-sitter does language-aware parsing, embeddings run locally via HuggingFace,
and an **MCP server** exposes the result to any AI client.

📚 **[Full documentation →](docs/README.md)**

## Features

- **Multi-Model Support**: `nomic` (default, 3584-dim, no task prefixes) or `jina` (1536-dim, task-specific prefixes for code search) via `--model`
- **Language-Aware Parsing**: Tree-sitter parses JS/TS/TSX, strips comments, and extracts rich AST metadata (functions, classes, imports, call sites, decorators, visibility)
- **Smart Chunking**: Token-aware sliding window with line-boundary respect and long-line splitting at token boundaries
- **Local Embeddings**: `nomic-ai/nomic-embed-code` or `jinaai/jina-code-embeddings-1.5b`, with automatic dtype selection (float16/bfloat16/float32)
- **Code Ontology Graph**: Neo4j stores Files, Classes, Functions, Methods, Fields, Variables, Imports, Interfaces, TypeAliases, Chunks and glossary entries, plus their relationships (CALLS, IMPORTS, CONTAINS, HAS_GLOSSARY, …)
- **Glossary Enrichment**: `glossary.yml` entries and nearby comments/JSDoc become `GlossaryEntry` nodes in Neo4j and searchable records in Qdrant
- **Hybrid Retrieval**: Vector similarity fused with graph traversal via Reciprocal Rank Fusion (RRF)
- **MCP Server**: `search_code`, `search_code_json` and `check_health` for any MCP-compatible client
- **Web Dashboard**: Browse vectors, explore the graph, and chat with your codebase — routed through the same MCP tools a model uses
- **OKF LLM Wiki**: Generate a cross-linked, human-readable wiki (Karpathy "LLM wiki" / DeepWiki style) in Google Cloud's **Open Knowledge Format** using **DeepSeek**, then sync it back into Qdrant and Neo4j
- **Deterministic IDs**: Content hashing makes upserts idempotent — re-running won't duplicate
- **Dry-Run Mode**: Preview what would be processed without generating embeddings

## Supported File Types

- JavaScript: `.js`, `.jsx`, `.mjs`, `.cjs`
- TypeScript: `.ts`, `.mts`, `.cts`
- TSX: `.tsx` (parsed with the TypeScriptReact grammar)

## Prerequisites

Python 3.10+, Docker & Docker Compose, and a HuggingFace token.
An OpenAI key (RAG answers), Anthropic key (dashboard chat) and DeepSeek key
(OKF wiki) are optional, per feature.

## Quick Start

```bash
# 1. Install
python -m venv .venv && source .venv/bin/activate
pip install -e ".[ingest,serve,query,mcp,dev]"

# 2. Configure — see .env.example for every supported variable
cp .env.example .env    # then add your HF_TOKEN

# 3. Start Qdrant + Neo4j
docker-compose up -d

# 4. Download the embedding model
cvg-download-model --model nomic

# 5. Index a repository
cvg-ingest --repo-path /path/to/js-or-ts-repo --verbose

# 6. Ask it questions
cvg-query --question "How does authentication work?" --retrieval hybrid

# 7. Or open the dashboard / serve over MCP
cvg-serve            # http://127.0.0.1:8000
cvg-mcp              # stdio MCP server
```

Full walkthrough in [docs/setup.md](docs/setup.md).

## Commands

| Command | Role | Docs |
|---|---|---|
| `cvg-ingest` | Index a repo into Qdrant + Neo4j | [Ingestion](docs/ingestion.md) |
| `cvg-query` | Ask questions from the terminal | [Query CLI](docs/query-cli.md) |
| `cvg-serve` | Web dashboard | [Dashboard](docs/dashboard.md) |
| `cvg-mcp` | MCP server for AI clients | [MCP Server](docs/mcp-server.md) |
| `cvg-download-model` | Pre-fetch embedding weights | [Setup](docs/setup.md) |
| `cvg-okf-build` / `cvg-okf-sync` | Build and sync the LLM wiki | [OKF Wiki](docs/okf-wiki.md) |
| `cvg-reinit-graph` | Rebuild Neo4j from Qdrant payloads | [Ingestion](docs/ingestion.md) |

## Embedding Models

| Model ID | Full Name | Dimensions | Dtype | Task Prefixes | Default |
|----------|-----------|------------|-------|---------------|---------|
| `nomic` | `nomic-ai/nomic-embed-code` | 3584 | float16 (CUDA) / bfloat16 (MPS) / float32 (ROCm, CPU) | None | Yes |
| `jina` | `jinaai/jina-code-embeddings-1.5b` | 1536 | bfloat16 (CUDA, MPS) / float32 (ROCm, CPU) | `code2code` + `nl2code` | No |

> Each model gets its own Qdrant collection (the model name and dimension count
> are appended). **Switching models means re-indexing.** Details in
> [docs/models.md](docs/models.md).

## Project Layout

Organised by role — see [docs/project-structure.md](docs/project-structure.md)
for the annotated tree.

```
src/code_vector_graph/
├── parsing/      source → AST, chunks, graph entities
├── embeddings/   model download + local inference
├── stores/       Qdrant + Neo4j persistence
├── retrieval/    hybrid vector/graph search
├── ingestion/    the indexing pipeline, plus the OKF wiki layer
├── mcp_server/   MCP tools
├── api/          FastAPI dashboard + static SPA
└── cli/          console-script entry points
```

## License

MIT — see [LICENSE](LICENSE).

---

Built with Tree-sitter, HuggingFace Transformers, Qdrant, Neo4j, and MCP.
