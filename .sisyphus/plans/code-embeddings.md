# Code Vector Embedding System

## TL;DR

> **Quick Summary**: Build a Python CLI tool that scans JS/TS code repositories, parses them with Tree-sitter to strip comments, chunks the clean code using a sliding window (512 tokens, 64 overlap) with accurate BERT tokenization, embeds each chunk via Ollama's nomic-embed-text model with the `search_document:` prefix, and inserts all vectors with full metadata into a Qdrant vector database running via Docker Compose.
>
> **Deliverables**:
> - Docker Compose for Qdrant with persistent storage
> - `src/scanner.py` — JS/TS/TSX file discovery module
> - `src/parser.py` — Tree-sitter parsing + comment stripping + line number preservation
> - `src/chunker.py` — Token-aware sliding window chunker (bert-base-uncased tokenizer)
> - `src/embedder.py` — Ollama embedding with `search_document:` prefix
> - `src/store.py` — Qdrant connection, collection creation (768/COSINE), upsert
> - `src/config.py` — Shared constants and defaults
> - `src/cli.py` — argparse CLI entry point with health checks and progress output
> - `main.py` — Pipeline orchestration entry point
> - `requirements.txt` — All dependencies pinned
> - `tests/` — Full pytest test suite for all modules
>
> **Estimated Effort**: Medium
> **Parallel Execution**: YES — 3 waves (2 + 5 + 1) + final verification
> **Critical Path**: T1 → T2 → T4 → T8 → F1-F4

---

## Context

### Original Request
User wants code that translates a code repository into vector embeddings using Ollama (nomic-embed-text:latest), Tree-sitter for code parsing (comment removal, simplified syntax), sliding window with overlap chunking, Python/LangChain, and Qdrant as vector DB via Docker Compose.

### Interview Summary
**Key Discussions**:
- Languages: JS/TS only — handle `.js`, `.jsx`, `.ts`, `.tsx`, `.mjs`, `.cjs`, `.mts`, `.cts`
- Target: Reusable CLI tool accepting any directory path
- Chunk size: 512 tokens with 64 token overlap (bert-base-uncased tokenizer)
- Metadata: Full — file_path, language, start_line, end_line, chunk_index, function_name, total_chunks
- Test strategy: pytest, tests written after implementation
- Interface: CLI tool with argparse (repo path, Qdrant URL, chunk size, overlap, etc.)

**Research Findings**:
- nomic-embed-text uses bert-base-uncased tokenizer (NOT tiktoken) — must use `tokenizers` library
- nomic-embed-text requires `search_document:` prefix for optimal retrieval quality
- nomic-embed-text outputs 768-dim vectors — Qdrant collection must be pre-created with `VectorParams(size=768, distance=COSINE)`
- TypeScript has TWO grammars: `language_typescript()` for `.ts`, `language_tsx()` for `.tsx`
- Tree-sitter doesn't store text in nodes — only byte offsets; must splice source bytes manually
- JS/TS comment node types: `comment`, `line_comment`, `block_comment` — must handle all three
- Modern tree-sitter Python API: `Language(module.language())` one-arg form (old `Language.build_library()` is deprecated)

### Metis Review
**Identified Gaps** (addressed):
- Tokenizer mismatch: Using `tokenizers` library with bert-base-uncased instead of tiktoken/character heuristic
- `search_document:` prefix: Will prepend to all chunks before embedding
- TSX handling: Will detect `.tsx` extension and use `language_tsx()` grammar
- Qdrant collection dimensions: Will pre-create with 768/COSINE before any insert
- Line number preservation: Will build byte-to-line mapping from original source BEFORE comment removal
- Edge cases: Parse errors → log and skip; binary files → skip; Ollama/Qdrant unreachable → fail fast at startup

---

## Work Objectives

### Core Objective
Build a Python CLI tool that transforms a JS/TS code repository into searchable vector embeddings stored in Qdrant, using Tree-sitter for language-aware parsing (comment removal), BERT tokenizer for accurate token-based sliding window chunking, and Ollama for embedding with the nomic-embed-text model.

### Concrete Deliverables
- `docker-compose.yml` for Qdrant (port 6333, persistent volume)
- `requirements.txt` with all pinned dependencies
- `src/config.py` with centralized constants
- `src/scanner.py` with file discovery for supported extensions
- `src/parser.py` with Tree-sitter parsing, comment stripping, line number preservation, function name extraction
- `src/chunker.py` with sliding window chunking using `tokenizers` (bert-base-uncased) for 512-token windows with 64-token overlap
- `src/embedder.py` with Ollama embedding, `search_document:` prefix, batch support
- `src/store.py` with Qdrant collection creation (768/COSINE), upsert with metadata
- `src/cli.py` with argparse CLI, health checks, progress logging
- `main.py` pipeline orchestration
- `tests/test_*.py` for all modules

### Definition of Done
- [x] `docker-compose up -d` starts Qdrant accessible at `localhost:6333`
- [x] `python main.py --repo-path /some/repo --dry-run` discovers JS/TS files, parses them, chunks them, prints stats without embedding/storing
- [x] `python main.py --repo-path /some/repo` processes all files, embeds chunks, inserts into Qdrant
- [x] Qdrant collection has vectors with 768 dimensions, COSINE distance, and payload containing all metadata fields
- [x] All pytest tests pass
- [x] No comments in embedded code (verified by re-parsing chunks)
- [x] All chunks start with `search_document:` prefix before embedding
- [x] CLI fails fast with clear error when Ollama or Qdrant is unreachable

### Must Have
- Comment stripping using Tree-sitter AST (NOT regex) — handle `comment`, `line_comment`, `block_comment` node types
- Accurate token counting using `tokenizers` library with `bert-base-uncased` — NOT tiktoken, NOT character heuristic
- `search_document:` prefix prepended to every chunk before embedding
- Qdrant collection pre-created with `VectorParams(size=768, distance=Distance.COSINE)` before any insert
- Separate tree-sitter grammars for `.ts` (`language_typescript()`) and `.tsx` (`language_tsx()`)
- Line number metadata referencing ORIGINAL source lines (before comment removal)
- Deterministic chunk IDs for idempotent upserts (hash of file_path + chunk_index)
- CLI health checks for Ollama and Qdrant at startup
- `--dry-run` flag that runs pipeline through chunking without embedding/storing
- `--verbose` flag for progress output
- Docker Compose for Qdrant with persistent volume

### Must NOT Have (Guardrails)
- No regex-based comment stripping (Tree-sitter AST only)
- No tiktoken usage (wrong tokenizer for nomic-embed-text)
- No `transformers` dependency (use lightweight `tokenizers` library)
- No `QdrantVectorStore.from_documents()` auto-creation (pre-create collection manually)
- No deprecated `Language.build_library()` API (use modern `Language(module.language())`)
- No search/query CLI subcommands (scope is embedding pipeline only)
- No web UI or API server (CLI tool only)
- No incremental/update mode (full re-process per run)
- No language support beyond JS/TS/TSX (no plugin system, no abstraction for future languages)
- No whitespace normalization or minification beyond comment removal

---

## Verification Strategy (MANDATORY)

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed. No exceptions.

### Test Decision
- **Infrastructure exists**: NO (greenfield)
- **Automated tests**: YES (Tests after)
- **Framework**: pytest
- **Test runner command**: `python -m pytest tests/ -v`

### QA Policy
Every task MUST include agent-executed QA scenarios.
Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

