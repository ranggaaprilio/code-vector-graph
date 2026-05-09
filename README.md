# Code Vector Graph

A Python CLI tool that transforms JavaScript/TypeScript code repositories into a searchable knowledge graph combining **vector embeddings** (Qdrant) with **code ontologies** (Neo4j). Uses Tree-sitter for language-aware parsing, HuggingFace for local embedding generation, and exposes an **MCP server** for AI-assisted code search.

## Features

- **Language-Aware Parsing**: Tree-sitter parses JS/TS/TSX files, strips comments, and extracts rich AST metadata (functions, classes, imports, call sites, decorators, visibility)
- **Smart Chunking**: Token-aware sliding window chunking using BERT tokenizer with line-boundary respect
- **Local Embeddings**: HuggingFace `nomic-ai/nomic-embed-code` model (3584-dim) for code-specific embeddings
- **Code Ontology Graph**: Neo4j stores a rich schema of Files, Classes, Functions, Methods, Variables, Imports, Interfaces, TypeAliases, and their relationships (CALLS, IMPORTS, INHERITS, CONTAINS, etc.)
- **Hybrid Retrieval**: Combines vector similarity and graph traversal using Reciprocal Rank Fusion (RRF) for superior search quality
- **MCP Server**: Expose `search_code` and `check_health` tools to any MCP-compatible AI client (Claude Desktop, OpenCode, etc.)
- **Query CLI**: Standalone query tool with code-specific query expansion and OpenAI-powered RAG answers
- **Deterministic IDs**: Content hashing for idempotent upserts — re-running won't create duplicates
- **Dry-Run Mode**: Preview what would be processed without generating embeddings

## Supported File Types

- JavaScript: `.js`, `.jsx`, `.mjs`, `.cjs`
- TypeScript: `.ts`, `.mts`, `.cts`
- TSX: `.tsx`

## Prerequisites

- Python 3.10+
- Docker & Docker Compose
- HuggingFace token (for `nomic-ai/nomic-embed-code` model access)

## Installation

### 1. Clone the repository

```bash
git clone <repository-url>
cd code-vector-graph
```

### 2. Create virtual environment

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Set up environment variables

```bash
cp .env.example .env
# Edit .env and add your HF_TOKEN
```

You need a HuggingFace token with access to `nomic-ai/nomic-embed-code`. Get one at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens).

### 5. Start infrastructure services

```bash
docker-compose up -d
```

This starts:
- **Qdrant** (Vector Database): REST API `http://localhost:6333`, gRPC `http://localhost:6334`
- **Neo4j** (Graph Database): Browser `http://localhost:7474`, Bolt `bolt://localhost:7687`

### 6. Download the embedding model

```bash
python download_model.py
```

This downloads `nomic-ai/nomic-embed-code` (~440MB) to `~/.cache/huggingface/`. The model is cached for subsequent runs.

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Scanner   │────▶│   Parser    │────▶│   Chunker   │
│  (discover  │     │(Tree-sitter │     │(BERT tokens │
│   JS/TS)    │     │ + metadata) │     │+ sliding)   │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                                │
                       ┌─────────────┐          │
                       │    Store    │◀─────────┤
                       │  (Qdrant)   │    ┌─────┴──────┐
                       └─────────────┘    │  Embedder   │
                                          │(HuggingFace)│
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
2. **Parse**: Parse each file with Tree-sitter, strip comments, extract AST metadata (functions, classes, imports, call sites, decorators, visibility)
3. **Chunk**: Create overlapping chunks using BERT tokenizer (400 tokens, 64 overlap, line-based)
4. **Embed**: Generate 3584-dim embeddings using HuggingFace `nomic-ai/nomic-embed-code`
5. **Store**: Upsert chunks into Qdrant with full metadata
6. **Graph Extract**: Extract code ontology entities (Files, Classes, Functions, Methods, Variables, Imports, Interfaces, TypeAliases) and relationships (CALLS, IMPORTS, INHERITS, CONTAINS, REFERENCES, etc.)
7. **Graph Store**: Upsert nodes and relationships into Neo4j

## Usage

### Index a Repository

Process a repository and store embeddings + graph:

```bash
python main.py --repo-path /path/to/your/repo
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
| `--qdrant-url` | `http://localhost:6333` | Qdrant server URL |
| `--collection-name` | `code_chunks` | Qdrant collection name |
| `--chunk-size` | `400` | Tokens per chunk |
| `--chunk-overlap` | `64` | Token overlap between chunks |
| `--batch-size` | `64` | Embedding batch size |
| `--no-graph` | `false` | Skip Neo4j graph ingestion |
| `--neo4j-uri` | `bolt://localhost:7687` | Neo4j bolt URI |
| `--neo4j-user` | `neo4j` | Neo4j username |
| `--neo4j-password` | `testpassword` | Neo4j password |
| `--dry-run` | `false` | Process without embedding/storing |
| `--verbose` | `false` | Enable verbose logging |

## Querying

### Query CLI

Ask questions about your indexed code using retrieval + OpenAI:

```bash
python query.py --question "How does authentication work?"
```

```bash
# Hybrid retrieval (vector + graph with RRF fusion)
python query.py --question "Where is the database connection established?" --retrieval hybrid

# Filter by language or file pattern
python query.py --question "What API routes exist?" --language typescript --file-pattern "src/routes/*"

# Expand query with code-specific synonyms
python query.py --question "What functions handle errors?" --expand-query
```

