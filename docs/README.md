# Documentation

Start with [Setup](setup.md), then pick the page for what you're doing.

## Getting started

| Page | What's in it |
|---|---|
| [Setup](setup.md) | Prerequisites, install, `.env`, starting Qdrant + Neo4j, quick start |
| [Embedding Models](models.md) | Nomic vs Jina, dimensions, dtype/device selection |
| [Architecture](architecture.md) | How the pieces fit; pipeline flow; chunking and RRF details |
| [Project Structure](project-structure.md) | Directory layout by role, console scripts, dependency extras |

## Using it

| Page | What's in it |
|---|---|
| [Ingestion](ingestion.md) | `cvg-ingest` — indexing a repo, all CLI options, glossary enrichment |
| [Query CLI](query-cli.md) | `cvg-query` — retrieval modes, filters, RAG answers |
| [Web Dashboard](dashboard.md) | `cvg-serve` — views, REST API, how it talks to MCP |
| [MCP Server](mcp-server.md) | `cvg-mcp` — tools, client registration |
| [OKF LLM Wiki](okf-wiki.md) | Generate a cross-linked wiki with DeepSeek and sync it back |

## Reference

| Page | What's in it |
|---|---|
| [Code Ontology](graph-schema.md) | Neo4j node labels and relationship types |
| [Testing](testing.md) | Running the suite, layout, the one known failing test |
| [Troubleshooting](troubleshooting.md) | Model access, dimension mismatch, connection and memory errors |

## Archive

- [Implementation Guide](archive/implementation-guide.md) — the original
  phase-by-phase build guide. **Historical**: the work it describes has shipped,
  and its file paths and line numbers predate the package restructure. Kept for
  the design rationale, not as instructions.