- **CLI/Backend**: Use Bash (python commands, curl) — Run commands, check exit codes, validate output
- **Qdrant verification**: Use Bash (curl) — Query vector DB, assert collection properties and point counts

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately — foundation + scaffolding):
├── T1: Project scaffolding + requirements.txt + Docker Compose [quick]
└── T2: Config/constants module [quick]

Wave 2 (After Wave 1 — core modules, MAX PARALLEL):
├── T3: Scanner module (file discovery) + tests [quick]
├── T4: Parser module (Tree-sitter + comment stripping) + tests [deep]
├── T5: Chunker module (sliding window + tokenizers) + tests [deep]
├── T6: Embedder module (Ollama + search_document prefix) + tests [unspecified-high]
└── T7: Store module (Qdrant connection + collection + upsert) + tests [unspecified-high]

Wave 3 (After Wave 2 — integration):
└── T8: CLI + pipeline orchestration + integration tests [unspecified-high]

Wave FINAL (After ALL tasks — 4 parallel reviews, then user okay):
├── F1: Plan compliance audit (oracle)
├── F2: Code quality review (unspecified-high)
├── F3: Real manual QA (unspecified-high)
└── F4: Scope fidelity check (deep)
→ Present results → Get explicit user okay

Critical Path: T1 → T2 → T4 → T8 → F1-F4 → user okay
Parallel Speedup: ~65% faster than sequential
Max Concurrent: 5 (Wave 2)
```

### Dependency Matrix

| Task | Depends On | Blocks | Wave |
|------|-----------|--------|------|
| T1   | —         | T2, T7 | 1    |
| T2   | —         | T3-T8  | 1    |
| T3   | T2        | T8     | 2    |
| T4   | T2        | T8     | 2    |
| T5   | T2        | T8     | 2    |
| T6   | T2        | T8     | 2    |
| T7   | T1        | T8     | 2    |
| T8   | T3-T7     | F1-F4  | 3    |
| F1   | T8        | —      | FINAL|
| F2   | T8        | —      | FINAL|
| F3   | T8        | —      | FINAL|
| F4   | T8        | —      | FINAL|

### Agent Dispatch Summary

- **Wave 1**: 2 tasks — T1 → `quick`, T2 → `quick`
- **Wave 2**: 5 tasks — T3 → `quick`, T4 → `deep`, T5 → `deep`, T6 → `unspecified-high`, T7 → `unspecified-high`
- **Wave 3**: 1 task — T8 → `unspecified-high`
- **FINAL**: 4 tasks — F1 → `oracle`, F2 → `unspecified-high`, F3 → `unspecified-high`, F4 → `deep`

---

## TODOs

- [x] 1. Project Scaffolding + Docker Compose + Requirements

  **What to do**:
  - Create project directory structure: `src/`, `tests/`, `tests/fixtures/`
  - Create `requirements.txt` with pinned versions:
    ```
    tree-sitter>=0.22
    tree-sitter-javascript>=0.21
    tree-sitter-typescript>=0.21
    langchain-ollama>=0.2
    langchain-qdrant>=0.2
    qdrant-client>=1.9
    tokenizers>=0.19
    pytest>=8.0
    ```
  - Create `docker-compose.yml` for Qdrant:
    - Image: `qdrant/qdrant:latest`
    - Ports: `6333:6333`, `6334:6334`
    - Volume: `./qdrant_storage:/qdrant/storage` for persistence
    - Restart policy: unless-stopped
  - Create `src/__init__.py` (empty)
  - Create `tests/__init__.py` (empty)
  - Create `main.py` with placeholder `if __name__ == "__main__": pass`
  - Create `.gitignore` with `__pycache__/`, `*.pyc`, `.venv/`, `qdrant_storage/`, `.env`

  **Must NOT do**:
  - Do NOT install `transformers` (use `tokenizers` only)
  - Do NOT install `tiktoken` (wrong tokenizer)
  - Do NOT add a Dockerfile for the Python app (only Qdrant Docker Compose)

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Pure file creation, no complex logic
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T2)
  - **Parallel Group**: Wave 1
  - **Blocks**: T7 (needs docker-compose.yml and requirements.txt)
  - **Blocked By**: None (can start immediately)

  **References** (CRITICAL):

  **Pattern References**:
  - Qdrant Docker Compose: `https://qdrant.tech/documentation/guides/installation/#docker` — Official Qdrant Docker setup with volume persistence and port mapping

  **API/Type References**:
  - `requirements.txt`: Pin `tree-sitter>=0.22` for modern API, `tokenizers>=0.19` for bert-base-uncased, `langchain-ollama>=0.2` and `langchain-qdrant>=0.2` for LangChain integrations

  **WHY Each Reference Matters**:
  - Qdrant Docker Compose pattern: Ensures correct port mapping (6333 REST, 6334 gRPC) and persistent volume setup
  - Pinned versions: tree-sitter>=0.22 required for modern `Language(module.language())` API; tokenizers provides lightweight BERT tokenizer without PyTorch dependency

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: Docker Compose starts Qdrant successfully
    Tool: Bash
    Preconditions: Docker is installed and running
    Steps:
      1. Run `docker-compose up -d` in project root
      2. Run `curl -s http://localhost:6333/healthz`
      3. Assert response contains "ok" or status code 200
    Expected Result: Qdrant container running, health endpoint returns 200
    Failure Indicators: Container not running, health check fails, port conflict
    Evidence: .sisyphus/evidence/task-1-docker-health.txt

  Scenario: Python dependencies install without errors
    Tool: Bash
    Preconditions: Python 3.10+ and pip available
    Steps:
      1. Run `python -m venv .venv && source .venv/bin/activate`
      2. Run `pip install -r requirements.txt`
      3. Run `python -c "import tree_sitter; import tokenizers; import qdrant_client; import langchain_ollama; import langchain_qdrant"`
    Expected Result: All imports succeed, no ModuleNotFoundError
    Failure Indicators: Any import fails, pip install fails with dependency conflict
    Evidence: .sisyphus/evidence/task-1-deps-install.txt
  ```

  **Commit**: YES
  - Message: `feat(init): project scaffolding with Docker Compose and requirements`
  - Files: `requirements.txt`, `docker-compose.yml`, `main.py`, `src/__init__.py`, `tests/__init__.py`, `.gitignore`

- [x] 2. Config/Constants Module

  **What to do**:
  - Create `src/config.py` with all shared constants and configuration:
    - `SUPPORTED_EXTENSIONS`: dict mapping file extensions to language names and tree-sitter grammar names
      ```python
      SUPPORTED_EXTENSIONS = {
          ".js": {"language": "javascript", "grammar": "javascript"},
          ".jsx": {"language": "javascript", "grammar": "javascript"},
          ".mjs": {"language": "javascript", "grammar": "javascript"},
          ".cjs": {"language": "javascript", "grammar": "javascript"},
          ".ts": {"language": "typescript", "grammar": "typescript"},
          ".tsx": {"language": "tsx", "grammar": "tsx"},
          ".mts": {"language": "typescript", "grammar": "typescript"},
          ".cts": {"language": "typescript", "grammar": "typescript"},
      }
      ```
    - `COMMENT_NODE_TYPES`: `("comment", "line_comment", "block_comment")`
    - `DEFAULT_CHUNK_SIZE`: `512`
    - `DEFAULT_CHUNK_OVERLAP`: `64`
    - `DEFAULT_OLLAMA_URL`: `"http://localhost:11434"`
    - `DEFAULT_QDRANT_URL`: `"http://localhost:6333"`
    - `DEFAULT_COLLECTION_NAME`: `"code_chunks"`
    - `DEFAULT_MODEL`: `"nomic-embed-text:latest"`
    - `EMBEDDING_DIMENSIONS`: `768`
    - `EMBEDDING_PREFIX`: `"search_document: "`
    - `TOKENIZER_NAME`: `"bert-base-uncased"`
  - Write tests in `tests/test_config.py`:
    - Test all extensions are covered by SUPPORTED_EXTENSIONS
    - Test constants have expected values (768 dimensions, COSINE distance, etc.)
    - Test EMBEDDING_PREFIX equals `"search_document: "`

  **Must NOT do**:
  - Do NOT add configuration for other languages (Python, Go, Rust, etc.)
  - Do NOT add runtime configuration loading from YAML/env files (constants only for now)
  - Do NOT add `transformers` or `tiktoken` references

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Simple constants file, minimal logic
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T1)
  - **Parallel Group**: Wave 1
  - **Blocks**: T3, T4, T5, T6, T7, T8 (all modules import from config)
  - **Blocked By**: None (can start immediately)

  **References** (CRITICAL):

  **API/Type References**:
  - `src/config.py` — This file IS the reference; it defines all shared constants
  - nomic-embed-text model card: `https://huggingface.co/nomic-ai/nomic-embed-text-v1.5` — Confirms 768 dimensions, `search_document:` prefix requirement, bert-base-uncased tokenizer

  **WHY Each Reference Matters**:
  - Model card: Confirms embedding dimensions (768), required prefix format, and tokenizer choice
  - All other modules import from config: Centralized constants prevent magic numbers scattered across codebase

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: Config constants have correct values
    Tool: Bash
    Preconditions: Python venv with dependencies installed
    Steps:
      1. Run `python -c "from src.config import EMBEDDING_DIMENSIONS, EMBEDDING_PREFIX, COMMENT_NODE_TYPES, DEFAULT_CHUNK_SIZE; assert EMBEDDING_DIMENSIONS == 768; assert EMBEDDING_PREFIX == 'search_document: '; assert COMMENT_NODE_TYPES == ('comment', 'line_comment', 'block_comment'); assert DEFAULT_CHUNK_SIZE == 512; print('ALL PASSED')"`
    Expected Result: Prints "ALL PASSED" with exit code 0
    Failure Indicators: ImportError, AssertionError, wrong constant values
    Evidence: .sisyphus/evidence/task-2-config-constants.txt

  Scenario: All supported extensions have language and grammar mappings
    Tool: Bash
    Preconditions: Config module exists
    Steps:
      1. Run `python -m pytest tests/test_config.py -v`
    Expected Result: All config tests pass (extension coverage, constant values)
    Failure Indicators: Missing extensions, wrong mappings, assertion failures
    Evidence: .sisyphus/evidence/task-2-config-tests.txt
  ```

  **Commit**: YES
  - Message: `feat(config): add shared constants and configuration module`
  - Files: `src/config.py`, `tests/test_config.py`
  - Pre-commit: `python -m pytest tests/test_config.py -v`

- [x] 3. Scanner Module (File Discovery) + Tests

  **What to do**:
  - Create `src/scanner.py` with a `discover_files(repo_path: str) -> list[dict]` function:
    - Walk directory tree starting at `repo_path`
    - For each file, check extension against `SUPPORTED_EXTENSIONS` from config
    - Skip directories: `node_modules`, `.git`, `dist`, `build`, `__pycache__`, `.venv`
    - Skip binary files (check for null bytes in first 8192 bytes)
    - Skip files with encoding errors (try UTF-8 decode, skip on failure)
    - Return list of dicts: `{"path": str, "extension": str, "language": str, "grammar": str}`
    - Sort results by file path for deterministic ordering
  - Write tests in `tests/test_scanner.py`:
    - Test with a test fixtures directory containing `.js`, `.ts`, `.tsx`, `.jsx` files
    - Test that `node_modules`, `.git` directories are skipped
    - Test that binary files are skipped
    - Test that `.py`, `.md`, `.json` files are skipped (unsupported extensions)
    - Test that hidden directories (`.git`) are skipped
  - Create `tests/fixtures/` with sample JS/TS files for testing:
    - `tests/fixtures/sample.js` — simple JS with comments
    - `tests/fixtures/sample.ts` — TypeScript with types and comments
    - `tests/fixtures/component.tsx` — React TSX component
    - `tests/fixtures/binary.bin` — binary file (should be skipped)
    - `tests/fixtures/node_modules/ignored.js` — should be skipped (in node_modules)

  **Must NOT do**:
  - Do NOT scan for Python, Go, Rust, or other non-JS/TS files
  - Do NOT read file contents in the scanner (that's the parser's job)
  - Do NOT use glob patterns that might miss `.mjs`, `.cjs`, `.mts`, `.cts` extensions

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Straightforward directory walking with filtering logic
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T4, T5, T6, T7)
  - **Parallel Group**: Wave 2
  - **Blocks**: T8 (pipeline needs scanner)
  - **Blocked By**: T2 (needs SUPPORTED_EXTENSIONS from config)

  **References** (CRITICAL):

  **Pattern References**:
  - `src/config.py:SUPPORTED_EXTENSIONS` — Extension-to-language mapping that scanner must use for classification

  **API/Type References**:
  - `os.walk()` — Python stdlib for directory traversal, skip directories by name
  - `pathlib.Path` — Preferred path handling in modern Python

  **WHY Each Reference Matters**:
  - SUPPORTED_EXTENSIONS: Scanner must use the same extension mapping that all other modules reference, ensuring consistency
  - Directory skipping: Avoids scanning massive node_modules/.git directories which would waste time and produce noise

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: Scanner discovers JS/TS files and skips excluded directories
    Tool: Bash
    Preconditions: Test fixtures directory exists with sample files
    Steps:
      1. Run `python -m pytest tests/test_scanner.py -v`
      2. Assert all scanner tests pass
    Expected Result: Tests pass — JS/TS/TSX files found, node_modules/binary files skipped
    Failure Indicators: Missing files, wrong language mapping, binary files not skipped
    Evidence: .sisyphus/evidence/task-3-scanner-tests.txt

  Scenario: Scanner integration with real directory structure
    Tool: Bash
    Preconditions: Project directory exists
    Steps:
      1. Run `python -c "from src.scanner import discover_files; files = discover_files('.'); print(len(files)); [print(f['path'], f['language']) for f in files[:5]]"`
      2. Assert output shows JS/TS files with correct language labels
      3. Assert no files from node_modules, .git, .venv directories
    Expected Result: Files found with correct language/grammar mappings, excluded dirs not present
    Failure Indicators: Zero files found, wrong languages, excluded dirs included
    Evidence: .sisyphus/evidence/task-3-scanner-integration.txt
  ```

  **Commit**: YES
  - Message: `feat(scanner): add JS/TS file discovery module with tests`
  - Files: `src/scanner.py`, `tests/test_scanner.py`, `tests/fixtures/`
  - Pre-commit: `python -m pytest tests/test_scanner.py -v`

