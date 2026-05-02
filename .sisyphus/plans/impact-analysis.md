# Code Vector Graph — Impact Analysis Enhancement

## TL;DR

> **Quick Summary**: Transform the code embedding service from a semantic search engine to a dependency graph engine by extracting AST metadata (imports, exports, call sites, symbols) from JS/TS/TSX files and storing it in Qdrant for impact analysis queries.
> 
> **Deliverables**:
> - Fix global state bug and bare exception handling in parser.py
> - Add AST metadata extraction (`extract_ast_metadata()`)
> - Refactor `parse_file()` to return `source_bytes` and `tree`
> - Add `strip_comments_with_tree()` to avoid double-parsing
> - Update `chunk_text()` with 11 new metadata parameters
> - Add `compute_file_hash()` to scanner and file_hash to discover_files output
> - Add payload indexes and update deterministic IDs in VectorStore
> - Update main.py pipeline to wire AST metadata through all stages
> - Update all existing tests and add new tests for each component
> 
> **Estimated Effort**: Large
> **Parallel Execution**: YES — 3 waves + final verification
> **Critical Path**: T1 (parser fixes) → T2 (AST metadata) → T3 (chunker) → T5 (pipeline) → F1-F4

---

## Context

### Original Request
Implement the 5-phase enhancement described in IMPLEMENTATION_GUIDE.md: fix critical bugs, add AST metadata extraction, enhance chunking with metadata, add file hashing and Qdrant payload indexes, update the pipeline to wire everything together.

### Interview Summary
**Key Discussions**:
- The IMPLEMENTATION_GUIDE.md is the canonical specification — follow it precisely
- The codebase uses: tree-sitter, qdrant-client, langchain-ollama, tokenizers, pytest
- Existing test infrastructure is solid (6 test files, fixtures, pytest)
- All modifications must preserve backward compatibility (additive changes)

**Research Findings**:
- parser.py has `_LAST_SOURCE_BYTES` global at line 31 — confirmed race condition bug
- `strip_comments()` calls dead-code function `_collect_function_names()` (line 157, return value discarded)
- `_generate_deterministic_id()` currently takes 2 args (file_path, chunk_index), will change to 3
- `chunk_text()` has 9 params currently, will expand to 20 with new metadata
- `discover_files()` returns 4-key dicts, will add `file_hash`
- No payload indexes exist yet in VectorStore
- `PayloadSchemaType` needs verification against installed qdrant-client version

### Metis Review
**Identified Gaps (all addressed)**:
- `strip_comments()` fate: KEEP as public function, remove global + dead code
- `_collect_function_names()`: REMOVE as dead code after global removal
- `extract_function_name()`: Make `source_bytes` a REQUIRED parameter (no default `None`)
- `tree=None` guard: MUST add to `extract_ast_metadata()` — return empty metadata
- `Property_identifier` casing: MUST verify lowercase `property_identifier` is correct for tree-sitter version
- Qdrant ID migration: Acceptable — old data orphaned, new IDs include file_hash
- Exception tuple: Keep as specified, tree-sitter errors propagate upward (acceptable)
- Double file read: Accept — scanner reads for hash, parser reads for content
- `nesting_depth`: Accept char-counting heuristic (documented limitation)

---

## Work Objectives

### Core Objective
Transform the code embedding service from "find similar text" to "trace code relationships" by extracting and storing AST-derived structural metadata alongside vector embeddings.

### Concrete Deliverables
- `src/parser.py`: Bug fixes + `extract_ast_metadata()` + `strip_comments_with_tree()` + updated `parse_file()`
- `src/chunker.py`: Updated `chunk_text()` with 11 new metadata params + nesting depth calculation
- `src/scanner.py`: `compute_file_hash()` + `file_hash` in `discover_files()` output
- `src/store.py`: `_ensure_indexes()` + updated `_generate_deterministic_id()` + updated `_chunk_to_point()`
- `main.py`: Updated pipeline passing AST metadata through all stages
- `tests/test_parser.py`: Updated + new tests for AST metadata, strip_comments_with_tree, extract_function_name
- `tests/test_chunker.py`: New tests for metadata fields in chunks
- `tests/test_scanner.py`: New test for compute_file_hash
- `tests/test_store.py`: Updated tests for deterministic IDs with file_hash + payload indexes

### Definition of Done
- [ ] All existing tests pass (`python -m pytest tests/ -v`)
- [ ] All new tests pass
- [ ] Global `_LAST_SOURCE_BYTES` completely removed from parser.py
- [ ] `extract_ast_metadata()` returns 11-key dict with bounded lists
- [ ] `parse_file()` returns dict with `source_bytes` and `tree` keys
- [ ] `chunk_text()` accepts all new params with defaults
- [ ] `discover_files()` returns `file_hash` key
- [ ] `VectorStore` creates payload indexes on collection creation
- [ ] Pipeline passes metadata from parser → chunker → store
- [ ] Dry-run mode still works

### Must Have
- Fix `_LAST_SOURCE_BYTES` global state bug (thread safety)
- Fix bare `except Exception` in `parse_file()`
- `extract_ast_metadata()` extracting imports, exports, call_sites, symbols_defined, class_name, node_type, is_exported, visibility, decorators, parent_function
- `strip_comments_with_tree()` to avoid double-parsing
- `parse_file()` returning `source_bytes` and `tree`
- `chunk_text()` with all new metadata params (with defaults)
- `compute_file_hash()` in scanner.py
- Payload indexes in VectorStore
- Updated pipeline in main.py
- All tests passing

### Must NOT Have (Guardrails)
- Do NOT remove `strip_comments()` as a public function (remove global + dead code, keep function)
- Do NOT add incremental update logic (skip-unchanged-files) — file_hash is stored but not used for skipping
- Do NOT add query/search API endpoints — Phase 5 is documentation only
- Do NOT add Python or other language AST extraction — JS/TS/TSX only
- Do NOT modify `embedder.py`, `cli.py`, or `config.py`
- Do NOT add new CLI arguments
- Do NOT handle `lexical_declaration` — only `variable_declaration` as in the guide
- Do NOT add parallel processing
- Do NOT add graph database integration
- Do NOT make `source_bytes` parameter optional with default `None` in `extract_function_name()` — it MUST be required
- Do NOT accumulate Tree objects across files — extract metadata immediately and let tree be GC'd
- Do NOT use `Property_identifier` (capital P) — verify and use `property_identifier` (lowercase p)

---

## Verification Strategy

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed. No exceptions.

### Test Decision
- **Infrastructure exists**: YES (pytest, 6 test files, fixtures directory)
- **Automated tests**: YES (Tests-after) — new tests added alongside existing ones after implementation
- **Framework**: pytest (already in requirements.txt)

### QA Policy
Every task MUST include agent-executed QA scenarios.
Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

- **Library/Module**: Use Bash (pytest) — Run test suite, check pass/fail counts, inspect coverage
- **Integration**: Use Bash (python main.py --dry-run) — Verify pipeline output with metadata

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately — bug fixes + foundation):
├── T1: Fix global state bug + bare exception in parser.py [quick]
└── T2: Add file hashing to scanner.py [quick]

Wave 2 (After Wave 1 — core new capabilities, MAX PARALLEL):
├── T3: Add AST metadata extraction to parser.py [deep]
├── T4: Add strip_comments_with_tree + update parse_file to return tree [deep]
└── T5: Add payload indexes + update store.py [unspecified-high]

Wave 3 (After Wave 2 — integration layers):
├── T6: Update chunker with impact metadata parameters [unspecified-high]
└── T7: Update main.py pipeline to wire metadata through [deep]

Wave 4 (After Wave 3 — tests for integration):
├── T8: Update existing tests + add new tests for all components [unspecified-high]
└── T9: Integration verification — dry-run pipeline with test repo [unspecified-high]

