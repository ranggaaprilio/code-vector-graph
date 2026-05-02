# Code Vector Graph

A Python CLI tool that transforms JavaScript/TypeScript code repositories into searchable vector embeddings stored in Qdrant, using Tree-sitter for language-aware parsing, BERT tokenizer for accurate sliding window chunking, and Ollama for local embedding generation.

## Features

- **Language-Aware Parsing**: Uses Tree-sitter to parse JS/TS/TSX files and strip comments while preserving line number metadata
- **Smart Chunking**: Token-aware sliding window chunking (512 tokens, 64 token overlap) using BERT tokenizer
- **Local Embeddings**: Leverages Ollama's `nomic-embed-text` model for efficient local embedding generation
- **Vector Storage**: Stores embeddings in Qdrant vector database with full metadata (file path, line numbers, function names)
- **Deterministic IDs**: Uses content hashing for idempotent upserts - re-running won't create duplicates
- **Health Checks**: Built-in connectivity checks for Ollama and Qdrant with clear error messages
- **Dry-Run Mode**: Preview what would be processed without generating embeddings
- **Multiple Embedding Backends**: Choose between Ollama (local, 768-dim) or HuggingFace (Salesforce/codet5p-110m-embedding, 256-dim)

## Supported File Types

- JavaScript: `.js`, `.jsx`, `.mjs`, `.cjs`
- TypeScript: `.ts`, `.mts`, `.cts`
- TSX: `.tsx`

## Prerequisites