- [x] 4. Parser Module (Tree-sitter Parsing + Comment Stripping) + Tests

  **What to do**:
  - Create `src/parser.py` with:
    - `get_parser(grammar_name: str) -> tree_sitter.Parser` — Returns cached parser for the given grammar ("javascript", "typescript", "tsx"). Uses `tree_sitter.Language(tree_sitter_javascript.language())` for JS, `tree_sitter.Language(tree_sitter_typescript.language_typescript())` for TS, `tree_sitter.Language(tree_sitter_typescript.language_tsx())` for TSX. Parser instances should be cached per grammar type.
    - `strip_comments(source_bytes: bytes, grammar_name: str) -> tuple[str, dict]` — Primary function:
      1. Parse source with appropriate Tree-sitter grammar
      2. Walk AST, collect all nodes with `type in COMMENT_NODE_TYPES`
      3. Build a byte-offset-to-line-number mapping from ORIGINAL source (before modification)
      4. Collect non-comment byte ranges: iterate through all leaf nodes, exclude comment nodes, preserve non-comment text
      5. Reconstruct clean source by splicing non-comment byte ranges
      6. For each chunk of clean source, map original byte offsets back to original line numbers
      7. Return `(stripped_text: str, line_map: dict)` where line_map maps stripped-text byte offsets to original line numbers
    - `extract_function_name(tree: tree_sitter.Tree, node_start_byte: int, node_end_byte: int) -> str | None` — Walk AST to find enclosing function_declaration, method_declaration, or arrow_function. Return the function name string, or None for module-level code.
    - `parse_file(file_path: str, grammar_name: str) -> dict` — Reads file, calls strip_comments, extracts function names, returns `{"stripped_text": str, "original_line_count": int, "stripped_line_count": int, "line_mapping": dict}`. On parse error or encoding error: log warning and return None.
  - Write tests in `tests/test_parser.py`:
    - Test JS parsing: `// line comment` stripped, `/* block */` stripped, code preserved
    - Test TS parsing: type annotations preserved, interface preserved
    - Test TSX parsing: JSX syntax preserved, comments inside JSX stripped
    - Test JSDoc stripping: `/** @param x */` is stripped (it's type `comment`)
    - Test line number preservation: original line numbers map correctly after comment removal
    - Test function name extraction: finds `function hello()`, `const arrow = () =>`, `class Method`, returns None for module-level code
    - Test parse error handling: malformed source returns None with warning logged
    - Test that re-parsing stripped output contains zero comment nodes (verify no comments leaked)
    - Create test fixtures in `tests/fixtures/` with files containing all comment types

  **Must NOT do**:
  - Do NOT use regex-based comment stripping — Tree-sitter AST only
  - Do NOT use `Language.build_library()` — use modern `Language(module.language())` API
  - Do NOT store file content in parser cache (only parser instances)
  - Do NOT modify the original source bytes; work on copies
  - Do NOT minify or normalize whitespace beyond removing comments

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Complex AST traversal, byte-splicing, and line mapping logic — core algorithmic component
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T3, T5, T6, T7)
  - **Parallel Group**: Wave 2
  - **Blocks**: T8 (pipeline needs parser)
  - **Blocked By**: T2 (needs COMMENT_NODE_TYPES, SUPPORTED_EXTENSIONS from config)

  **References** (CRITICAL):

  **Pattern References**:
  - Modern tree-sitter grammar loading: `Language(tree_sitter_javascript.language())` — One-arg API, NOT the deprecated `Language.build_library()`
  - Tree-sitter comment stripping: Collect `comment`/`line_comment`/`block_comment` node byte ranges, splice source bytes to exclude them
  - `mrmike/android_source_explorer_parser/tree_sitter_parser.py` — Pattern for `Parser(language)` creation and file parsing: `parser = tree_sitter.Parser(language); tree = parser.parse(source_code)`

  **API/Type References**:
  - `tree_sitter.Tree.root_node` — Entry point for AST traversal
  - `tree_sitter.Node.type` — Node type string (use to check for comment types)
  - `tree_sitter.Node.start_byte` / `end_byte` — Byte offsets into original source
  - `tree_sitter.Node.start_point` / `end_point` — Row/column positions (`Point(row, column)`)
  - `tree_sitter.Node.children` — Child nodes for traversal
  - `tree_sitter.Node.text` — Byte content of node (from original source)
  - `src/config.py:COMMENT_NODE_TYPES` — Comment node types to filter

  **Test References**:
  - `tests/fixtures/sample.js` — JS test file with line comments, block comments, JSDoc
  - `tests/fixtures/sample.ts` — TS test file with type annotations and comments
  - `tests/fixtures/component.tsx` — TSX test file with JSX and comments

  **External References**:
  - Tree-sitter Python docs: `https://tree-sitter.github.io/tree-sitter/using-parsers` — Node API, traversal patterns

  **WHY Each Reference Matters**:
  - Grammar loading pattern: Using deprecated API will cause import/runtime errors; must use `Language(module.language())`
  - Byte-splicing approach: Tree-sitter doesn't store text in nodes, only offsets; must reconstruct by splicing byte ranges
  - Line mapping: After comment removal, source positions shift; need original line numbers for metadata

  **Acceptance Criteria**:

  **If TDD (tests enabled):**
  - [ ] Test file created: tests/test_parser.py
  - [ ] python -m pytest tests/test_parser.py → PASS (all tests, 0 failures)

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: Comment stripping removes all comment types
    Tool: Bash
    Preconditions: Test fixtures with all comment types exist
    Steps:
      1. Run `python -m pytest tests/test_parser.py::test_strip_js_comments -v`
      2. Run `python -m pytest tests/test_parser.py::test_strip_ts_comments -v`
      3. Run `python -m pytest tests/test_parser.py::test_strip_tsx_comments -v`
    Expected Result: All comment stripping tests pass; re-parsed output has zero comment nodes
    Failure Indicators: Comment nodes found in stripped output, assertion failures
    Evidence: .sisyphus/evidence/task-4-comment-stripping.txt

  Scenario: Line number mapping preserves original positions
    Tool: Bash
    Preconditions: Test fixtures with known line positions exist
    Steps:
      1. Run `python -m pytest tests/test_parser.py::test_line_mapping -v`
      2. Verify that stripped code line 1 maps to original code line N (after comments removed)
    Expected Result: Line numbers in metadata correspond to original source, not stripped source
    Failure Indicators: Line mapping returns wrong original line numbers
    Evidence: .sisyphus/evidence/task-4-line-mapping.txt

  Scenario: Parse error handled gracefully
    Tool: Bash
    Preconditions: Malformed source fixture exists
    Steps:
      1. Run `python -m pytest tests/test_parser.py::test_parse_error -v`
      2. Verify function returns None and logs warning
    Expected Result: No crash, None returned, warning logged
    Failure Indicators: Exception raised, non-None return on malformed source
    Evidence: .sisyphus/evidence/task-4-parse-error.txt
  ```

  **Commit**: YES
  - Message: `feat(parser): add Tree-sitter parsing and comment stripping with tests`
  - Files: `src/parser.py`, `tests/test_parser.py`
  - Pre-commit: `python -m pytest tests/test_parser.py -v`

- [x] 5. Chunker Module (Sliding Window + Tokenizers) + Tests

  **What to do**:
  - Create `src/chunker.py` with:
    - `load_tokenizer() -> tokenizers.Tokenizer` — Load bert-base-uncased tokenizer from `tokenizers` library. Cache the instance for reuse.
    - `count_tokens(text: str, tokenizer: tokenizers.Tokenizer) -> int` — Count tokens in text using the tokenizer. Return integer token count.
    - `chunk_text(text: str, start_line: int, end_line: int, chunk_size: int = DEFAULT_CHUNK_SIZE, chunk_overlap: int = DEFAULT_CHUNK_OVERLAP, function_name: str | None = None, file_path: str = "", language: str = "", total_chunks: int = 0) -> list[dict]`:
      - Split text into chunks using sliding window of `chunk_size` tokens with `chunk_overlap` token overlap
      - Use line-based chunking: accumulate lines until token count reaches chunk_size, then start new chunk
      - Each chunk is a dict: `{"text": str, "metadata": {"file_path": str, "language": str, "start_line": int, "end_line": int, "chunk_index": int, "function_name": str | None, "total_chunks": int}}`
      - The `start_line` and `end_line` in metadata reference ORIGINAL line numbers (from parser's line mapping)
      - After chunking, set `total_chunks` in each chunk's metadata to the total count
      - Ensure no chunk exceeds `chunk_size` tokens (using bert-base-uncased tokenizer)
      - If a single line exceeds chunk_size tokens, it becomes its own chunk (never split mid-line)
    - `chunk_file(parsed_result: dict, file_path: str, language: str) -> list[dict]` — Takes output from `parse_file`, applies `chunk_text` to the stripped text with line mapping. Returns list of chunk dicts. Returns empty list if `parsed_result` is None.
  - Write tests in `tests/test_chunker.py`:
    - Test token counting: `count_tokens("hello world", tokenizer)` returns correct count
    - Test chunk size bounds: all chunks have <= 512 tokens
    - Test overlap: consecutive chunks share at least 64 tokens of content
    - Test line preservation: chunks don't split mid-line
    - Test single-line overflow: a line with >512 tokens becomes its own chunk
    - Test empty input: returns empty list
    - Test metadata: file_path, language, start_line, end_line, chunk_index, function_name populated correctly
    - Test integration with parser output: feed `parse_file` result into `chunk_file`

  **Must NOT do**:
  - Do NOT use `tiktoken` for token counting (wrong tokenizer for nomic-embed-text)
  - Do NOT use character-based approximation for token counting
  - Do NOT add `transformers` dependency (use `tokenizers` library only)
  - Do NOT split chunks mid-line (break on line boundaries)
  - Do NOT forget to set `total_chunks` after chunking (need two-pass: count first, then set)

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Core algorithmic component with token counting, sliding window logic, and line mapping
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T3, T4, T6, T7)
  - **Parallel Group**: Wave 2
  - **Blocks**: T8 (pipeline needs chunker)
  - **Blocked By**: T2 (needs DEFAULT_CHUNK_SIZE, DEFAULT_CHUNK_OVERLAP, TOKENIZER_NAME, EMBEDDING_PREFIX from config)

  **References** (CRITICAL):

  **Pattern References**:
  - `src/config.py:DEFAULT_CHUNK_SIZE`, `DEFAULT_CHUNK_OVERLAP`, `TOKENIZER_NAME`, `EMBEDDING_PREFIX` — Constants that chunker must use
  - HuggingFace tokenizers library: `from tokenizers import Tokenizer; tokenizer = Tokenizer.from_pretrained("bert-base-uncased")` — Lightweight tokenizer without PyTorch dependency

  **API/Type References**:
  - `tokenizers.Tokenizer` — HuggingFace lightweight tokenizer
  - `tokenizer.encode(text).ids` — Returns list of token IDs; `len(...)` gives token count
  - `src/parser.py:parse_file` — Returns `{"stripped_text": str, "line_mapping": dict, ...}` that chunker consumes
  - `src/parser.py:strip_comments` — Returns `(stripped_text, line_map)` that chunker uses for line number mapping

  **Test References**:
  - `tests/test_parser.py` — Parser tests that chunker should integrate with
  - `tests/fixtures/sample.js` — Test files to chunk

  **External References**:
  - tokenizers library docs: `https://huggingface.co/docs/tokenizers/index` — `Tokenizer.from_pretrained()` API
  - nomic-embed-text model card: `https://huggingface.co/nomic-ai/nomic-embed-text-v1.5` — Confirms bert-base-uncased tokenizer and 8192 max context

  **WHY Each Reference Matters**:
  - bert-base-uncased tokenizer: nomic-embed-text uses this tokenizer; any other tokenizer will produce incorrect token counts
  - Line-based chunking: Breaking on line boundaries ensures chunks don't split mid-statement, improving embedding quality
  - Two-pass total_chunks: Metadata requires total count before chunks are finalized

  **Acceptance Criteria**:

  **If TDD (tests enabled):**
  - [ ] Test file created: tests/test_chunker.py
  - [ ] python -m pytest tests/test_chunker.py → PASS (all tests, 0 failures)

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: Chunk size stays within 512 token limit
    Tool: Bash
    Preconditions: Tokenizer loads successfully, test fixtures exist
    Steps:
      1. Run `python -m pytest tests/test_chunker.py::test_chunk_size_bounds -v`
      2. Assert all chunks have token_count <= 512
    Expected Result: No chunk exceeds 512 tokens when counted with bert-base-uncased
    Failure Indicators: Any chunk reports > 512 tokens
    Evidence: .sisyphus/evidence/task-5-chunk-size.txt

  Scenario: Overlap between consecutive chunks is at least 64 tokens
    Tool: Bash
    Preconditions: Long enough test input to produce multiple chunks
    Steps:
      1. Run `python -m pytest tests/test_chunker.py::test_chunk_overlap -v`
      2. For each pair of consecutive chunks, verify at least 64 tokens of shared content
    Expected Result: Consecutive chunks overlap by >= 64 tokens of content
    Failure Indicators: Overlap less than 64 tokens, or zero overlap
    Evidence: .sisyphus/evidence/task-5-chunk-overlap.txt

  Scenario: Metadata fields are populated correctly
    Tool: Bash
    Preconditions: Parser and chunker working together
    Steps:
      1. Run `python -m pytest tests/test_chunker.py::test_metadata_fields -v`
      2. Verify each chunk has: file_path (str), language (str), start_line (int), end_line (int), chunk_index (int), function_name (str|None), total_chunks (int)
    Expected Result: All 7 metadata fields present with correct types and values
    Failure Indicators: Missing fields, wrong types, None for required fields
    Evidence: .sisyphus/evidence/task-5-metadata.txt
  ```

  **Commit**: YES
  - Message: `feat(chunker): add token-aware sliding window chunker with tests`
  - Files: `src/chunker.py`, `tests/test_chunker.py`
  - Pre-commit: `python -m pytest tests/test_chunker.py -v`

- [x] 6. Embedder Module (Ollama + search_document Prefix) + Tests

  **What to do**:
  - Create `src/embedder.py` with:
    - `class CodeEmbedder`:
      - `__init__(self, model: str = DEFAULT_MODEL, base_url: str = DEFAULT_OLLAMA_URL)` — Initialize OllamaEmbeddings from `langchain_ollama` with `model` and `base_url`
      - `check_health(self) -> bool` — Send a test request to Ollama to verify connectivity and model availability. Return True if Ollama is reachable and model is pulled. Return False with logged error if unreachable or model missing.
      - `embed_chunks(self, chunks: list[dict], batch_size: int = 64) -> list[dict]`:
        1. For each chunk, prepend `EMBEDDING_PREFIX` (`"search_document: "`) to the text
        2. Batch embed using `OllamaEmbeddings.embed_documents()` with `batch_size` chunks per batch
        3. Add `"embedding"` field to each chunk dict with the resulting vector
        4. Return list of chunks with embeddings added
        5. Log progress: "Embedding batch X/Y..."
      - `embed_query(self, query: str) -> list[float]` — Prepend `"search_query: "` and embed a single query string using `OllamaEmbeddings.embed_query()`. This is for future search functionality but should be in the API.
  - Write tests in `tests/test_embedder.py`:
    - Test initialization with default and custom parameters
    - Test `search_document:` prefix is prepended to chunk text before embedding
    - Test `search_query:` prefix is prepended for query embedding
    - Test batch embedding with mocked OllamaEmbeddings
    - Test health check with mocked Ollama (success and failure cases)
  - **Important**: Unit tests should mock `OllamaEmbeddings` to avoid requiring a running Ollama instance. Integration tests (in T8) will use the real thing.

  **Must NOT do**:
  - Do NOT embed chunks without the `search_document:` prefix
  - Do NOT use `transformers` or `tiktoken` for anything
  - Do NOT swallow Ollama connection errors silently — fail fast with clear message
  - Do NOT embed one chunk at a time — use batch embedding (`embed_documents`)
  - Do NOT forget to mock OllamaEmbeddings in unit tests

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: External service integration (Ollama) with mocking pattern, batch processing, and prefix handling
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T3, T4, T5, T7)
  - **Parallel Group**: Wave 2
  - **Blocks**: T8 (pipeline needs embedder)
  - **Blocked By**: T2 (needs DEFAULT_MODEL, DEFAULT_OLLAMA_URL, EMBEDDING_PREFIX from config)

  **References** (CRITICAL):

  **Pattern References**:
  - `src/config.py:EMBEDDING_PREFIX`, `DEFAULT_MODEL`, `DEFAULT_OLLAMA_URL` — Constants that embedder must use

  **API/Type References**:
  - `langchain_ollama.OllamaEmbeddings` — LangChain Ollama embedding integration: `OllamaEmbeddings(model="nomic-embed-text:latest", base_url="http://localhost:11434")`
  - `OllamaEmbeddings.embed_documents(texts: list[str]) -> list[list[float]]` — Batch embedding API
  - `OllamaEmbeddings.embed_query(text: str) -> list[float]` — Single query embedding
  - `src/config.py:EMBEDDING_DIMENSIONS` — Should be 768 for nomic-embed-text

  **External References**:
  - LangChain Ollama docs: `https://python.langchain.com/docs/integrations/text_embedding/ollama/` — API and initialization patterns
  - nomic-embed-text model card: `https://huggingface.co/nomic-ai/nomic-embed-text-v1.5` — Confirms `search_document:` prefix requirement

  **WHY Each Reference Matters**:
  - `search_document:` prefix: Critical for nomic-embed-text retrieval quality; without it, embeddings will have degraded performance
  - `embed_documents` batch API: Embedding one-at-a-time against local Ollama is extremely slow; batch is essential
  - Health check: Prevents processing thousands of files only to discover Ollama is unreachable at embedding time

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: search_document prefix is prepended before embedding
    Tool: Bash
    Preconditions: Mock OllamaEmbeddings in test
    Steps:
      1. Run `python -m pytest tests/test_embedder.py::test_prefix_prepended -v`
      2. Verify that embed_documents is called with texts starting with "search_document: "
    Expected Result: Every chunk text passed to embed_documents starts with "search_document: "
    Failure Indicators: Prefix missing, prefix doubled, prefix in wrong position
    Evidence: .sisyphus/evidence/task-6-prefix-test.txt

  Scenario: Health check detects Ollama unavailability
    Tool: Bash
    Preconditions: Mock OllamaEmbeddings with connection error
    Steps:
      1. Run `python -m pytest tests/test_embedder.py::test_health_check_failure -v`
      2. Verify check_health returns False and logs error
    Expected Result: False returned, error message logged
    Failure Indicators: True returned, no error logged, exception raised
    Evidence: .sisyphus/evidence/task-6-health-check.txt

  Scenario: Batch embedding processes all chunks
    Tool: Bash
    Preconditions: Mock OllamaEmbeddings returning 768-dim vectors
    Steps:
      1. Run `python -m pytest tests/test_embedder.py::test_batch_embedding -v`
      2. Verify all input chunks get embedding field with 768-dim vectors
    Expected Result: Every chunk has embedding field with list of 768 floats
    Failure Indicators: Missing embeddings, wrong dimensions, chunks dropped
    Evidence: .sisyphus/evidence/task-6-batch-embed.txt
  ```

  **Commit**: YES
  - Message: `feat(embedder): add Ollama embedding module with prefix handling and tests`
  - Files: `src/embedder.py`, `tests/test_embedder.py`
  - Pre-commit: `python -m pytest tests/test_embedder.py -v`

- [x] 7. Store Module (Qdrant Connection + Collection + Upsert) + Tests

  **What to do**:
  - Create `src/store.py` with:
    - `class VectorStore`:
      - `__init__(self, collection_name: str = DEFAULT_COLLECTION_NAME, qdrant_url: str = DEFAULT_QDRANT_URL, embedding_dimensions: int = EMBEDDING_DIMENSIONS)` — Initialize QdrantClient with url
      - `check_health(self) -> bool` — Call `client.get_collections()` to verify Qdrant is reachable. Return True/False with logging.
      - `create_collection(self) -> None`:
        1. Check if collection already exists using `client.collection_exists(collection_name)`
        2. If not, create with `VectorParams(size=768, distance=Distance.COSINE)`
        3. Log collection creation
      - `upsert_chunks(self, chunks: list[dict], batch_size: int = 100) -> list[str]`:
        1. Convert chunk dicts to Qdrant `PointStruct` objects:
           - `id`: deterministic UUID based on `file_path + chunk_index` hash (use `uuid.uuid5`)
           - `vector`: chunk's embedding (768 floats)
           - `payload`: chunk's metadata dict (file_path, language, start_line, end_line, chunk_index, function_name, total_chunks, text_content)
        2. Use `client.upsert()` with `batch_size` points per batch
        3. Return list of point IDs
        4. Log progress: "Upserting batch X/Y..."
      - `get_point(self, point_id: str) -> dict | None` — Retrieve a point by ID for verification
  - Write tests in `tests/test_store.py`:
    - Test collection creation with correct dimensions (768) and COSINE distance
    - Test collection already exists (idempotent create_collection)
    - Test upsert with batch processing
    - Test deterministic IDs (same file_path + chunk_index → same UUID)
    - Test metadata payload contains all required fields
    - **Unit tests should use `QdrantClient(":memory:")`** to avoid requiring a running Qdrant instance

  **Must NOT do**:
  - Do NOT use `QdrantVectorStore.from_documents()` to auto-create collections (wrong dimensions)
  - Do NOT create collection without explicit `VectorParams(size=768, distance=COSINE)`
  - Do NOT use random IDs for points — must use deterministic `uuid.uuid5`
  - Do NOT skip health check for Qdrant
  - Do NOT require a running Qdrant server for unit tests — use `:memory:` mode

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: External service integration (Qdrant) with in-memory testing, batch upsert, and UUID generation
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T3, T4, T5, T6)
  - **Parallel Group**: Wave 2
  - **Blocks**: T8 (pipeline needs store)
  - **Blocked By**: T1 (needs docker-compose.yml for integration), T2 (needs DEFAULT_COLLECTION_NAME, EMBEDDING_DIMENSIONS, DEFAULT_QDRANT_URL from config)

  **References** (CRITICAL):

  **Pattern References**:
  - `src/config.py:EMBEDDING_DIMENSIONS`, `DEFAULT_COLLECTION_NAME`, `DEFAULT_QDRANT_URL` — Constants that store must use

  **API/Type References**:
  - `qdrant_client.QdrantClient(":memory:")` — In-memory Qdrant for unit testing (no server needed)
  - `qdrant_client.QdrantClient(url="http://localhost:6333")` — Production client
  - `qdrant_client.models.VectorParams(size=768, distance=Distance.COSINE)` — Collection vector configuration
  - `qdrant_client.models.PointStruct(id=..., vector=..., payload=...)` — Point structure for upsert
  - `client.collection_exists(collection_name)` — Check if collection exists
  - `client.create_collection(...)` — Create with explicit dimensions
  - `client.upsert(collection_name, points=[...], wait=True)` — Batch insert points

  **External References**:
  - Qdrant Python client docs: `https://github.com/qdrant/qdrant-client` — API patterns and collection management
  - LangChain Qdrant integration: `https://python.langchain.com/docs/integrations/vectorstores/qdrant/` — QdrantVectorStore usage

  **WHY Each Reference Matters**:
  - Pre-created collection with 768/COSINE: If dimensions are wrong, all inserts fail; auto-creation may use wrong defaults
  - In-memory Qdrant: Enables unit testing without Docker dependency
  - Deterministic UUIDs: Enables idempotent upsert — re-running on same repo won't create duplicates

  **Acceptance Criteria**:

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: Collection created with 768 dimensions and COSINE distance
    Tool: Bash
    Preconditions: In-memory Qdrant client initialized
    Steps:
      1. Run `python -m pytest tests/test_store.py::test_create_collection -v`
      2. Verify collection config has size=768 and distance=COSINE
    Expected Result: Collection exists with VectorParams(size=768, distance=COSINE)
    Failure Indicators: Wrong dimensions, wrong distance metric, collection not created
    Evidence: .sisyphus/evidence/task-7-collection-creation.txt

  Scenario: Deterministic IDs enable idempotent upsert
    Tool: Bash
    Preconditions: In-memory Qdrant client initialized
    Steps:
      1. Run `python -m pytest tests/test_store.py::test_deterministic_ids -v`
      2. Upsert same chunk twice
      3. Verify point count remains 1 (not 2)
    Expected Result: Same file_path + chunk_index produces same UUID; upsert updates rather than duplicates
    Failure Indicators: Different IDs for same input, duplicate points after two upserts
    Evidence: .sisyphus/evidence/task-7-deterministic-ids.txt

  Scenario: Metadata payload contains all required fields
    Tool: Bash
    Preconditions: In-memory Qdrant client with inserted chunks
    Steps:
      1. Run `python -m pytest tests/test_store.py::test_metadata_fields -v`
      2. Retrieve a point and verify payload has: file_path, language, start_line, end_line, chunk_index, function_name, total_chunks, text_content
    Expected Result: All 8 payload fields present with correct types
    Failure Indicators: Missing fields, wrong types, None for required fields
    Evidence: .sisyphus/evidence/task-7-metadata-fields.txt
  ```

  **Commit**: YES
  - Message: `feat(store): add Qdrant connection, collection creation, and upsert with tests`
  - Files: `src/store.py`, `tests/test_store.py`
  - Pre-commit: `python -m pytest tests/test_store.py -v`

- [x] 8. CLI + Pipeline Orchestration + Integration Tests

  **What to do**:
  - Create `src/cli.py` with argparse configuration:
    - `--repo-path` (required): Path to repository to process
    - `--qdrant-url` (default: `DEFAULT_QDRANT_URL`): Qdrant server URL
    - `--collection-name` (default: `DEFAULT_COLLECTION_NAME`): Qdrant collection name
    - `--chunk-size` (default: `DEFAULT_CHUNK_SIZE`): Token chunk size
    - `--chunk-overlap` (default: `DEFAULT_CHUNK_OVERLAP`): Token overlap size
    - `--ollama-url` (default: `DEFAULT_OLLAMA_URL`): Ollama server URL
    - `--model` (default: `DEFAULT_MODEL`): Ollama embedding model
    - `--dry-run` (flag): Run discovery, parsing, chunking without embedding/storing
    - `--verbose` (flag): Print progress info (files found, chunks created, embedding batches)
    - `--batch-size` (default: 64): Embedding batch size
  - Update `main.py` as pipeline orchestration:
    - Parse CLI arguments
    - Health check: verify Ollama is reachable and model is available (fail fast with clear error if not)
    - Health check: verify Qdrant is reachable (fail fast with clear error if not)
    - Pipeline: `discover_files → parse_file → chunk_file → embed_chunks → upsert_chunks`
    - Progress logging: file count, chunk count, embedding batch progress
    - Error handling: log warnings for parse errors, skip files that fail, continue processing
    - `--dry-run`: stop after chunking, print stats (files found, files parsed, total chunks, avg chunk size)
  - Write integration tests in `tests/test_integration.py`:
    - Test full pipeline with a small test repo (test fixtures)
    - Test `--dry-run` flag: process files without Ollama/Qdrant
    - Test `--verbose` output
    - Test health check failure (Ollama unreachable): exits with clear error
    - Test health check failure (Qdrant unreachable): exits with clear error
    - Test that chunks are inserted into Qdrant with correct metadata
    - Test that chunk text starts with `search_document:` prefix

  **Must NOT do**:
  - Do NOT add search/query CLI subcommands (scope is embedding pipeline only)
  - Do NOT add incremental/update mode (full re-process per run)
  - Do NOT add web UI or API server
  - Do NOT silently swallow Ollama/Qdrant connection errors — fail fast
  - Do NOT proceed with embedding if health checks fail

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
    - Reason: Orchestrates all modules, includes integration testing, CLI design, health checks, and error handling
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 3 (sequential, depends on all Wave 2 tasks)
  - **Blocks**: F1-F4 (verification wave)
  - **Blocked By**: T3 (scanner), T4 (parser), T5 (chunker), T6 (embedder), T7 (store)

  **References** (CRITICAL):

  **Pattern References**:
  - `src/scanner.py:discover_files` — File discovery function to call
  - `src/parser.py:parse_file` — Parse and strip comments function to call
  - `src/chunker.py:chunk_file` — Chunk text into token-based windows function to call
  - `src/embedder.py:CodeEmbedder` — Embedding class to instantiate and call
  - `src/store.py:VectorStore` — Qdrant store class to instantiate and call

  **API/Type References**:
  - `argparse.ArgumentParser` — CLI argument parsing
  - `src/config.py` — All default constants (DEFAULT_CHUNK_SIZE, DEFAULT_COLLECTION_NAME, etc.)
  - All module APIs defined in T3-T7

  **Test References**:
  - `tests/test_scanner.py`, `tests/test_parser.py`, `tests/test_chunker.py`, `tests/test_embedder.py`, `tests/test_store.py` — Unit tests that integration tests should complement
  - `tests/fixtures/` — Test JS/TS files for integration testing

  **WHY Each Reference Matters**:
  - Pipeline wiring: CLI must correctly call all modules in sequence with proper data flow
  - Health checks: Prevents wasting time processing files when downstream services are unavailable
  - Error handling: Parse errors in individual files shouldn't crash the entire pipeline

  **Acceptance Criteria**:

  **If TDD (tests enabled):**
  - [ ] Test file created: tests/test_integration.py
  - [ ] python -m pytest tests/test_integration.py → PASS

  **QA Scenarios (MANDATORY):**

  ```
  Scenario: Full pipeline end-to-end with --dry-run
    Tool: Bash
    Preconditions: Test fixtures exist, dependencies installed
    Steps:
      1. Run `python main.py --repo-path ./tests/fixtures --dry-run --verbose`
      2. Assert exit code 0
      3. Assert output shows: files discovered, files parsed, total chunks, average chunk size
      4. Assert no Qdrant/Ollama calls were made
    Expected Result: Pipeline runs through scanning/parsing/chunking, prints stats, exits 0
    Failure Indicators: Non-zero exit, missing stats, Ollama/Qdrant connection attempted
    Evidence: .sisyphus/evidence/task-8-dry-run.txt

  Scenario: Ollama unreachable fails fast with clear error
    Tool: Bash
    Preconditions: Ollama NOT running on localhost:11434
    Steps:
      1. Run `python main.py --repo-path ./tests/fixtures --ollama-url http://localhost:11434`
      2. Assert non-zero exit code
      3. Assert stderr/stdout contains "Ollama" error message
    Expected Result: Clear error message about Ollama being unreachable, exit code != 0
    Failure Indicators: Exit code 0, hangs waiting for Ollama, no error message
    Evidence: .sisyphus/evidence/task-8-ollama-unreachable.txt

  Scenario: Full pipeline with Qdrant insertion
    Tool: Bash
    Preconditions: Qdrant running (docker-compose up), Ollama running with nomic-embed-text pulled
    Steps:
      1. Run `python main.py --repo-path ./tests/fixtures --verbose`
      2. Assert exit code 0
      3. Run `curl -s http://localhost:6333/collections/code_chunks | python -m json.tool`
      4. Assert response contains vectors config with size=768, distance=Cosine
      5. Assert points_count > 0
      6. Run `curl -s http://localhost:6333/collections/code_chunks/points/scroll | python -m json.tool`
      7. Verify point payload contains: file_path, language, start_line, end_line, chunk_index, function_name, total_chunks
      8. Verify chunk text content has no comments (re-parse, check for comment nodes)
    Expected Result: All JS/TS files processed, vectors inserted, metadata complete, no comments in content
    Failure Indicators: Empty collection, wrong dimensions, missing metadata, comments in content
    Evidence: .sisyphus/evidence/task-8-full-pipeline.txt

  Scenario: CLI --help displays all options
    Tool: Bash
    Preconditions: CLI module exists
    Steps:
      1. Run `python main.py --help`
      2. Assert exit code 0
      3. Assert output contains: --repo-path, --qdrant-url, --chunk-size, --chunk-overlap, --ollama-url, --model, --dry-run, --verbose, --batch-size
    Expected Result: Help text shows all CLI options with descriptions
    Failure Indicators: Missing options, non-zero exit code
    Evidence: .sisyphus/evidence/task-8-cli-help.txt
  ```

  **Commit**: YES
  - Message: `feat(cli): add argparse CLI, pipeline orchestration, and integration tests`
  - Files: `src/cli.py`, `main.py` (updated), `tests/test_integration.py`
  - Pre-commit: `python -m pytest tests/ -v`

---

## Final Verification Wave (after ALL implementation tasks)

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.
>
> **Do NOT auto-proceed after verification. Wait for user's explicit approval before marking work complete.**
> **Never mark F1-F4 as checked before getting user's okay.**

- [x] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, curl endpoint, run command). For each "Must NOT Have": search codebase for forbidden patterns (regex comment stripping, tiktoken usage, `from_documents` auto-creation, `Language.build_library`, `transformers` import). Check evidence files exist in `.sisyphus/evidence/`. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [x] F2. **Code Quality Review** — `unspecified-high`
  Run `python -m pytest tests/ -v` + `ruff check src/`. Review all source files for: `as any`/`# type: ignore`, empty `except:`, `print()` in production code (use `logging`), commented-out code, unused imports. Check AI slop: excessive comments, over-abstraction, generic variable names (data/result/item/temp). Verify all imports resolve. Verify `requirements.txt` matches all imports.
  Output: `Tests [N pass/N fail] | Lint [PASS/FAIL] | Files [N clean/N issues] | VERDICT`