Wave FINAL (After ALL tasks — 4 parallel reviews):
├── F1: Plan compliance audit (oracle)
├── F2: Code quality review (unspecified-high)
├── F3: Real manual QA (unspecified-high)
└── F4: Scope fidelity check (deep)
-> Present results -> Get explicit user okay

Critical Path: T1 → T3 → T6 → T7 → T8 → F1-F4
Parallel Speedup: ~40% faster than sequential
Max Concurrent: 3 (Waves 2)
```

### Dependency Matrix

| Task | Depends On | Blocks |
|------|------------|--------|
| T1 | — | T3, T4 |
| T2 | — | T7 |
| T3 | T1 | T6, T7 |
| T4 | T1 | T6, T7 |
| T5 | — | T7 |
| T6 | T3, T4 | T7 |
| T7 | T2, T3, T4, T5, T6 | T8 |
| T8 | T7 | T9 |
| T9 | T8 | F1-F4 |

### Agent Dispatch Summary

- **Wave 1**: 2 tasks — T1 → `quick`, T2 → `quick`
- **Wave 2**: 3 tasks — T3 → `deep`, T4 → `deep`, T5 → `unspecified-high`
- **Wave 3**: 2 tasks — T6 → `unspecified-high`, T7 → `deep`
- **Wave 4**: 2 tasks — T8 → `unspecified-high`, T9 → `unspecified-high`
- **FINAL**: 4 tasks — F1 → `oracle`, F2 → `unspecified-high`, F3 → `unspecified-high`, F4 → `deep`

---

## TODOs

- [x] 1. Fix global state bug and bare exception handling in parser.py

  **What to do**:
  - Remove the global `_LAST_SOURCE_BYTES` variable at line 31 of `src/parser.py`
  - Remove the `global _LAST_SOURCE_BYTES` statement and `_LAST_SOURCE_BYTES = source_bytes` assignment in `strip_comments()` (lines 155-156)
  - Remove the dead-code call to `_collect_function_names(root, source_bytes)` at line 157 in `strip_comments()`
  - Remove the entire `_collect_function_names()` function (lines 72-106) since it was only called from `strip_comments()` and its result was never used
  - Update `extract_function_name()` signature to add `source_bytes: bytes` as a REQUIRED third parameter (no default value)
  - Remove `global _LAST_SOURCE_BYTES` at line 168 and `if _LAST_SOURCE_BYTES is None: return None` at lines 169-170
  - Change `src = _LAST_SOURCE_BYTES` at line 171 to `src = source_bytes`
  - Verify `property_identifier` (lowercase) is the correct tree-sitter node type for the installed version by checking tree-sitter-javascript grammar. Update line 92 if needed.
  - Change `except Exception as e:` at line 222 in `parse_file()` to `except (ValueError, RuntimeError, OSError, UnicodeDecodeError) as e:`
  - Update `test_parser.py`: Remove `parser._LAST_SOURCE_BYTES = src_bytes` at line 85; update `extract_function_name()` call at line 102 to pass `source_bytes` as third argument
  - Run `python -m pytest tests/test_parser.py -v` and verify all tests pass

  **Must NOT do**:
  - Do NOT remove `strip_comments()` as a function — keep it, just remove the global and dead code
  - Do NOT make `source_bytes` parameter optional with `None` default — it MUST be required
  - Do NOT modify the tree-sitter version or grammar loading logic
  - Do NOT change `strip_comments()` signature — only remove internal global-setting lines

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []
  - Reason: Targeted bug fixes with clear, specific changes

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with T2)
  - **Blocks**: T3, T4
  - **Blocked By**: None

  **References**:
  - `src/parser.py:31` — `_LAST_SOURCE_BYTES` global variable declaration (REMOVE)
  - `src/parser.py:72-106` — `_collect_function_names()` dead-code function (REMOVE entirely)
  - `src/parser.py:109-159` — `strip_comments()` function (remove lines 155-157 only)
  - `src/parser.py:162-205` — `extract_function_name()` function (update signature, remove global)
  - `src/parser.py:208-234` — `parse_file()` function (fix exception handling at line 222)
  - `tests/test_parser.py:73-103` — `test_function_name_extraction` test (update to pass source_bytes)
  - IMPLEMENTATION_GUIDE.md Phase 0 tasks 1-2 — exact specifications for the changes

  **WHY Each Reference Matters**:
  - `src/parser.py:31` — This is the global variable causing thread-safety issues
  - `src/parser.py:72-106` — Dead code that becomes completely unreachable after global removal
  - `src/parser.py:155-157` — The global assignment and dead function call that must be removed
  - `src/parser.py:168-171` — The global read that must be replaced with parameter
  - `src/parser.py:222` — The bare exception handler that catches too broadly

  **Acceptance Criteria**:
  - [ ] No reference to `_LAST_SOURCE_BYTES` exists anywhere in codebase (`grep -rn "_LAST_SOURCE_BYTES" src/` returns nothing)
  - [ ] `_collect_function_names` function is completely removed (`grep -rn "_collect_function_names" src/` returns nothing)
  - [ ] `extract_function_name` signature is `(tree, node_start_byte: int, node_end_byte: int, source_bytes: bytes) -> Optional[str]`
  - [ ] `strip_comments()` still works and strips comments correctly
  - [ ] `parse_file()` catches only `(ValueError, RuntimeError, OSError, UnicodeDecodeError)`
  - [ ] `test_function_name_extraction` passes source_bytes parameter

  **QA Scenarios**:

  ```
  Scenario: Parser global state removed and function extraction still works
    Tool: Bash
    Preconditions: Code changes are saved
    Steps:
      1. Run: grep -rn "_LAST_SOURCE_BYTES" src/ — expect empty output
      2. Run: grep -rn "_collect_function_names" src/ — expect empty output
      3. Run: python -m pytest tests/test_parser.py -v — expect all tests pass
      4. Run: python -c "from src.parser import extract_function_name; import inspect; sig = inspect.signature(extract_function_name); print(list(sig.parameters.keys()))" — expect ['tree', 'node_start_byte', 'node_end_byte', 'source_bytes']
    Expected Result: No global variables remain, all tests pass, function signature has source_bytes as required param
    Failure Indicators: grep finds _LAST_SOURCE_BYTES references, tests fail, signature doesn't include source_bytes
    Evidence: .sisyphus/evidence/task-1-global-fix.txt

  Scenario: Exception handling is specific, not broad
    Tool: Bash
    Preconditions: Code changes are saved
    Steps:
      1. Run: grep -A2 "except (" src/parser.py — expect to see specific exception tuple
      2. Run: grep -n "except Exception" src/parser.py — expect no matches (or only in expected locations)
      3. Run: python -m pytest tests/test_parser.py -v — expect all pass
    Expected Result: No bare except Exception in parse_file, specific exceptions caught
    Failure Indicators: Bare except found, tests fail
    Evidence: .sisyphus/evidence/task-1-exception-fix.txt
  ```

  **Commit**: YES
  - Message: `fix(parser): remove global state and fix bare exception handling`
  - Files: `src/parser.py`, `tests/test_parser.py`
  - Pre-commit: `python -m pytest tests/test_parser.py -v`

- [x] 2. Add file hashing to scanner.py

  **What to do**:
  - Add `import hashlib` at the top of `src/scanner.py`
  - Add `compute_file_hash(file_path: Path) -> str` function that computes SHA256 of file contents, truncated to 16 hex chars
  - Call `compute_file_hash()` inside `discover_files()` loop for each valid file, add `"file_hash": file_hash` key to the returned dict
  - Add a test for `compute_file_hash()` in `tests/test_scanner.py`:
    - Create a temp file, write content, verify hash is 16-char hex string
    - Test with unreadable file returns empty string
    - Test `discover_files()` output includes `file_hash` key
  - Run `python -m pytest tests/test_scanner.py -v` and verify all tests pass

  **Must NOT do**:
  - Do NOT add incremental update logic (skip-unchanged-files) — file_hash is stored but not used for skipping
  - Do NOT modify `SUPPORTED_EXTENSIONS` or `SKIP_DIRS`
  - Do NOT change the existing keys in `discover_files()` output dict

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []
  - Reason: Small, self-contained addition to one file

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with T1)
  - **Blocks**: T7
  - **Blocked By**: None

  **References**:
  - `src/scanner.py:1-74` — Current scanner with `discover_files()` function
  - `src/scanner.py:31-74` — `discover_files()` function where file_hash must be added
  - `tests/test_scanner.py` — Existing scanner tests
  - `src/config.py:1-10` — `SUPPORTED_EXTENSIONS` dict (for understanding file type mappings)
  - IMPLEMENTATION_GUIDE.md Phase 3, task 6 — Exact specification for compute_file_hash

  **WHY Each Reference Matters**:
  - `src/scanner.py` — The file being modified
  - `discover_files()` at lines 31-74 — Where to add file_hash computation and dict key
  - `tests/test_scanner.py` — Test patterns to follow
  - `src/config.py` — Understanding supported extensions

  **Acceptance Criteria**:
  - [ ] `compute_file_hash()` returns 16-char hex string for valid files
  - [ ] `compute_file_hash()` returns empty string for unreadable files
  - [ ] `discover_files()` returns dict with `file_hash` key
  - [ ] Existing scanner tests still pass
  - [ ] New test for compute_file_hash passes

  **QA Scenarios**:

  ```
  Scenario: File hashing works correctly
    Tool: Bash
    Preconditions: Code changes are saved
    Steps:
      1. Run: python -c "from src.scanner import compute_file_hash; from pathlib import Path; import tempfile, os; f = tempfile.NamedTemporaryFile(delete=False, suffix='.js'); f.write(b'test content'); f.close(); h = compute_file_hash(Path(f.name)); print(f'hash={h}, len={len(h)}'); os.unlink(f.name)" — expect 16-char hex string
      2. Run: python -c "from src.scanner import compute_file_hash; from pathlib import Path; h = compute_file_hash(Path('/nonexistent/file.js')); print(f'result={repr(h)}')" — expect empty string ''
      3. Run: python -m pytest tests/test_scanner.py -v — expect all tests pass
    Expected Result: Hash is 16-char hex for valid files, empty string for invalid, all tests pass
    Failure Indicators: Hash wrong length, non-empty for missing files, tests fail
    Evidence: .sisyphus/evidence/task-2-file-hashing.txt

  Scenario: discover_files includes file_hash in output
    Tool: Bash
    Preconditions: Code changes are saved, tmp_test_sources directory exists
    Steps:
      1. Run: python -c "from src.scanner import discover_files; files = discover_files('tmp_test_sources'); print(files[0].keys() if files else 'no files')" — expect dict_keys containing 'file_hash'
    Expected Result: file_hash key present in discover_files output
    Failure Indicators: file_hash key missing
    Evidence: .sisyphus/evidence/task-2-discover-hash.txt
  ```

  **Commit**: YES
  - Message: `feat(scanner): add file hashing for change detection`
  - Files: `src/scanner.py`, `tests/test_scanner.py`
  - Pre-commit: `python -m pytest tests/test_scanner.py -v`

- [x] 3. Add AST metadata extraction function to parser.py

  **What to do**:
  - Add `extract_ast_metadata(tree, source_bytes: bytes) -> dict` function after `extract_function_name()` in `src/parser.py`
  - The function must return a dict with these keys: `imports` (list), `exports` (list), `call_sites` (list), `symbols_defined` (list), `class_name` (str|None), `node_type` (str|None), `is_exported` (bool), `visibility` (str), `decorators` (list), `parent_function` (str|None)
  - Add a `None` guard at the top: if `tree` is `None`, return a default metadata dict with all empty/None values
  - Implement the `walk_node` recursive function with these handlers:
    - `export_statement`: mark children as exported, recurse
    - `export_specifier` / `export_clause`: extract export names
    - `class_declaration` / `class_expression`: extract class name, walk class_body
    - `function_declaration`, `function`, `method_definition`, `arrow_function`, `async_function_declaration`, `generator_function`, `async_arrow_function`: extract function name, walk body
    - `call_expression`: extract call name (identifier or member_expression)
    - `import_statement` / `import_clause`: extract source and imported names
    - `variable_declaration`: extract variable names (for exported vars)
  - After walking, deduplicate lists while preserving order: `list(dict.fromkeys(...))`
  - Bound list sizes: imports ≤50, exports ≤50, call_sites ≤100, symbols_defined ≤50, decorators ≤20
  - Add a test in `tests/test_parser.py` for `extract_ast_metadata`:
    - Test with JS source containing: import, export, function, class, call expression
    - Test with empty/minimal source string
    - Test with `tree=None` returns default empty metadata
  - Run `python -m pytest tests/test_parser.py -v` and verify all tests pass

  **Must NOT do**:
  - Do NOT add Python/other language AST extraction — JS/TS/TSX node types only
  - Do NOT handle `lexical_declaration` — only `variable_declaration` as in the guide
  - Do NOT modify `extract_function_name()` (that was done in T1)
  - Do NOT add this function to `__all__` or any exports list unless it already exists
  - Do NOT make `tree` parameter optional — always require the tree argument

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
  - Reason: Complex AST walking logic with many node type handlers, careful deduplication and bounding

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T4, T5)
  - **Parallel Group**: Wave 2
  - **Blocks**: T6, T7
  - **Blocked By**: T1

  **References**:
  - `src/parser.py:162-205` — `extract_function_name()` function (add new function after this)
  - `src/parser.py:27` — `COMMENT_NODE_TYPES` tuple (for understanding node type patterns)
  - `IMPLEMENTATION_GUIDE.md:158-371` — Complete specification of `extract_ast_metadata` with all node handlers
  - `IMPLEMENTATION_GUIDE.md:188-197` — FUNCTION_NODE_TYPES and CLASS_NODE_TYPES definitions
  - `tests/test_parser.py` — Existing parser tests (add new tests here)
  - `tests/fixtures/sample.js` — JS test fixture file

  **WHY Each Reference Matters**:
  - `src/parser.py:162-205` — Location where new function should be inserted
  - `IMPLEMENTATION_GUIDE.md:158-371` — The complete implementation specification with all AST node handlers
  - `IMPLEMENTATION_GUIDE.md:188-197` — The exact set of node types to handle (FUNCTION_NODE_TYPES, CLASS_NODE_TYPES)
  - `tests/test_parser.py` — Test patterns to follow (using `_write_temp` helper, etc.)

  **Acceptance Criteria**:
  - [ ] `extract_ast_metadata(tree, source_bytes)` returns dict with all 11 keys
  - [ ] Returns correct metadata for JS code with: imports, exports, functions, classes, call expressions
  - [ ] Returns all-empty/None metadata for `tree=None`
  - [ ] List sizes are bounded (imports ≤50, exports ≤50, call_sites ≤100, symbols_defined ≤50, decorators ≤20)
  - [ ] Duplicates are removed while preserving order
  - [ ] All existing parser tests still pass

  **QA Scenarios**:

  ```
  Scenario: AST metadata extraction produces correct results for JS source
    Tool: Bash
    Preconditions: Code changes are saved
    Steps:
      1. Write a test JS file to tmp_test_sources with: import statement, export statement, function declaration, class declaration, call expression
      2. Run: python -c "
