# Code Vector Graph

A Python CLI tool that transforms JavaScript/TypeScript code repositories into a searchable knowledge graph combining **vector embeddings** (Qdrant) with **code ontologies** (Neo4j). Uses Tree-sitter for language-aware parsing, supports multiple embedding models (Nomic and Jina) via HuggingFace, and exposes an **MCP server** for AI-assisted code search.

## Features

- **Multi-Model Support**: Choose between `nomic` (default, 3584-dim, no task prefixes) and `jina` (1536-dim, task-specific prefixes for code search) via the `--model` flag
- **Language-Aware Parsing**: Tree-sitter parses JS/TS/TSX files, strips comments, and extracts rich AST metadata (functions, classes, imports, call sites, decorators, visibility)
- **Smart Chunking**: Token-aware sliding window chunking with line-boundary respect and long-line splitting at token boundaries
- **Local Embeddings**: Run HuggingFace models locally — `nomic-ai/nomic-embed-code` (default) or `jinaai/jina-code-embeddings-1.5b`, with automatic dtype selection (float16/bfloat16/float32)
- **Code Ontology Graph**: Neo4j stores a rich schema of Files, Classes, Functions, Methods, Fields, Variables, Imports, Interfaces, TypeAliases, Chunks, glossary entries, and their relationships (CALLS, IMPORTS, HAS_GLOSSARY, CONTAINS, etc.)
- **Glossary Enrichment**: Manual `glossary.yml` entries and nearby comments/JSDoc become structured `GlossaryEntry` nodes in Neo4j and searchable glossary records in Qdrant
- **Hybrid Retrieval**: Combines vector similarity and graph traversal using Reciprocal Rank Fusion (RRF) for superior search quality
- **MCP Server**: Expose `search_code` and `check_health` tools to any MCP-compatible AI client (Claude Desktop, OpenCode, etc.)
- **Query CLI**: Standalone query tool with code-specific query expansion and OpenAI-powered RAG answers
- **Deterministic IDs**: Content hashing for idempotent upserts — re-running won't create duplicates
- **Dry-Run Mode**: Preview what would be processed without generating embeddings

## Supported File Types

- JavaScript: `.js`, `.jsx`, `.mjs`, `.cjs`
- TypeScript: `.ts`, `.mts`, `.cts`
- TSX: `.tsx` (parsed with TypeScriptReact grammar)

## Embedding Models

| Model ID | Full Name | Dimensions | Dtype | Task Prefixes | Default |
|----------|-----------|------------|-------|---------------|---------|
| `nomic` | `nomic-ai/nomic-embed-code` | 3584 | float16 (float32 on MPS/ROCm) | None | Yes |
| `jina` | `jinaai/jina-code-embeddings-1.5b` | 1536 | bfloat16 (float32 on MPS/ROCm) | `code2code` + `nl2code` | No |

- **Nomic** (default): Higher-dimensional (3584), no task prefixes needed, uses `float16` precision. Good general-purpose code embedding.
- **Jina**: Lower-dimensional (1536), prepends task-specific prefixes (`code2code` for code passages, `nl2code` for queries) to improve retrieval accuracy. Uses `bfloat16` precision.

Switch models with `--model`:
```bash
python main.py --repo-path /path/to/repo --model nomic   # default
python main.py --repo-path /path/to/repo --model jina
```

> **Important**: Each model creates a separate Qdrant collection (e.g., `code_chunks_nomic-embed-code_3584` vs `code_chunks_jina-code-embeddings-1.5b_1536`). If you switch models, you must re-index your repository.

## Prerequisites

- Python 3.10+
- Docker & Docker Compose
- HuggingFace token (for model access)
- OpenAI API key (for RAG answers via `query.py` — optional)

## Step-by-Step Setup

### 1. Clone the repository

```bash
git clone <repository-url>
cd code-vector-graph
```

### 2. Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate       # Linux/macOS
# .venv\Scripts\activate        # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

This installs PyTorch, Transformers, Tree-sitter, Qdrant client, and all other required packages.

### 4. Create a `.env` file

```bash
cat > .env << 'EOF'
HF_TOKEN=hf_your_huggingface_token_here
OPENAI_API_KEY=sk-your_openai_key_here
EOF
```

- **HF_TOKEN**: HuggingFace token with access to the embedding models. Get one at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens). Both models require `trust_remote_code=True`, so ensure your token has read access.
- **OPENAI_API_KEY**: OpenAI API key for RAG answers via `query.py` (only needed for querying, not indexing).

### 5. Start infrastructure services

