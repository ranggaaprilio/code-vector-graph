# src/ - AGENTS.md

**Generated:** 2025-01-09

## OVERVIEW

Core modules for code vectorization pipeline. Each module has a single responsibility.

## STRUCTURE

```
src/
├── __init__.py      # Empty package marker
├── cli.py           # CLI argument parsing + validation
├── config.py        # Constants, supported extensions, provider configs
├── scanner.py       # File discovery with skip logic
├── parser.py        # Tree-sitter parsing, comment stripping
├── chunker.py       # BERT token-aware sliding window chunking
├── embedder.py      # Ollama + HuggingFace embedding backends
└── store.py         # Qdrant vector store with UUID5 IDs
```

## WHERE TO LOOK

| Task | Module | Key Function/Class |
|------|--------|-------------------|
| Parse CLI args | `cli.py` | `parse_args()`, `create_parser()` |
| Scan repo | `scanner.py` | `discover_files()` |
| Parse JS/TS | `parser.py` | `parse_file()`, `strip_comments()` |
| Chunk text | `chunker.py` | `chunk_text()` |
| Create embedder | `embedder.py` | `create_embedder()` |
| Store vectors | `store.py` | `VectorStore.upsert_chunks()` |
| Get constants | `config.py` | `SUPPORTED_EXTENSIONS`, `EMBEDDING_PROVIDERS` |

## CONVENTIONS

**Module Imports:**
```python
from src.config import SUPPORTED_EXTENSIONS
from src.scanner import discover_files
```

**Abstract Base Classes:**
- `Embedder` (embedder.py) - All embedding providers must implement

**Caching:**
- `parser.py`: `_PARSER_CACHE` - Tree-sitter parsers cached by grammar
- `chunker.py`: `_tokenizer_cache` - BERT tokenizer singleton

**Logging Pattern:**
```python
import logging
logger = logging.getLogger(__name__)
```

## ANTI-PATTERNS

| Pattern | Location | Fix |
|---------|----------|-----|
| Global `_LAST_SOURCE_BYTES` | `parser.py` | Pass as parameter |
| Bare `except Exception` | `parser.py:222-224` | Catch specific errors |
| Hardcoded HF token | `config.py:43` | Load from env |

## MODULE-SPECIFIC NOTES

### scanner.py
- `SKIP_DIRS = {"node_modules", ".git", "dist", "build", "__pycache__", ".venv"}`
- Binary detection: checks for null bytes in first 8192 bytes
- Returns file hash (SHA256 first 16 chars) for deduplication

### parser.py
- Tree-sitter grammars: javascript, typescript, tsx
- Comment stripping preserves line numbers via byte-splicing
- `COMMENT_NODE_TYPES = ("comment", "line_comment", "block_comment")`

### chunker.py
- Uses `bert-base-uncased` tokenizer
- Fallback: `_DummyTokenizer` (whitespace split) for offline testing
- Never splits mid-line

### embedder.py
- Prefixes: `search_document:` for docs, `search_query:` for queries (Ollama only)
- Truncation at 512 tokens
- HuggingFace uses `trust_remote_code=True` ⚠️

### store.py
- UUID5 IDs: deterministic based on content hash
- Collection naming: `{base}_{model}_{dimensions}`
- Payload indexes for filtering on metadata fields