from src.parser import get_parser, extract_ast_metadata
import tempfile, os
code = b'''import React from 'react';
export function hello() { console.log('hi'); }
export class App { render() { return helper(); } }
'''
tree = get_parser('javascript').parse(code)
meta = extract_ast_metadata(tree, code)
print('imports:', meta['imports'])
print('exports:', meta['exports'])
print('call_sites:', meta['call_sites'])
print('symbols_defined:', meta['symbols_defined'])
print('node_type:', meta['node_type'])
"
      3. Verify imports contains 'react', exports contains 'hello', call_sites contains 'console.log' and 'helper'
    Expected Result: Metadata dict contains expected JS structural elements
    Failure Indicators: Missing imports/exports, empty lists, wrong node types
    Evidence: .sisyphus/evidence/task-3-ast-metadata.txt

  Scenario: extract_ast_metadata handles None tree gracefully
    Tool: Bash
    Preconditions: Code changes are saved
    Steps:
      1. Run: python -c "from src.parser import extract_ast_metadata; result = extract_ast_metadata(None, b''); print(result)"
      2. Verify result is a dict with all 11 keys, all lists empty, string values are None or 'unknown'
    Expected Result: Default metadata dict with all-empty/None values, no crash
    Failure Indicators: Crashes, missing keys, non-empty values
    Evidence: .sisyphus/evidence/task-3-none-tree.txt

  Scenario: List bounding and deduplication
    Tool: Bash
    Preconditions: Code changes are saved
    Steps:
      1. Create a JS string with 60+ duplicate imports
      2. Run extract_ast_metadata on it
      3. Verify imports list has at most 50 items and no duplicates
    Expected Result: Lists bounded to max sizes, no duplicates
    Failure Indicators: Lists exceed bounds, duplicates present
    Evidence: .sisyphus/evidence/task-3-bounding.txt
  ```

  **Commit**: YES
  - Message: `feat(parser): add AST metadata extraction for impact analysis`
  - Files: `src/parser.py`, `tests/test_parser.py`
  - Pre-commit: `python -m pytest tests/test_parser.py -v`

- [x] 4. Add strip_comments_with_tree and update parse_file to return tree

  **What to do**:
  - Add `strip_comments_with_tree(source_bytes: bytes, grammar_name: str, tree) -> Tuple[str, Dict[int, int]]` function to `src/parser.py`
  - This function takes a pre-parsed tree instead of creating one internally
  - The logic is identical to `strip_comments()` but uses the provided tree instead of calling `get_parser()` and `parser.parse()`
  - Build the line_map the same way as `strip_comments()`
  - Update `parse_file()` to:
    - Call `get_parser(grammar_name)` and `parser.parse(data)` to get the tree ONCE
    - Call `strip_comments_with_tree(data, grammar_name, tree)` instead of `strip_comments(data, grammar_name)`
    - Add `"source_bytes": data` and `"tree": tree` to the return dict
    - Catch `(ValueError, RuntimeError, OSError, UnicodeDecodeError)` instead of `Exception`
  - Keep `strip_comments()` as a public function (just without the global and dead code, already cleaned in T1)
  - Add a test in `tests/test_parser.py` verifying `strip_comments_with_tree()` produces output identical to `strip_comments()` for the same input
  - Add a test verifying `parse_file()` returns dict with `source_bytes` and `tree` keys
  - Run `python -m pytest tests/test_parser.py -v` and verify all tests pass

  **Must NOT do**:
  - Do NOT remove `strip_comments()` — keep it as a public function
  - Do NOT call both `strip_comments()` and `strip_comments_with_tree()` — use only the latter in `parse_file()`
  - Do NOT store Tree objects across files in the pipeline — extract metadata from tree immediately
  - Do NOT modify `strip_comments()` function signature

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
  - Reason: Tight coupling with parser internals, careful refactoring to avoid double-parsing

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T3, T5)
  - **Parallel Group**: Wave 2
  - **Blocks**: T6, T7
  - **Blocked By**: T1

  **References**:
  - `src/parser.py:109-159` — Current `strip_comments()` function (reference for new function)
  - `src/parser.py:208-234` — Current `parse_file()` function (update to use strip_comments_with_tree)
  - `IMPLEMENTATION_GUIDE.md:383-465` — Complete specification for strip_comments_with_tree and updated parse_file
  - `IMPLEMENTATION_GUIDE.md:49-73` — parse_file updated return dict with source_bytes and tree
  - `tests/test_parser.py` — Existing tests (add new tests here)

  **WHY Each Reference Matters**:
  - `src/parser.py:109-159` — The logic to replicate in strip_comments_with_tree (same comment-rich removal, different parse strategy)
  - `src/parser.py:208-234` — The function being refactored to avoid double-parsing
  - `IMPLEMENTATION_GUIDE.md:383-465` — Exact code specification for both new functions
  - `IMPLEMENTATION_GUIDE.md:49-73` — Return dict specification (adding source_bytes, tree)

  **Acceptance Criteria**:
  - [ ] `strip_comments_with_tree()` exists and produces identical output to `strip_comments()` for same input
  - [ ] `parse_file()` calls `strip_comments_with_tree()` instead of `strip_comments()`
  - [ ] `parse_file()` returns dict with 6 keys: `stripped_text`, `original_line_count`, `stripped_line_count`, `line_mapping`, `source_bytes`, `tree`
  - [ ] `parse_file()` parses the source exactly once (no double-parsing)
  - [ ] `parse_file()` returns `None` on file read/parse errors
  - [ ] `strip_comments()` still exists as a public function
  - [ ] All existing parser tests pass

  **QA Scenarios**:

  ```
  Scenario: strip_comments_with_tree produces identical output to strip_comments
    Tool: Bash
    Preconditions: Code changes are saved
    Steps:
      1. Run: python -c "