```bash
docker-compose up -d
```

This starts:
- **Qdrant** (Vector Database): REST API at `http://localhost:6333`, gRPC at `http://localhost:6334`
- **Neo4j** (Graph Database): Browser at `http://localhost:7474`, Bolt at `bolt://localhost:7687`

Verify they're running:
```bash
curl http://localhost:6333/healthz        # Qdrant health check
docker-compose ps neo4j                   # Neo4j status
```

### 6. Download the embedding model

You must download the model you plan to use before running the pipeline. The script supports both models:

```bash
# Download the default Nomic model (~2GB):
python download_model.py

# Or download the Jina model (~3GB):
python download_model.py --model jina
```

Models are cached in `~/.cache/huggingface/` for subsequent runs.

### 7. Index a repository

```bash
# With default Nomic model:
python main.py --repo-path /path/to/your/repo --verbose

# With Jina model:
python main.py --repo-path /path/to/your/repo --model jina --verbose

# Dry run first (no embeddings, no storage):
python main.py --repo-path /path/to/your/repo --dry-run --verbose
```

### 8. Query your indexed code

```bash
# Vector search (requires OPENAI_API_KEY for RAG answers):
python query.py --question "How does authentication work?"

# Hybrid search (vector + graph):
python query.py --question "Where is the database connection established?" --retrieval hybrid
```

### 9. (Optional) Start the MCP server

```bash
python mcp_server.py
```