- Python 3.10+
- Docker & Docker Compose
- [Ollama](https://ollama.com/) installed and running

## Installation

### 1. Clone the repository

```bash
git clone <repository-url>
cd codeVectorGraph
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

### 4. Start Qdrant (Vector Database)

```bash
docker-compose up -d
```

This starts Qdrant on:
- REST API: http://localhost:6335
- gRPC: http://localhost:6336

### 5. Pull the embedding model

```bash
ollama pull nomic-embed-text:latest
```

## Embedding Providers

| Feature | Ollama (nomic-embed-text) | HuggingFace (codet5p-110m-embedding) |
|---------|---------------------------|--------------------------------------|
| **Dimensions** | 768 | 256 |
| **Model Size** | ~275MB | ~440MB |
| **Local/Offline** | Yes | Yes (after first download) |
| **Prefixes** | `search_document:` / `search_query:` | None |
| **Requirements** | Ollama server | PyTorch + Transformers |
| **Best For** | General text/code | Code-specific embeddings |

### Security Note
HuggingFace provider uses `trust_remote_code=True` which executes code from the model repository. Only use models from trusted sources.

## Usage

### Basic Usage

Process a repository and store embeddings:

```bash
python main.py --repo-path /path/to/your/repo
```

### Using Ollama (Default)

```bash
python main.py --repo-path /path/to/repo
# or explicitly
python main.py --repo-path /path/to/repo --embedding-provider ollama
```

### Using HuggingFace

```bash
python main.py --repo-path /path/to/repo --embedding-provider huggingface
```

Note: First run will download the ~440MB model to `~/.cache/huggingface/`.

### Dry Run (Preview Mode)

See what would be processed without generating embeddings:

```bash
python main.py --repo-path /path/to/your/repo --dry-run
```

### Verbose Output

Show detailed progress:

```bash
python main.py --repo-path /path/to/your/repo --verbose
```

### Custom Configuration

```bash
python main.py \
  --repo-path /path/to/repo \
  --qdrant-url http://localhost:6333 \
  --collection-name my_code_chunks \
  --ollama-url http://localhost:11434 \
  --model nomic-embed-text:latest \
  --chunk-size 512 \
  --chunk-overlap 64 \
  --batch-size 64 \
  --verbose
```

### CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `--repo-path` | *required* | Path to the repository to process |
| `--qdrant-url` | `http://localhost:6333` | Qdrant server URL |
| `--collection-name` | `code_chunks` | Qdrant collection name |
| `--ollama-url` | `http://localhost:11434` | Ollama server URL |
| `--model` | `nomic-embed-text:latest` | Ollama embedding model |
| `--embedding-provider` | `ollama` | Embedding backend: `ollama` or `huggingface` |
| `--chunk-size` | `512` | Tokens per chunk |
| `--chunk-overlap` | `64` | Token overlap between chunks |
| `--batch-size` | `64` | Embedding batch size |
| `--dry-run` | `false` | Process without embedding/storing |
| `--verbose` | `false` | Enable verbose logging |

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Scanner   │────▶│   Parser    │────▶│   Chunker   │
│  (discover  │     │(Tree-sitter │     │(BERT tokens │
│   JS/TS)    │     │ + strip)    │     │+ sliding)   │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                                │
                       ┌─────────────┐          │
                       │    Store    │◀─────────┘
                       │  (Qdrant)   │    ┌─────────────┐
                       └─────────────┘    │  Embedder   │
                                          │   (Ollama)  │
                                          └─────────────┘
```

### Pipeline Flow

1. **Scan**: Discover all JS/TS files (excludes `node_modules`, `.git`, etc.)
2. **Parse**: Parse each file with Tree-sitter, strip comments, preserve line numbers
3. **Chunk**: Create overlapping chunks using BERT tokenizer (512 tokens, 64 overlap)
4. **Embed**: Generate embeddings using Ollama with `search_document:` prefix
5. **Store**: Upsert chunks into Qdrant with full metadata

## Project Structure

```
.
├── main.py                    # CLI entry point and pipeline orchestration
├── docker-compose.yml         # Qdrant vector database
├── requirements.txt           # Python dependencies
├── src/
│   ├── __init__.py
│   ├── config.py             # Constants and configuration
│   ├── scanner.py            # File discovery
│   ├── parser.py             # Tree-sitter parsing & comment stripping
│   ├── chunker.py            # Token-aware sliding window chunking
│   ├── embedder.py           # Ollama embedding integration
│   ├── store.py              # Qdrant vector store
│   └── cli.py                # CLI argument parsing
├── tests/
│   ├── __init__.py
│   ├── test_config.py
│   ├── test_scanner.py
│   ├── test_parser.py
│   ├── test_chunker.py
│   ├── test_embedder.py
│   ├── test_store.py
│   └── test_integration.py
│   └── fixtures/             # Test files
│       ├── sample.js
│       ├── sample.ts
│       ├── component.tsx
│       └── ...
└── qdrant_storage/           # Qdrant persistent data (gitignored)
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

- **Model**: `nomic-embed-text:latest`
- **Dimensions**: 768
- **Tokenizer**: bert-base-uncased
- **Prefix**: `search_document:` (prepended to all chunks)
- **Distance Metric**: Cosine similarity in Qdrant

### Chunking Strategy

- **Chunk Size**: 512 tokens (configurable)
- **Overlap**: 64 tokens (configurable)
- **Line-based**: Never splits mid-line for better context preservation
- **Tokenizer**: Uses HuggingFace `tokenizers` library with BERT tokenizer

### Comment Stripping

Uses Tree-sitter AST parsing to remove:
- `//` line comments
- `/* */` block comments
- `/** */` JSDoc comments

Line numbers are mapped to the original source before comment removal.

### Metadata Stored

Each vector includes:
- `file_path`: Path to source file
- `language`: Detected language (javascript, typescript, tsx)
- `start_line`: Starting line in original source
- `end_line`: Ending line in original source
- `chunk_index`: Position within file (0-indexed)
- `function_name`: Enclosing function name (if applicable)
- `total_chunks`: Total chunks in file
- `text_content`: The chunk text content

## Troubleshooting

### Ollama Connection Error

```
ERROR: Cannot connect to Ollama or model is not available.
```

**Solution**:
```bash
# Start Ollama
ollama serve

# Pull the model
ollama pull nomic-embed-text:latest
```

### Qdrant Connection Error

```
ERROR: Cannot connect to Qdrant server.
```

**Solution**:
```bash
# Start Qdrant
docker-compose up -d

# Verify it's running
curl http://localhost:6333/healthz
```

### Port Conflicts

If ports 6333 or 6334 are already in use:

```bash
# Stop existing containers
sudo lsof -ti:6333 | xargs kill -9

# Or modify docker-compose.yml to use different ports
```

### Memory Issues

For large repositories, reduce batch size:

```bash
python main.py --repo-path /large/repo --batch-size 32
```

### HuggingFace Model Download

First use requires downloading the model (~440MB):

```
Loading HuggingFace model Salesforce/codet5p-110m-embedding...
```

This is cached in `~/.cache/huggingface/` for subsequent runs.

## Development

### Adding New File Types

Edit `src/config.py` and add to `SUPPORTED_EXTENSIONS`:

```python
SUPPORTED_EXTENSIONS = {
    # ... existing extensions ...
    ".vue": {"language": "vue", "grammar": "vue"},
}
```

### Environment Variables

Create a `.env` file for local development (optional):

```bash
QDRANT_URL=http://localhost:6333
OLLAMA_URL=http://localhost:11434
```

## License

[Your License Here]

## Contributing

Contributions welcome! Please ensure:
- Tests pass: `python -m pytest tests/`
- Code follows existing patterns
- New features include tests

---

Built with Tree-sitter, LangChain, Qdrant, and Ollama.