from src.parser import get_parser, strip_comments, strip_comments_with_tree
code = b'''// comment
function hello() {
  /* block comment */
  return 42;
}
'''
tree = get_parser('javascript').parse(code)
result1_text, result1_map = strip_comments(code, 'javascript')
result2_text, result2_map = strip_comments_with_tree(code, 'javascript', tree)
print('texts_match:', result1_text == result2_text)
print('maps_match:', result1_map == result2_map)
"
      2. Verify both produce identical stripped text and line maps
    Expected Result: texts_match=True, maps_match=True
    Failure Indicators: Mismatched output between the two functions
    Evidence: .sisyphus/evidence/task-4-strip-comments-parity.txt

  Scenario: parse_file returns source_bytes and tree
    Tool: Bash
    Preconditions: Code changes are saved, tmp_test_sources/sample.js exists
    Steps:
      1. Run: python -c "
from src.parser import parse_file
result = parse_file('tmp_test_sources/sample.js', 'javascript')
print('keys:', sorted(result.keys()) if result else 'None')
print('has_source_bytes:', 'source_bytes' in result if result else False)
print('has_tree:', 'tree' in result if result else False)
print('source_bytes_type:', type(result.get('source_bytes')).__name__ if result else 'N/A')
"
      2. Verify result dict contains 'source_bytes' and 'tree' keys
    Expected Result: Dict contains all 6 keys including source_bytes and tree
    Failure Indicators: Missing keys, None values for source_bytes or tree
    Evidence: .sisyphus/evidence/task-4-parse-file-tree.txt

  Scenario: parse_file returns None on errors
    Tool: Bash
    Preconditions: Code changes are saved
    Steps:
      1. Run: python -c "from src.parser import parse_file; result = parse_file('/nonexistent/file.js', 'javascript'); print(result)"
      2. Verify result is None
    Expected Result: None returned for non-existent files
    Failure Indicators: Exception raised, non-None return
    Evidence: .sisyphus/evidence/task-4-parse-errors.txt
  ```

  **Commit**: YES
  - Message: `feat(parser): add strip_comments_with_tree and update parse_file to return tree`
  - Files: `src/parser.py`, `tests/test_parser.py`
  - Pre-commit: `python -m pytest tests/test_parser.py -v`

- [x] 5. Add payload indexes and update store.py with file_hash support

  **What to do**:
  - Add `from qdrant_client.models import PayloadSchemaType` import to `src/store.py`
  - Add `_ensure_indexes(self) -> None` method to `VectorStore` class that creates 11 payload indexes:
    - `(file_path, PayloadSchemaType.KEYWORD)`, `(language, PayloadSchemaType.KEYWORD)`,
    - `(node_type, PayloadSchemaType.KEYWORD)`, `(class_name, PayloadSchemaType.KEYWORD)`,
    - `(function_name, PayloadSchemaType.KEYWORD)`, `(imports, PayloadSchemaType.KEYWORD)`,
    - `(exports, PayloadSchemaType.KEYWORD)`, `(call_sites, PayloadSchemaType.KEYWORD)`,
    - `(is_exported, PayloadSchemaType.BOOL)`, `(visibility, PayloadSchemaType.KEYWORD)`,
    - `(file_hash, PayloadSchemaType.KEYWORD)`
  - Call `_ensure_indexes()` in `create_collection()` after collection creation (and when collection already exists)
  - Update `_generate_deterministic_id()` signature to accept `file_hash: str = ""` as 3rd parameter, include it in the UUID5 name string
  - Update `_chunk_to_point()` to include all new metadata fields in the payload dict (node_type, class_name, parent_function, imports, exports, symbols_defined, call_sites, is_exported, visibility, nesting_depth, token_count, decorators, file_hash)
  - Update `create_collection()` to call `_ensure_indexes()` after creation and when collection already exists
  - Add tests in `tests/test_store.py`:
    - Test `_ensure_indexes()` creates indexes without error on in-memory Qdrant
    - Test `_generate_deterministic_id()` with 3 args (file_path, chunk_index, file_hash) — same hash produces same ID, different hash produces different ID
    - Test `_chunk_to_point()` includes all new metadata fields in payload
    - Update `sample_chunks` fixture and `TestMetadataPayload.test_payload_has_all_required_fields` to include new fields
  - Run `python -m pytest tests/test_store.py -v` and verify all tests pass

  **Must NOT do**:
  - Do NOT modify `embedder.py`
  - Do NOT modify `config.py`
  - Do NOT add query/search methods to VectorStore
  - Do NOT add migration logic for existing Qdrant data
  - Do NOT change the collection name or vector configuration

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - Reason: Multiple coordinated changes to store class — indexes, ID generation, payload structure

  **Parallelization**:
  - **Can Run In Parallel**: YES (with T3, T4)
  - **Parallel Group**: Wave 2
  - **Blocks**: T7
  - **Blocked By**: None

  **References**:
  - `src/store.py:1-200` — Current VectorStore class (all methods)
  - `src/store.py:84-97` — Current `_generate_deterministic_id()` (2 args, needs 3rd arg)
  - `src/store.py:99-138` — Current `_chunk_to_point()` (needs new payload fields)
  - `src/store.py:61-82` — Current `create_collection()` (needs _ensure_indexes call)
  - `IMPLEMENTATION_GUIDE.md:739-924` — Complete specification for updated VectorStore
  - `tests/test_store.py` — Existing store tests (update fixtures, add new tests)

  **WHY Each Reference Matters**:
  - `src/store.py:84-97` — Must add file_hash parameter to ID generation
  - `src/store.py:99-138` — Must add all new payload fields to PointStruct
  - `src/store.py:61-82` — Must call _ensure_indexes after collection creation
  - `IMPLEMENTATION_GUIDE.md:739-924` — Exact specification for indexes, ID generation, and payload
  - `tests/test_store.py` — Test patterns and fixtures to update

  **Acceptance Criteria**:
  - [ ] `_ensure_indexes()` creates all 11 payload indexes without error
  - [ ] `_ensure_indexes()` handles already-existing indexes gracefully (no crash)
  - [ ] `create_collection()` calls `_ensure_indexes()` after creating collection
  - [ ] `create_collection()` calls `_ensure_indexes()` when collection already exists
  - [ ] `_generate_deterministic_id()` accepts 3 args and includes file_hash
  - [ ] Same file_path + chunk_index + file_hash produces same ID
  - [ ] Different file_hash produces different ID (same file_path + chunk_index)
  - [ ] `_chunk_to_point()` payload includes all 13 new metadata fields
  - [ ] All existing store tests pass with updated fixtures

  **QA Scenarios**:

  ```
  Scenario: Payload indexes are created successfully
    Tool: Bash
    Preconditions: Code changes are saved
    Steps:
      1. Run: python -c "