See the [MCP Server](#mcp-server) section for client configuration.

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Scanner   │────▶│   Parser    │────▶│   Chunker   │
│  (discover  │     │(Tree-sitter │     │(model-aware │
│   JS/TS)    │     │ + metadata) │     │+ sliding)   │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                                │
                       ┌─────────────┐          │
                       │    Store    │◀─────────┤
                       │  (Qdrant)   │    ┌─────┴──────┐
                       └─────────────┘    │  Embedder   │
                                          │(Nomic/Jina) │
                       ┌─────────────┐    └─────────────┘
                       │  GraphStore │◀─── Graph Extractor
                       │   (Neo4j)   │    (AST ontology)
                       └─────────────┘
                              │
                     ┌────────┴────────┐
                     │ Hybrid Retriever│
                     │  (RRF fusion)   │
                     └────────┬────────┘
                              │
                    ┌─────────┴─────────┐
                    │    MCP Server     │
                    │  (search_code,    │
                    │   check_health)   │
                    └───────────────────┘
```

### Pipeline Flow

1. **Scan**: Discover all JS/TS files (excludes `node_modules`, `.git`, etc.)
2. **Parse**: Parse each file with Tree-sitter, strip comments, extract AST metadata
3. **Chunk**: Create overlapping, token-aware chunks (400 tokens, 64 overlap, line-based, never mid-line)
4. **Embed**: Generate embeddings using the selected model (Nomic: 3584-dim, no prefixes; Jina: 1536-dim with task prefixes)
5. **Store**: Upsert chunks into Qdrant with full metadata
6. **Graph Extract**: Extract code ontology entities (Files, Classes, Functions, Methods, Fields, Variables, Imports, Interfaces, TypeAliases) and relationships (CALLS, IMPORTS, INHERITS, CONTAINS, REFERENCES, etc.)
7. **Glossary Enrich**: Attach manual glossary entries and nearby comments/JSDoc to matching symbols with `HAS_GLOSSARY`
8. **Graph Store**: Upsert nodes and relationships into Neo4j

## CLI Reference

### Indexing (`main.py`)

```bash
python main.py --repo-path /path/to/repo [OPTIONS]
```

### Dry Run (Preview Mode)

See what would be processed without generating embeddings:

```bash
python main.py --repo-path /path/to/your/repo --dry-run
```

### Skip Graph Ingestion

```bash
python main.py --repo-path /path/to/your/repo --no-graph
```

### Verbose Output

```bash
python main.py --repo-path /path/to/your/repo --verbose
```

### Glossary Enrichment

By default, the pipeline looks for `glossary.yml` in the repository root. Missing glossary files are ignored.

```bash
python main.py --repo-path /path/to/your/repo --glossary-file glossary.yml
```

Example `glossary.yml`:

```yaml
entries:
  - term: userId
    kind: variable
    file_path: src/auth/session.ts
    summary: Unique identifier for the authenticated user.
    source: manual

  - term: SessionManager
    kind: class
    file_path: src/auth/session.ts
    summary: Coordinates session lifecycle and token refresh behavior.
```

Supported `kind` values match graph symbols: `class`, `function`, `method`, `field`, `variable`, `interface`, and `type_alias`.

Manual entries take precedence over comments/JSDoc for the same `file_path + kind + term`. Comments immediately above a symbol are also extracted automatically:

```ts
/** Unique identifier for the authenticated user. */
const userId = session.user.id;
```

Glossary entries are stored as `GlossaryEntry` nodes in Neo4j, linked to symbols with `HAS_GLOSSARY`, and also indexed in Qdrant as `node_type="glossary_entry"` records for semantic search.

### Custom Configuration

```bash
python main.py \
  --repo-path /path/to/repo \
  --qdrant-url http://localhost:6333 \
  --collection-name my_code_chunks \
  --chunk-size 400 \
  --chunk-overlap 64 \
  --batch-size 64 \
  --neo4j-uri bolt://localhost:7687 \
  --verbose
```

### CLI Options
| Option | Default | Description |
|--------|---------|-------------|
| `--repo-path` | *required* | Path to the repository to process |
| `--model` | `nomic` | Embedding model: `nomic` (3584-dim) or `jina` (1536-dim) |
| `--qdrant-url` | `http://localhost:6333` | Qdrant server URL |
| `--collection-name` | `code_chunks` | Base Qdrant collection name (model suffix + dimensions appended automatically) |
| `--chunk-size` | `400` | Tokens per chunk |
| `--chunk-overlap` | `64` | Token overlap between chunks |
| `--batch-size` | `64` | Embedding batch size |
| `--glossary-file` | `glossary.yml` | Manual glossary YAML file path |
| `--no-graph` | `false` | Skip Neo4j graph ingestion |
| `--neo4j-uri` | `bolt://localhost:7687` | Neo4j bolt URI |
| `--neo4j-user` | `neo4j` | Neo4j username |
| `--neo4j-password` | `testpassword` | Neo4j password |
| `--dry-run` | `false` | Preview without embedding/storing |
| `--verbose` | `false` | Enable verbose (INFO-level) logging |

#### Examples

```bash
# Basic usage with default model (Nomic):
python main.py --repo-path ./my-project --verbose

# Use Jina model:
python main.py --repo-path ./my-project --model jina --verbose

# Dry run to preview what gets processed:
python main.py --repo-path ./my-project --dry-run --verbose

# Skip Neo4j (vectors only, no graph):
python main.py --repo-path ./my-project --no-graph

# Custom Qdrant and Neo4j:
python main.py --repo-path ./my-project \
  --qdrant-url http://localhost:6333 \
  --neo4j-uri bolt://localhost:7687 \
  --neo4j-user neo4j \
  --neo4j-password mypassword

# Reduce memory for large repos:
python main.py --repo-path /large/repo --batch-size 32
```

### Querying (`query.py`)

Ask questions about your indexed code using retrieval + OpenAI (`gpt-4o-mini`):

```bash
# Requires OPENAI_API_KEY in your .env
python query.py --question "How does authentication work?"

# Hybrid retrieval (vector + graph with RRF fusion)
python query.py --question "Where is the database connection established?" --retrieval hybrid

# Filter by language or file pattern
python query.py --question "What API routes exist?" --language typescript --file-pattern "src/routes/*"

# Expand query with code-specific synonyms
python query.py --question "What functions handle errors?" --expand-query

# Graph-only traversal
python query.py --question "class UserService" --retrieval graph
```

#### Query CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `--question` | *required* | Your question about the code |
| `--retrieval` | `vector` | Retrieval mode: `vector` (default), `hybrid` (vector+graph RRF), `graph` (Neo4j traversal) |
| `--top-k` | `20` | Number of code chunks to retrieve |
| `--language` | *none* | Filter: `javascript`, `typescript`, `tsx` |
| `--file-pattern` | *none* | Filter by file path glob |
| `--min-score` | `0.0` | Minimum similarity score (0.0–1.0) |
| `--expand-query` | `false` | Expand query with code synonyms |
| `--vector-weight` | `0.7` | Vector weight in hybrid mode |
| `--graph-weight` | `0.3` | Graph weight in hybrid mode |
| `--neo4j-uri` | `bolt://localhost:7687` | Neo4j bolt URI |
| `--neo4j-user` | `neo4j` | Neo4j username |
| `--neo4j-password` | `testpassword` | Neo4j password |

### MCP Server

The project includes an MCP (Model Context Protocol) server that exposes code search as tools for AI clients like Claude Desktop or OpenCode.

#### Configure in Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "code-vector-graph": {
      "type": "stdio",
      "command": "/path/to/code-vector-graph/.venv/bin/python",
      "args": ["/path/to/code-vector-graph/mcp_server.py"]
    }
  }
}
```

#### Configure in OpenCode

The project includes `.mcp.json` — OpenCode picks this up automatically.

#### Available MCP Tools

| Tool | Description |
|------|-------------|
| `search_code` | Search indexed code using vector embeddings and/or graph relationships. Supports `vector`, `hybrid` (recommended), and `graph` modes. |
| `check_health` | Check connectivity of embedder (model + device), Qdrant, and Neo4j |

#### `search_code` Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `query` | *required* | Natural language or code search query |
| `mode` | `hybrid` | `vector`, `hybrid` (recommended, RRF fusion), or `graph` |
| `top_k` | `10` | Number of results |
| `language` | *none* | Filter: `javascript`, `typescript`, `tsx` |
| `file_pattern` | *none* | File path glob filter |
| `min_score` | `0.0` | Minimum similarity score |
| `vector_weight` | `0.7` | Vector weight (hybrid mode) |
| `graph_weight` | `0.3` | Graph weight (hybrid mode) |

## Code Ontology (Neo4j Graph)

### Node Types

| Label | Description | Key Properties |
|-------|-------------|----------------|
| `File` | Source file | path, language, file_hash, imports, exports |
| `Module` | ES module | name, path, is_package |
| `Class` | Class declaration | name, start_line, end_line, is_exported, visibility, decorators, parent_class |
| `Function` | Function declaration | name, start_line, end_line, is_async, parameters, call_sites, decorators |
| `Method` | Class method | name, parent_class, is_async, parameters, call_sites |
| `Field` | Class field/property | name, parent_class, type_annotation, visibility |
| `Variable` | Variable declaration | name, is_constant, type_annotation, visibility |
| `Import` | Import statement | module, names, is_wildcard |
| `Interface` | TypeScript interface | name, extends |
| `TypeAlias` | TypeScript type alias | name, type_expression |
| `Chunk` | Code chunk (linked to Qdrant) | qdrant_id, file_path, start_line, end_line, token_count |
| `GlossaryEntry` | Manual or comment-derived term explanation | term, kind, summary, source, confidence, symbol_id |

### Relationship Types

| Type | Description |
|------|-------------|
| `CONTAINS` | File contains class/function/variable |
| `CALLS` | Function calls another function |
| `IMPORTS` | File/module imports from another |
| `INHERITS` | Class extends another class |
| `EXPORTS` | File exports a symbol |
| `REFERENCES` | Symbol references another |
| `DEFINES` | Module defines a symbol |
| `TYPE_OF` | Type relationship |
| `DEPENDS_ON` | Module dependency |
| `HAS_GLOSSARY` | Symbol has a glossary explanation |

## Project Structure

```
.
├── main.py                    # CLI entry point and pipeline orchestration
├── download_model.py          # Pre-download HuggingFace embedding model
├── mcp_server.py               # MCP server (search_code, check_health tools)
├── query.py                    # Query CLI with RAG + OpenAI
├── docker-compose.yml          # Qdrant + Neo4j services
├── requirements.txt            # Python dependencies
├── .mcp.json                   # MCP server config for OpenCode
├── src/
│   ├── __init__.py
│   ├── config.py              # Multi-model configuration (MODEL_CONFIGS)
│   ├── cli.py                  # CLI argument parsing (--model flag)
│   ├── scanner.py              # File discovery with SHA256 hashing
│   ├── parser.py               # Tree-sitter parsing, comment stripping, AST metadata
│   ├── chunker.py              # Token-aware sliding window chunking
│   ├── embedder.py             # HuggingFace embedding (Nomic + Jina with prefix dispatch)
│   ├── store.py                # Qdrant vector store with deterministic UUID5
│   ├── glossary.py             # Manual/comment glossary extraction and graph enrichment
│   ├── graph_schema.py         # Neo4j node/relationship schema definitions
│   ├── graph_extractor.py     # AST-to-graph entity extraction
│   ├── graph_store.py          # Neo4j CRUD operations with batching
│   └── hybrid_retriever.py   # Vector + graph hybrid search with RRF
├── tests/
│   ├── __init__.py
│   ├── test_config.py
│   ├── test_scanner.py
│   ├── test_parser.py
│   ├── test_chunker.py
│   ├── test_embedder.py
│   ├── test_store.py
│   ├── test_graph_extractor.py
│   ├── test_graph_store.py
│   ├── test_hybrid_retriever.py
│   ├── test_integration.py
│   └── fixtures/              # Test files
├── qdrant_storage/            # Qdrant persistent data (gitignored)
└── neo4j_data/                # Neo4j persistent data (gitignored)
```

## Technical Details

### Embedding Models

The pipeline supports two embedding models, selectable via `--model`:

**Nomic (default)**:
- **Model**: `nomic-ai/nomic-embed-code`
- **Dimensions**: 3584
- **Precision**: float16 on CUDA, float32 on MPS/ROCm/CPU
- **Task Prefixes**: None (the model works without prefixes)
- **Collection name**: `code_chunks_nomic-embed-code_3584`

**Jina**:
- **Model**: `jinaai/jina-code-embeddings-1.5b`
- **Dimensions**: 1536
- **Precision**: bfloat16 on CUDA, float32 on MPS/ROCm/CPU
- **Task Prefixes**: `code2code` for passage indexing, `nl2code` for queries
- **Collection name**: `code_chunks_jina-code-embeddings-1.5b_1536`

### Chunking Strategy

- **Chunk Size**: 400 tokens (default, configurable via `--chunk-size`)
- **Overlap**: 64 tokens (configurable via `--chunk-overlap`)
- **Line-based**: Never splits mid-line; if a single line exceeds chunk size, it's split at token boundaries
- **Token limit**: 512 tokens per embedding input (model max)

### Hybrid Retrieval (RRF)

Hybrid search combines vector similarity with graph traversal using **Reciprocal Rank Fusion**:

```
fused_score = (vector_weight / (k + vector_rank)) + (graph_weight / (k + graph_rank))
```

Default weights: vector=0.7, graph=0.3, k=60.

### Metadata Stored Per Chunk

Each vector in Qdrant includes indexed payload fields: `file_path`, `language`, `start_line`, `end_line`, `chunk_index`, `function_name`, `class_name`, `parent_function`, `imports`, `exports`, `symbols_defined`, `call_sites`, `is_exported`, `visibility`, `decorators`, `file_hash`, `text_content`, `node_type`, `nesting_depth`, `token_count`.

### Collection Naming

Collection names are auto-generated from the base name + model + dimensions:
- Nomic: `code_chunks_nomic-embed-code_3584`
- Jina: `code_chunks_jina-code-embeddings-1.5b_1536`

## Running Tests

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_embedder.py -v

# Run with coverage
python -m pytest tests/ --cov=src --cov-report=term-missing
```