- [x] F3. **Real Manual QA** — `unspecified-high`
  Start from clean state. Run `docker-compose up -d`. Run `python main.py --repo-path <test-repo> --dry-run --verbose` — verify file discovery, parsing, chunking stats output. Run `python main.py --repo-path <test-repo>` — verify embedding and insertion. Use `curl http://localhost:6333/collections/code_chunks` to verify collection exists with 768 dimensions, COSINE distance, point count > 0. Use `curl` to retrieve a point and verify metadata fields (file_path, language, start_line, end_line, chunk_index, function_name, total_chunks). Verify chunk text starts with `search_document:`. Test failure: stop Ollama, run CLI, verify clear error message and non-zero exit code. Save all evidence to `.sisyphus/evidence/final-qa/`.
  Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

- [x] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff. Verify 1:1 — everything in spec was built, nothing beyond spec was built. Check "Must NOT do" compliance. Detect cross-task contamination. Flag unaccounted changes. Verify no search/query subcommand exists (scope is embedding pipeline only). Verify no `transformers` dependency (only `tokenizers`). Verify no regex-based comment stripping.
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

- **T1**: `feat(init): project scaffolding with Docker Compose and requirements` — requirements.txt, docker-compose.yml, main.py, src/__init__.py
- **T2**: `feat(config): add shared constants and configuration module` — src/config.py
- **T3**: `feat(scanner): add JS/TS file discovery module with tests` — src/scanner.py, tests/test_scanner.py
- **T4**: `feat(parser): add Tree-sitter parsing and comment stripping with tests` — src/parser.py, tests/test_parser.py
- **T5**: `feat(chunker): add token-aware sliding window chunker with tests` — src/chunker.py, tests/test_chunker.py
- **T6**: `feat(embedder): add Ollama embedding module with prefix handling and tests` — src/embedder.py, tests/test_embedder.py
- **T7**: `feat(store): add Qdrant connection, collection creation, and upsert with tests` — src/store.py, tests/test_store.py
- **T8**: `feat(cli): add argparse CLI, pipeline orchestration, and integration tests` — src/cli.py, main.py (updated), tests/test_integration.py

---

## Success Criteria

### Verification Commands
```bash
docker-compose up -d                            # Expected: Qdrant running on port 6333
python -m pytest tests/ -v                      # Expected: All tests pass
python main.py --help                            # Expected: Shows argparse help with all options
python main.py --repo-path ./tests/fixtures --dry-run --verbose  # Expected: Stats output, no embedding
python main.py --repo-path ./tests/fixtures      # Expected: Vectors inserted into Qdrant
curl http://localhost:6333/collections/code_chunks  # Expected: 768 dimensions, COSINE, points > 0
```

### Final Checklist
- [x] All "Must Have" present
- [x] All "Must NOT Have" absent
- [x] All tests pass