from src.store import VectorStore
store = VectorStore(collection_name='test_idx', qdrant_url=':memory:')
store.create_collection()
# Verify no errors
print('Indexes created successfully')
"
      2. Run: python -m pytest tests/test_store.py -v - expect all tests pass
    Expected Result: Collection creation succeeds, indexes created, all tests pass
    Failure Indicators: Exception on index creation, test failures
    Evidence: .sisyphus/evidence/task-5-indexes.txt

  Scenario: Deterministic IDs with file_hash
    Tool: Bash
    Preconditions: Code changes are saved
    Steps:
      1. Run: python -c "
from src.store import VectorStore
store = VectorStore(collection_name='test_ids', qdrant_url=':memory:')
id1 = store._generate_deterministic_id('/path/file.js', 0, 'abc123')
id2 = store._generate_deterministic_id('/path/file.js', 0, 'abc123')
id3 = store._generate_deterministic_id('/path/file.js', 0, 'different_hash')
print(f'same inputs: {id1 == id2}')
print(f'different hash: {id1 != id3}')
"
      2. Verify same inputs produce same ID, different hash produces different ID
    Expected Result: same inputs: True, different hash: True
    Failure Indicators: IDs don't match or don't differ as expected
    Evidence: .sisyphus/evidence/task-5-deterministic-ids.txt

  Scenario: _chunk_to_point includes all new metadata fields
    Tool: Bash
    Preconditions: Code changes are saved
    Steps:
      1. Run: python -m pytest tests/test_store.py::TestMetadataPayload -v
      2. Verify test verifies all new fields are present in payload
    Expected Result: All metadata fields present in Qdrant payload
    Failure Indicators: Missing fields, test failures
    Evidence: .sisyphus/evidence/task-5-metadata-payload.txt
  ```

  **Commit**: YES
  - Message: `feat(store): add payload indexes and update deterministic IDs with file_hash`
  - Files: `src/store.py`, `tests/test_store.py`
  - Pre-commit: `python -m pytest tests/test_store.py -v`

- [x] 6. Update chunker with impact metadata parameters

  **What to do**:
  - Add 11 new keyword parameters to `chunk_text()` in `src/chunker.py`:
    - `node_type: Optional[str] = None`
    - `class_name: Optional[str] = None`
    - `parent_function: Optional[str] = None`
    - `imports: Optional[list] = None`
    - `exports: Optional[list] = None`
    - `symbols_defined: Optional[list] = None`
    - `call_sites: Optional[list] = None`
    - `is_exported: bool = False`
    - `visibility: str = "unknown"`
    - `decorators: Optional[list] = None`
    - `file_hash: str = ""`
  - Add nesting depth calculation before the chunking loop:
    ```
    nesting_depth = 0
    for line in lines:
        open_count = line.count('{') + line.count('(') + line.count('[')
        close_count = line.count('}') + line.count(')') + line.count(']')
        line_depth = open_count - close_count
        if line_depth > nesting_depth:
            nesting_depth = line_depth
    ```
  - Add `token_count` calculation for each chunk using `count_tokens(chunk_text_segment, tokenizer)`
  - Add all new fields to each chunk's `metadata` dict (in all 3 places: single-line overflow, normal chunk, final chunk)
  - Use defaults: `imports or []`, `exports or []`, `symbols_defined or []`, `call_sites or []`, `decorators or []`
  - Keep existing metadata fields unchanged (file_path, language, start_line, end_line, chunk_index, function_name, total_chunks)
  - Also update `chunk_file()` helper function to pass through new metadata params (or document why it's not updated)
  - Run `python -m pytest tests/test_chunker.py -v` and verify all existing tests pass
  - Add a test for `chunk_text()` with new metadata params verifying fields appear in output
  - Add a test verifying `chunk_text()` still works without new params (backward compatibility)

  **Must NOT do**:
  - Do NOT make new params required — they MUST have defaults for backward compatibility
  - Do NOT change existing metadata field names or types
  - Do NOT remove `chunk_file()` function
  - Do NOT change the chunking algorithm (token-based sliding window)
  - Do NOT add AST-based nesting depth calculation — use the char-counting heuristic as specified

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - Reason: Many param additions across multiple chunk creation sites, careful to maintain backward compatibility

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 3 (after T3 and T4)
  - **Blocks**: T7
  - **Blocked By**: T3, T4

  **References**:
  - `src/chunker.py:58-189` — Current `chunk_text()` function (add params and metadata fields)
  - `src/chunker.py:192-213` — `chunk_file()` helper (consider updating)
  - `src/chunker.py:47-51` — `count_tokens()` function (use for token_count in metadata)
  - `IMPLEMENTATION_GUIDE.md:478-668` — Complete specification for updated chunk_text with all new params and metadata
  - `IMPLEMENTATION_GUIDE.md:514-521` — Nesting depth calculation logic
  - `tests/test_chunker.py` — Existing chunker tests

  **WHY Each Reference Matters**:
  - `src/chunker.py:58-189` — The function being modified — must add params and update metadata dict in 3 places (lines ~106-118, ~132-142, ~167-178)
  - `src/chunker.py:47-51` — `count_tokens()` used for token_count in metadata
  - `IMPLEMENTATION_GUIDE.md:514-521` — Exact nesting depth calculation algorithm
  - `IMPLEMENTATION_GUIDE.md:478-668` — Complete implementation spec showing all locations where metadata must be added

  **Acceptance Criteria**:
  - [ ] `chunk_text()` accepts all 11 new keyword parameters with defaults
  - [ ] All 3 chunk creation sites include all new metadata fields
  - [ ] Existing `chunk_text()` calls without new params still work
  - [ ] `nesting_depth` is calculated and included in chunk metadata
  - [ ] `token_count` is calculated for each chunk and included in metadata
  - [ ] All existing chunker tests pass
  - [ ] New test verifies metadata fields are present in output

  **QA Scenarios**:

  ```
  Scenario: chunk_text with full metadata params
    Tool: Bash
    Preconditions: Code changes are saved
    Steps:
      1. Run: python -c "