## Troubleshooting

### HuggingFace Model Not Found

```
ERROR: Failed to load model 'nomic-ai/nomic-embed-code'.
```

**Solution**:
```bash
# Ensure HF_TOKEN is set in .env, then download the model:
python download_model.py              # Nomic (default)
python download_model.py --model jina # Jina
```

### Dimension Mismatch

If you see a dimension mismatch error during queries, you may have indexed with one model but are querying with another. Re-index your repository with the correct model:

```bash
python main.py --repo-path /path/to/repo --model nomic --verbose
# or
python main.py --repo-path /path/to/repo --model jina --verbose
```

### OpenAI API Key Not Set

```
ERROR: OPENAI_API_KEY environment variable is required.
```

**Solution**:
```bash
export OPENAI_API_KEY='your-key'
# Or add to your .env file
```

### Qdrant Connection Error

```
ERROR: Cannot connect to Qdrant server.
```

**Solution**:
```bash
docker-compose up -d
curl http://localhost:6333/healthz
```

### Neo4j Connection Error

Neo4j is optional — the pipeline continues without it if unavailable, or use `--no-graph` to skip entirely.

```bash
docker-compose ps neo4j
docker-compose logs neo4j
```

### Memory Issues

For large repositories, reduce batch size:

```bash
python main.py --repo-path /large/repo --batch-size 32
```

## Quick Start Summary

```bash
# 1. Clone and enter the project
git clone <repository-url> && cd code-vector-graph

# 2. Create virtual environment and install dependencies
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Configure — create .env with your tokens
cat > .env << 'EOF'
HF_TOKEN=hf_your_huggingface_token
OPENAI_API_KEY=sk_your_openai_key
EOF

# 4. Start services (Qdrant + Neo4j)
docker-compose up -d

# 5. Download embedding model (Nomic by default)
python download_model.py

# 6. Index a repository
python main.py --repo-path /path/to/repo --verbose

# 7. Query with RAG
python query.py --question "How does auth work?" --retrieval hybrid

# 8. Or start MCP server for AI client integration
python mcp_server.py
```

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.

---

Built with Tree-sitter, HuggingFace Transformers, Qdrant, Neo4j, and MCP.