#### Query CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `--question` | *required* | Your question about the code |
| `--retrieval` | `vector` | Retrieval mode: `vector`, `hybrid` (vector+graph RRF), `graph` |
| `--top-k` | `20` | Number of code chunks to retrieve |
| `--language` | *none* | Filter: `javascript`, `typescript`, `tsx` |
| `--file-pattern` | *none* | Filter by file path glob (e.g. `*.service.ts`) |
| `--min-score` | `0.0` | Minimum similarity score (0.0–1.0) |
| `--expand-query` | `false` | Expand query with code synonyms |
| `--vector-weight` | `0.7` | Vector weight in hybrid mode |
| `--graph-weight` | `0.3` | Graph weight in hybrid mode |

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
| `search_code` | Search indexed code using vector embeddings and/or graph relationships |
| `check_health` | Check connectivity of embedder, Qdrant, and Neo4j |

#### `search_code` Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `query` | *required* | Natural language or code search query |
| `mode` | `hybrid` | `vector`, `hybrid` (recommended), or `graph` |
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
| `Variable` | Variable declaration | name, is_constant, type_annotation, visibility |
| `Import` | Import statement | module, names, is_wildcard |
| `Interface` | TypeScript interface | name, extends |
| `TypeAlias` | TypeScript type alias | name, type_expression |
| `Chunk` | Code chunk (linked to Qdrant) | qdrant_id, file_path, start_line, end_line, token_count |

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

## Project Structure

```
.
├── main.py                    # CLI entry point and pipeline orchestration
├── download_model.py          # Pre-download HuggingFace embedding model
├── mcp_server.py              # MCP server (search_code, check_health tools)
├── query.py                   # Query CLI with RAG + OpenAI
├── docker-compose.yml         # Qdrant + Neo4j services
├── requirements.txt           # Python dependencies
├── .mcp.json                  # MCP server config for OpenCode
├── src/
│   ├── __init__.py
│   ├── config.py              # Constants and configuration
│   ├── cli.py                 # CLI argument parsing
│   ├── scanner.py             # File discovery
│   ├── parser.py              # Tree-sitter parsing, comment stripping, AST metadata
│   ├── chunker.py             # Token-aware sliding window chunking
│   ├── embedder.py            # HuggingFace embedding (nomic-ai/nomic-embed-code)
│   ├── store.py               # Qdrant vector store
│   ├── graph_schema.py        # Neo4j node/relationship schema definitions
│   ├── graph_extractor.py     # AST-to-graph entity extraction
│   ├── graph_store.py         # Neo4j CRUD operations
│   └── hybrid_retriever.py    # Vector + graph hybrid search with RRF
├── tests/
│   ├── __init__.py
│   ├── test_config.py
│   ├── test_scanner.py
│   ├── test_parser.py
│   ├── test_chunker.py
│   ├── test_embedder.py
│   ├── test_store.py
│   └── test_integration.py
│   └── fixtures/              # Test files
├── qdrant_storage/            # Qdrant persistent data (gitignored)
└── neo4j_data/                # Neo4j persistent data (gitignored)
```

## Running Tests

```bash
# Run all tests
python -m pytest tests/ -v

# Run specific test file
python -m pytest tests/test_parser.py -v

# Run with coverage
python -m pytest tests/ --cov=src --cov-report=term-missing
```

## Technical Details

### Embedding Model

- **Model**: `nomic-ai/nomic-embed-code`
- **Dimensions**: 3584
- **Tokenizer**: `nomic-ai/nomic-embed-code` (BERT-based)
- **Device**: Auto-detects MPS (Apple Silicon) > CUDA > CPU
- **Distance Metric**: Cosine similarity in Qdrant

### Chunking Strategy

- **Chunk Size**: 400 tokens (default, configurable)
- **Overlap**: 64 tokens (configurable)
- **Line-based**: Never splits mid-line for better context preservation

### Hybrid Retrieval (RRF)

Hybrid search combines vector similarity with graph traversal using **Reciprocal Rank Fusion**:

```
fused_score = (vector_weight / (k + vector_rank)) + (graph_weight / (k + graph_rank))
```

Default weights: vector=0.7, graph=0.3, k=60.

### Metadata Stored Per Chunk

Each vector includes: `file_path`, `language`, `start_line`, `end_line`, `chunk_index`, `function_name`, `class_name`, `parent_function`, `imports`, `exports`, `symbols_defined`, `call_sites`, `is_exported`, `visibility`, `decorators`, `file_hash`, `text_content`.

## Troubleshooting

### HuggingFace Model Not Found

```
ERROR: Failed to load model 'nomic-ai/nomic-embed-code'.
```

**Solution**:
```bash
# Ensure HF_TOKEN is set in .env
python download_model.py
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

Neo4j is optional — the pipeline continues without it if unavailable.

```bash
# Check Neo4j status
docker-compose ps neo4j

# View logs
docker-compose logs neo4j
```

### Memory Issues

For large repositories, reduce batch size:

```bash
python main.py --repo-path /large/repo --batch-size 32
```

## Quick Start Summary

```bash
# 1. Install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Configure
cp .env.example .env  # Add your HF_TOKEN

# 3. Start services
docker-compose up -d

# 4. Download model
python download_model.py

# 5. Index a repository
python main.py --repo-path /path/to/repo --verbose

# 6. Query
python query.py --question "How does auth work?" --retrieval hybrid

# 7. Or use MCP server with your AI client
python mcp_server.py
```

## License

[Your License Here]

---

Built with Tree-sitter, HuggingFace Transformers, Qdrant, Neo4j, and MCP.