from src.chunker import chunk_text
chunks = chunk_text(
    'function hello() { return 1; }',
    start_line=1, end_line=1,
    file_path='/test.js', language='javascript',
    node_type='function', class_name='MyClass',
    imports=['react'], exports=['hello'],
    symbols_defined=['hello'], call_sites=['return'],
    is_exported=True, visibility='public',
    decorators=['@test'], file_hash='abc123'
)
c = chunks[0]
m = c['metadata']
print('node_type:', m['node_type'])
print('class_name:', m['class_name'])
print('imports:', m['imports'])
print('exports:', m['exports'])
print('is_exported:', m['is_exported'])
print('file_hash:', m['file_hash'])
"
      2. Verify all new fields appear with correct values
    Expected Result: All metadata fields present with correct values
    Failure Indicators: Missing fields, wrong values, TypeError on call
    Evidence: .sisyphus/evidence/task-6-chunk-metadata.txt

  Scenario: backward compatibility — chunk_text without new params
    Tool: Bash
    Preconditions: Code changes are saved
    Steps:
      1. Run: python -c "
from src.chunker import chunk_text
chunks = chunk_text('function hello() { return 1; }', start_line=1, end_line=1, file_path='/test.js', language='javascript')
print('chunks:', len(chunks))
print('has_metadata:', 'metadata' in chunks[0])
print('node_type:', chunks[0]['metadata'].get('node_type'))
print('imports:', chunks[0]['metadata'].get('imports'))
"
      2. Verify chunks still created, metadata dict exists, new fields have defaults
    Expected Result: Chunks created, metadata has default values for new fields
    Failure Indicators: TypeError, missing fields, chunks not created
    Evidence: .sisyphus/evidence/task-6-backward-compat.txt
  ```

  **Commit**: YES
  - Message: `feat(chunker): add impact analysis metadata to chunk output`
  - Files: `src/chunker.py`, `tests/test_chunker.py`
  - Pre-commit: `python -m pytest tests/test_chunker.py -v`

- [x] 7. Update main.py pipeline to wire AST metadata through all stages

  **What to do**:
  - Add `from src.parser import extract_ast_metadata` import to `main.py`
  - Update the file processing loop in `run_pipeline()` to:
    1. Extract `file_hash` from `file_info.get("file_hash", "")` (from discover_files)
    2. After `parse_file()`, call `extract_ast_metadata(parsed["tree"], parsed["source_bytes"])` to get metadata
    3. Pass ALL metadata params to `chunk_text()`: node_type, class_name, parent_function, imports, exports, symbols_defined, call_sites, is_exported, visibility, decorators, file_hash
  - The AST metadata extraction call should be INSIDE the `if parsed is None` guard — only extract if parse succeeded
  - Keep the existing pipeline flow: discover → parse → chunk → embed → store
  - Keep the dry-run mode working (it exits before embedding)
  - Update the metadata flattening loop (`for chunk in chunks: metadata = chunk.pop("metadata", {}); chunk.update(metadata)`) to work with the new fields (it should already work since chunk.update merges dicts)
  - Run `python -m pytest tests/ -v` and verify all tests pass
  - Run `python main.py --repo-path tmp_test_sources --dry-run` and verify pipeline completes without error

  **Must NOT do**:
  - Do NOT modify `embedder.py` or `cli.py`
  - Do NOT add new CLI arguments
  - Do NOT add incremental update logic (skip-unchanged-files)
  - Do NOT accumulate parsed results across files — process each file's tree immediately and let it be GC'd
  - Do NOT handle missing `source_bytes` or `tree` keys — they should always be present after T4

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
  - Reason: Integration task requiring careful wiring of data flow through all components

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 3 (after T2, T3, T4, T5, T6)
  - **Blocks**: T8
  - **Blocked By**: T2, T3, T4, T5, T6

  **References**:
  - `main.py:80-218` — Current `run_pipeline()` function (update the processing loop)
  - `main.py:7-13` — Current imports (add extract_ast_metadata)
  - `main.py:126-165` — Current file processing loop (where to insert metadata extraction)
  - `IMPLEMENTATION_GUIDE.md:938-1085` — Complete specification for updated pipeline
  - `tests/test_integration.py` — Integration tests (may need mock updates)

  **WHY Each Reference Matters**:
  - `main.py:126-165` — The exact loop where metadata extraction and passing must be inserted
  - `IMPLEMENTATION_GUIDE.md:938-1085` — The complete pipeline code showing exact placement of each step
  - `tests/test_integration.py` — Integration tests that may need mock updates for parse_file return values

  **Acceptance Criteria**:
  - [ ] `extract_ast_metadata` is imported from `src.parser`
  - [ ] Pipeline calls `extract_ast_metadata(parsed["tree"], parsed["source_bytes"])` after successful parse
  - [ ] All AST metadata fields are passed to `chunk_text()`
  - [ ] `file_hash` is extracted from `file_info` and passed to `chunk_text()`
  - [ ] Dry-run mode still works
  - [ ] All integration tests pass
  - [ ] `python main.py --repo-path tmp_test_sources --dry-run` completes without error

  **QA Scenarios**:

  ```
  Scenario: Pipeline runs in dry-run mode with metadata
    Tool: Bash
    Preconditions: All previous tasks (T1-T6) completed, tmp_test_sources directory exists with JS/TS files
    Steps:
      1. Run: python main.py --repo-path tmp_test_sources --dry-run --verbose 2>&1 | tee /tmp/pipeline_output.txt
      2. Check output contains: "Created N total chunks from M files"
      3. Check no errors or tracebacks in output
    Expected Result: Dry-run completes successfully with chunk count > 0
    Failure Indicators: ImportError, AttributeError, traceback, 0 chunks
    Evidence: .sisyphus/evidence/task-7-dry-run.txt

  Scenario: Metadata flows through pipeline
    Tool: Bash
    Preconditions: All previous tasks completed
    Steps:
      1. Write a small Python script that runs the pipeline steps manually:
         - discover_files on tmp_test_sources
         - parse a JS file
         - extract_ast_metadata
         - chunk with metadata
         - verify chunks contain metadata fields
      2. Run the script and verify output contains node_type, imports, call_sites, etc.
    Expected Result: Chunks contain all AST metadata fields populated with real data
    Failure Indicators: Missing metadata, empty lists for known imports, None for node_type
    Evidence: .sisyphus/evidence/task-7-metadata-flow.txt
  ```

  **Commit**: YES
  - Message: `feat(pipeline): wire AST metadata through parser-chunker-store pipeline`
  - Files: `main.py`
  - Pre-commit: `python -m pytest tests/ -v`

- [x] 8. Update existing tests and add new tests for all components

  **What to do**:
  - **test_parser.py updates**:
    - Update `test_function_name_extraction` to pass `source_bytes` as 3rd arg instead of setting `_LAST_SOURCE_BYTES`
    - Add test for `extract_ast_metadata()` with JS source containing imports, exports, functions, classes, call expressions
    - Add test for `extract_ast_metadata(tree=None, source_bytes=b'')` returning default empty metadata
    - Add test for `strip_comments_with_tree()` producing identical output to `strip_comments()`
    - Add test for `parse_file()` returning `source_bytes` and `tree` keys
  - **test_store.py updates**:
    - Update `sample_chunks` fixture to include `file_hash` field and new metadata fields
    - Update `TestMetadataPayload.test_payload_has_all_required_fields` to check for new fields
    - Add test for `_ensure_indexes()` creating indexes without error
    - Add test for `_generate_deterministic_id()` with 3 args (including file_hash)
    - Add test verifying different file_hash produces different ID
    - Add test for `_chunk_to_point()` including all new metadata in payload
  - **test_scanner.py updates**:
    - Add test for `compute_file_hash()` returning 16-char hex string for valid file
    - Add test for `compute_file_hash()` returning empty string for unreadable file
    - Add test for `discover_files()` returning `file_hash` key in output
  - **test_chunker.py updates**:
    - Add test for `chunk_text()` with all new metadata params
    - Add test for backward compatibility — `chunk_text()` without new params
    - Add test for `nesting_depth` in metadata
    - Add test for `token_count` in metadata
  - **test_integration.py updates**:
    - Update `parser.parse_file` mock to return dict with `source_bytes` and `tree` keys
    - Ensure mock return value includes all fields needed by the updated pipeline
  - Run `python -m pytest tests/ -v` and verify ALL tests pass

  **Must NOT do**:
  - Do NOT create new test files — add to existing test files
  - Do NOT reorganize test structure
  - Do NOT modify test fixtures directory structure
  - Do NOT skip any existing tests

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - Reason: Multiple test files to update, careful mock updates needed, must ensure all components are tested

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 4 (after T7)
  - **Blocks**: T9
  - **Blocked By**: T7

  **References**:
  - `tests/test_parser.py` — Existing parser tests (update function_name test, add AST metadata tests)
  - `tests/test_store.py` — Existing store tests (update fixtures, add index tests)
  - `tests/test_scanner.py` — Existing scanner tests (add file_hash tests)
  - `tests/test_chunker.py` — Existing chunker tests (add metadata tests)
  - `tests/test_integration.py` — Integration tests (update parse_file mocks)
  - `tests/test_parser.py:85` — Line that sets `_LAST_SOURCE_BYTES` (REMOVE)
  - `tests/test_parser.py:102` — Line that calls `extract_function_name()` (UPDATE)
  - `tests/test_store.py:23-58` — `sample_chunks` fixture (UPDATE)

  **WHY Each Reference Matters**:
  - `tests/test_parser.py:85,102` — Must update for new `extract_function_name` signature
  - `tests/test_store.py:23-58` — Must add new fields to fixture data
  - All test files need new test functions for new functionality

  **Acceptance Criteria**:
  - [ ] `test_function_name_extraction` passes `source_bytes` as 3rd arg
  - [ ] No reference to `_LAST_SOURCE_BYTES` in test code
  - [ ] New test for `extract_ast_metadata` with real JS source
  - [ ] New test for `extract_ast_metadata` with `None` tree
  - [ ] New test for `strip_comments_with_tree` parity with `strip_comments`
  - [ ] New test for `parse_file` returning `source_bytes` and `tree`
  - [ ] Updated store fixture includes `file_hash` and new metadata fields
  - [ ] New test for `_ensure_indexes()`
  - [ ] New test for `_generate_deterministic_id` with file_hash
  - [ ] New test for `compute_file_hash`
  - [ ] New test for `discover_files` including `file_hash`
  - [ ] New test for `chunk_text` with metadata
  - [ ] Updated integration test mock for `parse_file`
  - [ ] `python -m pytest tests/ -v` — ALL tests pass

  **QA Scenarios**:

  ```
  Scenario: Full test suite passes
    Tool: Bash
    Preconditions: All code changes saved
    Steps:
      1. Run: python -m pytest tests/ -v 2>&1 | tee /tmp/test_results.txt
      2. Verify: 0 failures, 0 errors
      3. Count total tests run: grep -c "PASSED\|FAILED" /tmp/test_results.txt or check summary line
    Expected Result: All tests pass with 0 failures
    Failure Indicators: Any test failure, import errors, collection errors
    Evidence: .sisyphus/evidence/task-8-test-suite.txt

  Scenario: Individual test files pass
    Tool: Bash
    Preconditions: All code changes saved
    Steps:
      1. Run: python -m pytest tests/test_parser.py tests/test_chunker.py tests/test_scanner.py tests/test_store.py -v
      2. Verify all 4 test files pass individually
    Expected Result: All tests pass in each file
    Failure Indicators: Any test failure in any file
    Evidence: .sisyphus/evidence/task-8-individual-tests.txt
  ```

  **Commit**: YES
  - Message: `test: add and update tests for AST metadata, file hashing, payload indexes`
  - Files: `tests/test_parser.py`, `tests/test_store.py`, `tests/test_scanner.py`, `tests/test_chunker.py`, `tests/test_integration.py`
  - Pre-commit: `python -m pytest tests/ -v`

- [x] 9. End-to-end integration verification with dry-run pipeline

  **What to do**:
  - Run the full pipeline with `--dry-run` mode on the test fixtures directory
  - Verify the pipeline discovers JS/TS/TSX files, parses them, extracts metadata, and creates chunks with all new fields
  - Write a verification script that:
    1. Runs `discover_files()` on `tmp_test_sources/`
    2. Parses each discovered file
    3. Extracts AST metadata from each parsed file
    4. Chunks with metadata params
    5. Verifies chunks contain: `node_type`, `imports`, `exports`, `call_sites`, `symbols_defined`, `class_name`, `is_exported`, `visibility`, `decorators`, `parent_function`, `nesting_depth`, `token_count`, `file_hash`
  - Verify `discover_files()` output includes `file_hash` key
  - Verify `parse_file()` output includes `source_bytes` and `tree` keys
  - Verify `extract_ast_metadata()` returns populated metadata for non-trivial JS source
  - Verify `chunk_text()` produces chunks with all metadata fields
  - Verify there are no import errors or runtime errors
  - Run `python -m pytest tests/ -v` as final sanity check

  **Must NOT do**:
  - Do NOT run the pipeline against a live Qdrant instance (dry-run only)
  - Do NOT modify any source code — this is verification only
  - Do NOT add new production code

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - Reason: Integration verification requiring careful end-to-end checking

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 4 (after T8)
  - **Blocks**: F1-F4
  - **Blocked By**: T8

  **References**:
  - `main.py:80-218` — Full pipeline function
  - `tmp_test_sources/` — Test fixtures directory with JS/TS/TSX files
  - `IMPLEMENTATION_GUIDE.md:1212-1248` — Verification checklist for all phases

  **WHY Each Reference Matters**:
  - `main.py:80-218` — The pipeline being verified end-to-end
  - `tmp_test_sources/` — Test data to verify against
  - `IMPLEMENTATION_GUIDE.md:1212-1248` — Verification checklist with specific criteria per phase

  **Acceptance Criteria**:
  - [ ] `python main.py --repo-path tmp_test_sources --dry-run` completes without error
  - [ ] `discover_files()` returns dicts with `file_hash` key
  - [ ] `parse_file()` returns dicts with `source_bytes` and `tree` keys
  - [ ] `extract_ast_metadata()` returns populated metadata for JS source
  - [ ] Chunks contain all new metadata fields
  - [ ] No import errors
  - [ ] `python -m pytest tests/ -v` — all tests pass

  **QA Scenarios**:

  ```
  Scenario: Full pipeline dry-run with all metadata fields
    Tool: Bash
    Preconditions: All previous tasks completed
    Steps:
      1. Run: python main.py --repo-path tmp_test_sources --dry-run --verbose 2>&1 | tee .sisyphus/evidence/task-9-full-pipeline.txt
      2. Check output shows: "Files found:", "Files parsed:", "Total chunks:"
      3. Run: python -c "
