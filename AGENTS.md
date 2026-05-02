# codeVectorGraph - AGENTS.md

**Generated:** 2025-01-09
**Language:** Python 3.10+
**Stack:** Tree-sitter, LangChain, Qdrant, Ollama/HuggingFace

## MAIN RULE (MOST IMPORTANT)

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

Tradeoff: These guidelines bias toward caution over speed. For trivial tasks, use judgment.

1. Think Before Coding
Don't assume. Don't hide confusion. Surface tradeoffs.

Before implementing:

State your assumptions explicitly. If uncertain, ask.
If multiple interpretations exist, present them - don't pick silently.
If a simpler approach exists, say so. Push back when warranted.
If something is unclear, stop. Name what's confusing. Ask.
2. Simplicity First
Minimum code that solves the problem. Nothing speculative.

No features beyond what was asked.
No abstractions for single-use code.
No "flexibility" or "configurability" that wasn't requested.
No error handling for impossible scenarios.
If you write 200 lines and it could be 50, rewrite it.
Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

3. Surgical Changes
Touch only what you must. Clean up only your own mess.

When editing existing code:

Don't "improve" adjacent code, comments, or formatting.
Don't refactor things that aren't broken.
Match existing style, even if you'd do it differently.
If you notice unrelated dead code, mention it - don't delete it.
When your changes create orphans:

Remove imports/variables/functions that YOUR changes made unused.
Don't remove pre-existing dead code unless asked.
The test: Every changed line should trace directly to the user's request.

4. Goal-Driven Execution
Define success criteria. Loop until verified.

Transform tasks into verifiable goals:

"Add validation" → "Write tests for invalid inputs, then make them pass"
"Fix the bug" → "Write a test that reproduces it, then make it pass"
"Refactor X" → "Ensure tests pass before and after"
For multi-step tasks, state a brief plan:

1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

These guidelines are working if: fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

## OVERVIEW

CLI tool that transforms JS/TS code repositories into searchable vector embeddings. Pipeline: Scan → Parse (Tree-sitter) → Chunk (BERT tokenizer) → Embed (Ollama/HF) → Store (Qdrant).

## STRUCTURE

```
.
├── main.py                 # CLI entry point, pipeline orchestration
├── src/                    # Core modules (see src/AGENTS.md)
├── tests/                  # Test suite (see tests/AGENTS.md)
├── docker-compose.yml      # Qdrant service only
├── requirements.txt        # Dependencies (no pyproject.toml)
└── .sisyphus/             # OpenCode workflow state (gitignored)
```

## WHERE TO LOOK

| Task | Location | Notes |
|------|----------|-------|
| CLI args | `src/cli.py` | argparse with validation |
| Config | `src/config.py` | Hardcoded constants, providers |
| File discovery | `src/scanner.py` | SKIP_DIRS = node_modules, .git, etc. |
| Parsing | `src/parser.py` | Tree-sitter, comment stripping |
| Chunking | `src/chunker.py` | BERT tokenizer, sliding window |
| Embedding | `src/embedder.py` | Ollama/HuggingFace backends |
| Storage | `src/store.py` | Qdrant with deterministic UUID5 |
| Pipeline | `main.py` | Batch processing (FILE_BATCH_SIZE=50) |

## CONVENTIONS

**Dependencies:** `requirements.txt` only. No `pyproject.toml` or `setup.py`.

**Imports:** Use `from src.module import function` pattern.

**Logging:** Use `logger = logging.getLogger(__name__)`.

**CLI Pattern:**
```python
args = parse_args()
setup_logging(args.verbose)
run_pipeline(args)
```

**Error Handling:**
- Health checks fail fast with `sys.exit(1)` and helpful messages
- Validation happens in `parse_args()` using `parser.error()`

## ANTI-PATTERNS (EXPLICITLY FORBIDDEN)

| Pattern | Why | Location |
|---------|-----|----------|
| Global state | Causes race conditions in parallel processing | `_LAST_SOURCE_BYTES` in parser.py |
| Bare `except Exception` | Masks specific errors | parser.py lines 222-224 |
| Chunks >512 tokens | Will be truncated, data loss | embedder.py warns |
| Hardcoded HF token | Security risk | config.py line 43 |

## CRITICAL BUGS TO FIX

1. **Parser global state bug** - `_LAST_SOURCE_BYTES` must be removed per IMPLEMENTATION_GUIDE.md Phase 0
2. **Bare exception handling** - Use specific exceptions: `(ValueError, RuntimeError, OSError, UnicodeDecodeError)`

## SUPPORTED FILE TYPES

```python
SUPPORTED_EXTENSIONS = {
    ".js", ".jsx", ".mjs", ".cjs",
    ".ts", ".tsx", ".mts", ".cts"
}
```

## EMBEDDING PROVIDERS

| Provider | Model | Dimensions | Prefix |
|----------|-------|------------|--------|
| Ollama | nomic-embed-text:latest | 768 | `search_document: ` |
| HuggingFace | Salesforce/codet5p-110m-embedding | 256 | (none) |

## COMMANDS

```bash
# Setup
pip install -r requirements.txt
docker-compose up -d
ollama pull nomic-embed-text:latest

# Run
python main.py --repo-path /path/to/repo
python main.py --repo-path /path/to/repo --dry-run --verbose

# Test
python -m pytest tests/ -v
python -m pytest tests/ --cov=src --cov-report=term-missing
```

## NOTES

- **No CI/CD** - Manual execution only
- **No Makefile** - Use `python main.py` directly
- **Docker only for Qdrant** - No containerized app build
- **`.sisyphus/`** - OpenCode workflow state, internal tooling
- **Chunking**: 512 tokens with 64 overlap, line-based (never mid-line)
- **Memory control**: Files processed in batches of 50
- **Trust Remote Code**: HuggingFace uses `trust_remote_code=True` - only use trusted models