from src.scanner import discover_files
from src.parser import parse_file, extract_ast_metadata
from src.chunker import chunk_text

files = discover_files('tmp_test_sources')
print(f'Found {len(files)} files')
if files:
    f = files[0]
    print(f'Processing: {f[\"path\"]}')
    print(f'Has file_hash: {\"file_hash\" in f}')
    parsed = parse_file(f['path'], f['grammar'])
    if parsed:
        print(f'Has source_bytes: {\"source_bytes\" in parsed}')
        print(f'Has tree: {\"tree\" in parsed}')
        meta = extract_ast_metadata(parsed['tree'], parsed['source_bytes'])
        print(f'node_type: {meta[\"node_type\"]}')
        print(f'imports: {meta[\"imports\"]}')
        print(f'exports: {meta[\"exports\"]}')
        chunks = chunk_text(
            text=parsed['stripped_text'], start_line=1,
            end_line=parsed['stripped_line_count'],
            file_path=f['path'], language=f['language'],
            file_hash=f.get('file_hash', ''),
            **{k: meta.get(k) for k in ['node_type', 'class_name', 'parent_function', 'imports', 'exports', 'symbols_defined', 'call_sites', 'is_exported', 'visibility', 'decorators']}
        )
        if chunks:
            m = chunks[0]['metadata']
            print(f'Chunk metadata keys: {sorted(m.keys())}')
            print(f'Has node_type: {\"node_type\" in m}')
            print(f'Has imports: {\"imports\" in m}')
            print(f'Has file_hash: {\"file_hash\" in m}')
"
      4. Verify all metadata fields present
    Expected Result: Pipeline runs, all metadata fields populated, no errors
    Failure Indicators: Missing fields, import errors, runtime errors, empty metadata
    Evidence: .sisyphus/evidence/task-9-full-pipeline.txt

  Scenario: Full test suite passes
    Tool: Bash
    Preconditions: All previous tasks completed
    Steps:
      1. Run: python -m pytest tests/ -v 2>&1 | tee .sisyphus/evidence/task-9-test-suite.txt
      2. Verify: 0 failures, 0 errors
    Expected Result: All tests pass
    Failure Indicators: Any test failure
    Evidence: .sisyphus/evidence/task-9-test-suite.txt
  ```

  **Commit**: YES
  - Message: `test: verify end-to-end pipeline with dry-run mode`
  - Files: `.sisyphus/evidence/task-9-*` (evidence files only)
  - Pre-commit: `python -m pytest tests/ -v`

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

- [ ] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, run command). For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist in .sisyphus/evidence/. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`
  Run `python -m pytest tests/ -v` + `python -m pytest tests/ --tb=short`. Review all changed files for: bare `except Exception`, global mutable state, `as any`/`@ts-ignore`, empty catches, console.log in prod, commented-out code, unused imports. Check AI slop: excessive comments, over-abstraction, generic names.
  Output: `Tests [N pass/N fail] | Lint [PASS/FAIL] | Files [N clean/N issues] | VERDICT`

- [ ] F3. **Real Manual QA** — `unspecified-high`
  Start from clean state. Execute EVERY QA scenario from EVERY task. Test cross-task integration (parser → chunker → store pipeline). Test edge cases: empty file, file with only comments, file with syntax errors. Save to `.sisyphus/evidence/final-qa/`.
  Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff (git diff). Verify 1:1 — everything in spec was built (no missing), nothing beyond spec was built (no creep). Check "Must NOT do" compliance. Detect cross-task contamination. Flag unaccounted changes.
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

- **T1**: `fix(parser): remove global state and fix bare exception handling` — src/parser.py
- **T2**: `feat(scanner): add file hashing for change detection` — src/scanner.py
- **T3**: `feat(parser): add AST metadata extraction for impact analysis` — src/parser.py
- **T4**: `feat(parser): add strip_comments_with_tree and update parse_file to return tree` — src/parser.py
- **T5**: `feat(store): add payload indexes and update deterministic IDs with file_hash` — src/store.py
- **T6**: `feat(chunker): add impact analysis metadata to chunk output` — src/chunker.py
- **T7**: `feat(pipeline): wire AST metadata through parser-chunker-store pipeline` — main.py
- **T8**: `test: add and update tests for AST metadata, file hashing, payload indexes` — tests/
- **T9**: `test: verify end-to-end pipeline with dry-run mode` — tests/

---

## Success Criteria

### Verification Commands
```bash
python -m pytest tests/ -v                  # Expected: all tests pass, 0 failures
python -m pytest tests/test_parser.py -v    # Expected: all parser tests pass
python -m pytest tests/test_chunker.py -v   # Expected: all chunker tests pass
python -m pytest tests/test_scanner.py -v   # Expected: all scanner tests pass
python -m pytest tests/test_store.py -v     # Expected: all store tests pass
python main.py --repo-path tmp_test_sources --dry-run  # Expected: pipeline runs without error
```

### Final Checklist
- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent
- [ ] All tests pass
- [ ] Global `_LAST_SOURCE_BYTES` completely removed
- [ ] `extract_ast_metadata()` works for JS/TS/TSX files
- [ ] `parse_file()` returns `source_bytes` and `tree`
- [ ] `strip_comments_with_tree()` produces identical output to `strip_comments()`
- [ ] `chunk_text()` has all 11 new params with defaults
- [ ] `discover_files()` returns `file_hash` key
- [ ] `VectorStore._ensure_indexes()` creates all 11 payload indexes
- [ ] `_generate_deterministic_id()` uses file_hash in ID generation
- [ ] Pipeline passes metadata from parser → chunker → store