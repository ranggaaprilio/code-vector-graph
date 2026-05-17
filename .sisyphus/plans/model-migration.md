# Migrate Embedding Model: nomic-embed-code → jina-code-embeddings-1.5b

## TL;DR

> **Quick Summary**: Swap the embedding model from `nomic-ai/nomic-embed-code` (3584 dims) to `jinaai/jina-code-embeddings-1.5b` (1536 dims). Update config, add task-specific prefix logic (code2code for indexing, nl2code for queries), update dimensions throughout, update dependency versions, and update all tests.
>
> **Deliverables**:
> - Config updated with new model name, dimensions (1536), and tokenizer
> - Embedder updated with task-specific prefix prepending for Jina model
> - Chunker tokenizer reference updated
> - All dimension refs updated (3584→1536, 768→1536)
> - Dependency versions bumped where needed
> - All tests updated and passing
>
> **Estimated Effort**: Medium
> **Parallel Execution**: YES - 3 waves
> **Critical Path**: Task 1 (config) → Task 3 (embedder) → Task 7 (tests)

---

## Context

### Original Request
User wants to migrate from nomic-ai/nomic-embed-code to jinaai/jina-code-embeddings-1.5b. The download_model.py already downloads the Jina model, but the rest of the codebase still references nomic.

### Interview Summary
**Key Discussions**:
- Task prefixes: Hardcode `code2code` for indexing + `nl2code` for queries (Metis identified that queries are NL, not code)
- Chunk sizes: Keep current 400/64/512 — good defaults for focused code chunks
- Data migration: Auto via `get_collection_name()` — old data preserved
- Model download: Already downloaded locally
- Tests: Update existing mocks/assertions

**Research Findings**:
- Jina model dims: **1536** (not 3584). Matryoshka-truncatable to 128/256/512/1024
- Jina requires **task-specific prefixes** for optimal retrieval (nl2code, code2code, etc.)
- Pooling: Last-token pooling — current code already does this (compatible)
- `trust_remote_code=True` already in code (compatible)
- Dependency: Jina requires `transformers>=4.53.0` and `torch>=2.7.1` (current: `>=4.32.1`, `>=2.0`)
- `torch.float16` in current code should change to `torch.bfloat16` per Jina model card
- `local_files_only=True` means pre-download is required (already done)

### Metis Review
**Identified Gaps** (addressed):
- **Task prefix mismatch**: `code2code.query` prefix is for CODE input, but queries in `query.py` and `mcp_server.py` are NATURAL LANGUAGE. Need `nl2code.query` prefix for `embed_query()` and `code2code.passage` for `embed_chunks()`. **CRITICAL** — fixed in plan.
- **Dependency version gap**: Jina needs `transformers>=4.53.0`, `torch>=2.7.1`. Current requirements.txt too old. **Added as task**.
- **torch_dtype**: Should be `torch.bfloat16` (Jina's model card) not `torch.float16` (current). **Added to embedder task**.
- **Chunker tokenizer**: Uses `tokenizers` library with `local_files_only=True` and `nomic-ai/nomic-embed-code` tokenizer. Must change to Jina tokenizer name and ensure it was downloaded. **Added to chunker task**.

---

## Work Objectives

### Core Objective
Replace the nomic-ai/nomic-embed-code embedding model throughout the codebase with jinaai/jina-code-embeddings-1.5b, including proper task-specific prefixes for the Jina model.

### Concrete Deliverables
- `src/config.py` updated with new model name, dimensions, tokenizer, provider config
- `src/embedder.py` updated with prefix logic and torch_dtype fix
- `src/chunker.py` updated tokenizer reference
- `src/store.py` docstrings updated
- `download_model.py` docstring updated
- `requirements.txt` dependency versions bumped
- All test files updated with new dimensions and model name
- All tests passing

### Definition of Done
- [ ] `python -m pytest tests/ -v` passes all tests
- [ ] `EMBEDDING_PROVIDERS["huggingface"]["model"]` == `"jinaai/jina-code-embeddings-1.5b"`
- [ ] `EMBEDDING_PROVIDERS["huggingface"]["dimensions"]` == 1536
- [ ] `EMBEDDING_DIMENSIONS` == 1536
- [ ] `DEFAULT_MODEL` == `"jinaai/jina-code-embeddings-1.5b"`
- [ ] `TOKENIZER_NAME` == `"jinaai/jina-code-embeddings-1.5b"`
- [ ] `embed_chunks()` prepends `code2code.passage` prefix to each text
- [ ] `embed_query()` prepends `nl2code.query` prefix to query text
- [ ] Qdrant collection auto-named with new model suffix

### Must Have
- Model name changed from nomic to jina in ALL locations
- Dimensions changed from 3584 to 1536 in ALL locations
- Task-specific prefixes implemented (code2code.passage for indexing, nl2code.query for queries)
- All tests updated and passing
- torch_dtype changed from float16 to bfloat16
- Dependency versions updated for Jina model compatibility

### Must NOT Have (Guardrails)
- Do NOT change the embedding architecture (keep HuggingFaceEmbedder class structure)
- Do NOT change chunk sizes or max_length (keep 400/64/512)
- Do NOT remove nomic model support infrastructure (just change defaults)
- Do NOT add a CLI --task parameter (hardcode prefix strategy)
- Do NOT change the pooling logic (already compatible — last-token pooling)
- Do NOT delete or modify old Qdrant collections
- Do NOT add new dependencies beyond version bumps
- Do NOT change the download_model.py script logic (only docstring)

---

## Verification Strategy (MANDATORY)

> **ZERO HUMAN INTERVENTION** — ALL verification is agent-executed. No exceptions.

### Test Decision
- **Infrastructure exists**: YES
- **Automated tests**: YES (Tests-after — update existing tests)
- **Framework**: pytest
- **If Tests-after**: Update test assertions as part of the code changes, then run suite

### QA Policy
Every task MUST include agent-executed QA scenarios.
Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

- **Config/Constants**: Use Bash (grep/python) — verify values in files
- **Tests**: Use Bash (pytest) — run test suite, verify pass count
- **Embedder Logic**: Use Bash (python REPL) — import module, check prefix behavior

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately — foundation config):
├── Task 1: Update config.py with new model/dims/tokenizer [quick]
├── Task 2: Update requirements.txt dependency versions [quick]
└── Task 3: Fix download_model.py docstring [quick]

Wave 2 (After Wave 1 — core logic changes):
├── Task 4: Update embedder.py with prefix logic + torch_dtype fix [unspecified-high]
├── Task 5: Update chunker.py tokenizer reference [quick]
└── Task 6: Update store.py docstrings + other minor refs [quick]

Wave 3 (After Wave 2 — tests):
├── Task 7: Update test_config.py [quick]
├── Task 8: Update test_embedder.py [unspecified-high]
├── Task 9: Update test_store.py fixtures [quick]
└── Task 10: Update test_integration.py [quick]

Wave 4 (After ALL tasks — verification):
└── Task 11: Full test suite run + grep audit [unspecified-high]

Critical Path: Task 1 → Task 4 → Task 8 → Task 11
Parallel Speedup: ~60% faster than sequential
Max Concurrent: 3 (Wave 1)
```

### Dependency Matrix

| Task | Depends On | Blocks |
|------|-----------|--------|
| 1 | - | 4, 5, 7, 8 |
| 2 | - | 4 |
| 3 | - | - |
| 4 | 1, 2 | 8, 11 |
| 5 | 1 | - |
| 6 | 1 | - |
| 7 | 1 | - |
| 8 | 4 | 11 |
| 9 | 1 | - |
| 10 | 1 | 11 |
| 11 | 4, 8, 10 | - |

### Agent Dispatch Summary

- **Wave 1**: **3** — T1 → `quick`, T2 → `quick`, T3 → `quick`
- **Wave 2**: **3** — T4 → `unspecified-high`, T5 → `quick`, T6 → `quick`
- **Wave 3**: **4** — T7 → `quick`, T8 → `unspecified-high`, T9 → `quick`, T10 → `quick`
- **Wave 4**: **1** — T11 → `unspecified-high`

---

## TODOs

- [x] 1. Update config.py with new model/dims/tokenizer

  **What to do**:
  - Change `DEFAULT_MODEL` from `"nomic-ai/nomic-embed-code"` to `"jinaai/jina-code-embeddings-1.5b"`
  - Change `EMBEDDING_DIMENSIONS` from `3584` to `1536`
  - Change `TOKENIZER_NAME` from `"nomic-ai/nomic-embed-code"` to `"jinaai/jina-code-embeddings-1.5b"`
  - Change `EMBEDDING_PROVIDERS["huggingface"]["model"]` from `"nomic-ai/nomic-embed-code"` to `"jinaai/jina-code-embeddings-1.5b"`
  - Change `EMBEDDING_PROVIDERS["huggingface"]["dimensions"]` from `3584` to `1536`

  **Must NOT do**:
  - Do NOT change the structure of EMBEDDING_PROVIDERS dict
  - Do NOT add new provider keys
  - Do NOT change NEO4J or QDRANT config

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2, 3)
  - **Blocks**: Tasks 4, 5, 7, 8, 9, 10
  - **Blocked By**: None

  **References**:
  - `src/config.py:19-28` — All 5 values to change: DEFAULT_MODEL, EMBEDDING_DIMENSIONS, TOKENIZER_NAME, EMBEDDING_PROVIDERS model and dimensions

  **Acceptance Criteria**:
  - [ ] `python -c "from src.config import EMBEDDING_DIMENSIONS; assert EMBEDDING_DIMENSIONS == 1536"` succeeds
  - [ ] `python -c "from src.config import DEFAULT_MODEL; assert DEFAULT_MODEL == 'jinaai/jina-code-embeddings-1.5b'"` succeeds
  - [ ] `python -c "from src.config import TOKENIZER_NAME; assert TOKENIZER_NAME == 'jinaai/jina-code-embeddings-1.5b'"` succeeds
  - [ ] `python -c "from src.config import EMBEDDING_PROVIDERS; assert EMBEDDING_PROVIDERS['huggingface']['dimensions'] == 1536"` succeeds

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Config values are correct
    Tool: Bash (python)
    Preconditions: config.py has been updated
    Steps:
      1. Run: python -c "from src.config import EMBEDDING_DIMENSIONS, DEFAULT_MODEL, TOKENIZER_NAME, EMBEDDING_PROVIDERS; assert EMBEDDING_DIMENSIONS == 1536; assert DEFAULT_MODEL == 'jinaai/jina-code-embeddings-1.5b'; assert TOKENIZER_NAME == 'jinaai/jina-code-embeddings-1.5b'; assert EMBEDDING_PROVIDERS['huggingface']['model'] == 'jinaai/jina-code-embeddings-1.5b'; assert EMBEDDING_PROVIDERS['huggingface']['dimensions'] == 1536"
      2. Assert exit code 0
    Expected Result: All assertions pass, exit code 0
    Failure Indicators: AssertionError or ImportError
    Evidence: .sisyphus/evidence/task-1-config-values.txt

  Scenario: No nomic references remain in config
    Tool: Bash (grep)
    Preconditions: config.py updated
    Steps:
      1. Run: grep -c "nomic" src/config.py
      2. Assert count is 0
    Expected Result: Zero matches for "nomic" in config.py
    Failure Indicators: Any nomic reference found
    Evidence: .sisyphus/evidence/task-1-no-nomic-grep.txt
  ```

  **Commit**: YES (groups with Tasks 2, 3)
  - Message: `refactor(config): migrate embedding model from nomic to jina`
  - Files: `src/config.py, requirements.txt, download_model.py`
  - Pre-commit: `python -m pytest tests/test_config.py -v`

- [x] 2. Update requirements.txt dependency versions

  **What to do**:
  - Change `transformers` minimum from `>=4.32.1` to `>=4.53.0` (Jina model card requirement)
  - Change `torch` minimum from `>=2.0` to `>=2.7.1` (Jina model card requirement)
  - Verify no other dependencies conflict

  **Must NOT do**:
  - Do NOT add new dependencies
  - Do NOT remove any existing dependencies

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 3)
  - **Blocks**: Task 4
  - **Blocked By**: None

  **References**:
  - `requirements.txt` — Current transformers and torch version pins

  **Acceptance Criteria**:
  - [ ] `requirements.txt` contains `transformers>=4.53.0`
  - [ ] `requirements.txt` contains `torch>=2.7.1`

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Dependency versions are correct
    Tool: Bash (grep)
    Preconditions: requirements.txt updated
    Steps:
      1. Run: grep "transformers" requirements.txt
      2. Assert output contains ">=4.53.0"
      3. Run: grep "torch" requirements.txt
      4. Assert output contains ">=2.7.1"
    Expected Result: Both version strings found with correct minimums
    Failure Indicators: Wrong version numbers or missing lines
    Evidence: .sisyphus/evidence/task-2-deps-grep.txt
  ```

  **Commit**: YES (groups with Tasks 1, 3)
  - Message: `refactor(config): migrate embedding model from nomic to jina`
  - Files: `src/config.py, requirements.txt, download_model.py`

- [x] 3. Fix download_model.py docstring

  **What to do**:
  - Change the docstring on line 2 from `"""Download nomic-ai/nomic-embed-code model from Hugging Face."""` to `"""Download jinaai/jina-code-embeddings-1.5b model from Hugging Face."""`
  - No code changes needed — the model_name on line 26 already says `"jinaai/jina-code-embeddings-1.5b"`

  **Must NOT do**:
  - Do NOT change any code logic in download_model.py
  - Do NOT change the model_name variable (already correct)

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - `download_model.py:2` — Docstring to update
  - `download_model.py:26` — Already correct model_name

  **Acceptance Criteria**:
  - [ ] Docstring contains "jinaai/jina-code-embeddings-1.5b"
  - [ ] `grep "nomic" download_model.py` returns no matches

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Docstring references jina model
    Tool: Bash (grep)
    Preconditions: download_model.py updated
    Steps:
      1. Run: grep "nomic" download_model.py
      2. Assert count is 0
      3. Run: grep "jina-code-embeddings" download_model.py
      4. Assert count is at least 2 (docstring + model_name)
    Expected Result: No nomic references, jina references present
    Failure Indicators: Any nomic reference remains
    Evidence: .sisyphus/evidence/task-3-docstring-fix.txt
  ```

  **Commit**: YES (groups with Tasks 1, 2)
  - Message: `refactor(config): migrate embedding model from nomic to jina`
  - Files: `src/config.py, requirements.txt, download_model.py`

- [x] 4. Update embedder.py with prefix logic + torch_dtype fix

  **What to do**:
  - Add a `JINA_TASK_PREFIXES` constant dict with the code2code and nl2code prefixes:
    ```python
    JINA_TASK_PREFIXES = {
        "code2code": {
            "query": "Find an equivalent code snippet given the following code snippet:\n",
            "passage": "Candidate code snippet:\n",
        },
        "nl2code": {
            "query": "Find the most relevant code snippet given the following query:\n",
            "passage": "Candidate code snippet:\n",
        },
    }
    ```
  - Modify `embed_chunks()` to prepend the `code2code.passage` prefix (`"Candidate code snippet:\n"`) to each text before tokenization
  - Modify `embed_query()` to prepend the `nl2code.query` prefix (`"Find the most relevant code snippet given the following query:\n"`) to query text before tokenization
  - Change `torch.float16` to `torch.bfloat16` on line 60 of embedder.py (model loading)
  - Ensure prefix is prepended BEFORE tokenization, not after

  **Must NOT do**:
  - Do NOT change the pooling logic (already compatible — last-token pooling)
  - Do NOT change the class structure or method signatures
  - Do NOT add a task parameter to the constructor (hardcode prefix strategy)
  - Do NOT change max_length from 512

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 2 (with Tasks 5, 6, after Wave 1)
  - **Blocks**: Tasks 8, 11
  - **Blocked By**: Tasks 1, 2

  **References**:
  - `src/embedder.py:39-88` — HuggingFaceEmbedder.__init__, need to change torch_dtype on line 60
  - `src/embedder.py:101-180` — embed_chunks(), need to add prefix prepending before tokenization
  - `src/embedder.py:182-206` — embed_query(), need to add prefix prepending before tokenization
  - Jina model card: task-specific prefixes required for optimal retrieval. `nl2code.query` for NL queries, `code2code.passage` for indexing code snippets.

  **WHY Each Reference Matters**:
  - embedder.py init: torch_dtype must change from float16 to bfloat16 per Jina model spec
  - embedder.py embed_chunks: prefixes must be prepended to raw text strings BEFORE tokenization
  - embedder.py embed_query: different prefix (nl2code.query) because queries are natural language

  **Acceptance Criteria**:
  - [ ] `embed_chunks()` prepends `"Candidate code snippet:\n"` to each text
  - [ ] `embed_query()` prepends `"Find the most relevant code snippet given the following query:\n"` to query
  - [ ] `torch.float16` changed to `torch.bfloat16`
  - [ ] Prefix constants are defined at module level
  - [ ] No `search_document` prefix remains (current code has none, but verify)

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Prefix logic works in embed_chunks (mock test)
    Tool: Bash (python)
    Preconditions: embedder.py updated
    Steps:
      1. Run: python -c "from src.embedder import JINA_TASK_PREFIXES; assert 'code2code' in JINA_TASK_PREFIXES; assert 'passage' in JINA_TASK_PREFIXES['code2code']; assert JINA_TASK_PREFIXES['code2code']['passage'] == 'Candidate code snippet:\n'; print('PASS: passage prefix correct')"
      2. Assert exit code 0
    Expected Result: JINA_TASK_PREFIXES constant loaded and has correct values
    Failure Indicators: ImportError or AssertionError
    Evidence: .sisyphus/evidence/task-4-prefixes-exist.txt

  Scenario: Prefix logic works in embed_query (mock test)
    Tool: Bash (python)
    Preconditions: embedder.py updated
    Steps:
      1. Run: python -c "from src.embedder import JINA_TASK_PREFIXES; assert 'nl2code' in JINA_TASK_PREFIXES; assert 'query' in JINA_TASK_PREFIXES['nl2code']; assert JINA_TASK_PREFIXES['nl2code']['query'] == 'Find the most relevant code snippet given the following query:\n'; print('PASS: query prefix correct')"
      2. Assert exit code 0
    Expected Result: nl2code query prefix is correct
    Failure Indicators: KeyError or AssertionError
    Evidence: .sisyphus/evidence/task-4-nl2code-prefix.txt

  Scenario: torch_dtype is bfloat16
    Tool: Bash (grep)
    Preconditions: embedder.py updated
    Steps:
      1. Run: grep "torch.bfloat16" src/embedder.py
      2. Assert match found
      3. Run: grep "torch.float16" src/embedder.py
      4. Assert NO match (it was replaced)
    Expected Result: bfloat16 found, float16 not found
    Failure Indicators: float16 still present or bfloat16 not found
    Evidence: .sisyphus/evidence/task-4-torch-dtype.txt
  ```

  **Commit**: YES (groups with Tasks 5, 6)
  - Message: `feat(embedder): add jina task-specific prefixes and update model config`
  - Files: `src/embedder.py, src/chunker.py, src/store.py`

- [x] 5. Update chunker.py tokenizer reference

  **What to do**:
  - The chunker imports `TOKENIZER_NAME` from config and uses it to load a fast tokenizer. Since config.py will already have the new model name after Task 1, the chunker should work automatically.
  - Verify the chunker's `load_tokenizer()` function will work with `jinaai/jina-code-embeddings-1.5b` tokenizer name
  - Check that the `local_files_only=True` parameter won't cause issues — the tokenizer must already be downloaded via `download_model.py`
  - Update the docstring on line 39 that references `'nomic-ai/nomic-embed-code'` to `'jinaai/jina-code-embeddings-1.5b'`

  **Must NOT do**:
  - Do NOT change chunking algorithm or sizes
  - Do NOT change the DummyTokenizer fallback behavior
  - Do NOT hardcode the model name — it should come from config

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 4, 6)
  - **Blocks**: None
  - **Blocked By**: Task 1

  **References**:
  - `src/chunker.py:9` — Imports TOKENIZER_NAME from config
  - `src/chunker.py:30-69` — `load_tokenizer()` function, uses `local_files_only=True`
  - `src/chunker.py:39` — Docstring referencing 'nomic-ai/nomic-embed-code'

  **Acceptance Criteria**:
  - [ ] Docstring in `load_tokenizer()` references jina model name
  - [ ] `grep "nomic" src/chunker.py` returns no matches
  - [ ] Tokenizer name comes from config import (not hardcoded)

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: No nomic references in chunker
    Tool: Bash (grep)
    Preconditions: chunker.py updated
    Steps:
      1. Run: grep -c "nomic" src/chunker.py
      2. Assert count is 0
    Expected Result: Zero nomic references
    Failure Indicators: Any nomic reference remaining
    Evidence: .sisyphus/evidence/task-5-chunker-nomic-check.txt
  ```

  **Commit**: YES (groups with Tasks 4, 6)
  - Message: `feat(embedder): add jina task-specific prefixes and update model config`
  - Files: `src/embedder.py, src/chunker.py, src/store.py`

- [x] 6. Update store.py docstrings + other minor refs

  **What to do**:
  - Update the docstring on line 121 from `size=768` to `size=1536` (or just make it generic like `size={self.embedding_dimensions}`)
  - Update the docstring on line 172 from `768 dimensions` to `1536 dimensions`
  - Update comment examples on lines 26-27 from `code_chunks_nomic-embed-code_3584` to `code_chunks_jina-code-embeddings-1.5b_1536`
  - Search for any other `768` or `3584` references in store.py and update appropriately

  **Must NOT do**:
  - Do NOT change VectorStore logic or method signatures
  - Do NOT change how dimensions are sourced (still from config)

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 4, 5)
  - **Blocks**: None
  - **Blocked By**: Task 1

  **References**:
  - `src/store.py:26-27` — Collection name examples in docstring
  - `src/store.py:121` — `Create collection` docstring referencing 768
  - `src/store.py:172` — `_generate_deterministic_id` docstring referencing 768

  **Acceptance Criteria**:
  - [ ] `grep "768" src/store.py` returns no matches (except in actual 768-dim context)
  - [ ] `grep "nomic" src/store.py` returns no matches
  - [ ] Collection name examples show jina model

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: No stale references in store.py
    Tool: Bash (grep)
    Preconditions: store.py updated
    Steps:
      1. Run: grep -c "nomic" src/store.py → assert 0
      2. Run: grep -c "768" src/store.py → assert 0 (or only in tests context)
    Expected Result: No nomic or 768 references in store.py
    Failure Indicators: Any stale references remain
    Evidence: .sisyphus/evidence/task-6-store-references.txt
  ```

  **Commit**: YES (groups with Tasks 4, 5)
  - Message: `feat(embedder): add jina task-specific prefixes and update model config`
  - Files: `src/embedder.py, src/chunker.py, src/store.py`

- [x] 7. Update test_config.py

  **What to do**:
  - Change `assert EMBEDDING_DIMENSIONS == 3584` to `assert EMBEDDING_DIMENSIONS == 1536` on line 16

  **Must NOT do**:
  - Do NOT change test structure or add new tests
  - Do NOT change other unrelated assertions

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 8, 9, 10)
  - **Blocks**: None
  - **Blocked By**: Task 1

  **References**:
  - `tests/test_config.py:16` — `assert EMBEDDING_DIMENSIONS == 3584` needs to be `== 1536`

  **Acceptance Criteria**:
  - [ ] `python -m pytest tests/test_config.py -v` passes

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: config tests pass with new dimensions
    Tool: Bash (pytest)
    Preconditions: Task 1 (config.py) and test update complete
    Steps:
      1. Run: python -m pytest tests/test_config.py -v
      2. Assert all tests pass, 0 failures
    Expected Result: 3 tests pass (test_supported_extensions, test_embedding_dimensions_value, test_comment_node_types)
    Failure Indicators: Any test failure
    Evidence: .sisyphus/evidence/task-7-test-config.txt
  ```

  **Commit**: YES (groups with Tasks 8, 9, 10)
  - Message: `test: update test fixtures and assertions for jina model migration`
  - Files: `tests/test_config.py, tests/test_embedder.py, tests/test_store.py, tests/test_integration.py`

- [x] 8. Update test_embedder.py

  **What to do**:
  - Change `assert embedder.model_name == "nomic-ai/nomic-embed-code"` on line 22 to `assert embedder.model_name == "jinaai/jina-code-embeddings-1.5b"`
  - Change all `3584` dimension references to `1536` (lines 68, 78, 79, 100, 140, etc. — mock tensor dimensions)
  - Change all `torch.randn(batch_size, 10, 3584)` to `torch.randn(batch_size, 10, 1536)` in mock outputs
  - Change `torch.randn(1, 3, 3584)` to `torch.randn(1, 3, 1536)` in single-chunk mock outputs
  - Add a test that verifies prefix prepending: mock the tokenizer and check that `embed_chunks()` passes text with `"Candidate code snippet:\n"` prefix
  - Add a test that verifies query prefix: check that `embed_query()` prepends `"Find the most relevant code snippet given the following query:\n"`
  - Verify mock `last_hidden_state` dimensions match 1536

  **Must NOT do**:
  - Do NOT change the mock structure or test patterns
  - Do NOT add unnecessary test infrastructure
  - Do NOT change the HuggingFaceEmbedder interface being tested

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO — depends on Task 4 (embedder prefix logic)
  - **Parallel Group**: Wave 3 (with Tasks 7, 9, 10)
  - **Blocks**: Task 11
  - **Blocked By**: Tasks 1, 4

  **References**:
  - `tests/test_embedder.py:22` — Model name assertion
  - `tests/test_embedder.py:68,78,79,100,140` — `3584` dimension assertions and mock tensor dimensions
  - `tests/test_embedder.py:106` — Test for "search_document" prefix absence (verify still no prefix, but check for Jina prefix instead)
  - `src/embedder.py` — Need to understand the new prefix logic to write correct tests

  **Acceptance Criteria**:
  - [ ] `python -m pytest tests/test_embedder.py -v` passes
  - [ ] No `3584` references remain in test_embedder.py
  - [ ] No `nomic-embed-code` references remain
  - [ ] Tests verify prefix prepending for both embed_chunks and embed_query

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: embedder tests pass with new model and dimensions
    Tool: Bash (pytest)
    Preconditions: Both embedder.py and test_embedder.py updated
    Steps:
      1. Run: python -m pytest tests/test_embedder.py -v
      2. Assert all tests pass, 0 failures
    Expected Result: All embedder tests pass with 1536 dimensions and jina model name
    Failure Indicators: Any test failure or import error
    Evidence: .sisyphus/evidence/task-8-test-embedder.txt

  Scenario: No stale dimension references in embedder tests
    Tool: Bash (grep)
    Preconditions: test_embedder.py updated
    Steps:
      1. Run: grep -c "3584" tests/test_embedder.py
      2. Assert count is 0
      3. Run: grep -c "nomic-embed-code" tests/test_embedder.py
      4. Assert count is 0
    Expected Result: No stale references
    Failure Indicators: Old dimension or model name found
    Evidence: .sisyphus/evidence/task-8-no-stale-refs.txt
  ```

  **Commit**: YES (groups with Tasks 7, 9, 10)
  - Message: `test: update test fixtures and assertions for jina model migration`
  - Files: `tests/test_config.py, tests/test_embedder.py, tests/test_store.py, tests/test_integration.py`

- [x] 9. Update test_store.py fixtures

  **What to do**:
  - Change `embedding_dimensions=768` to `embedding_dimensions=1536` in `in_memory_store` fixture on line 16
  - Change `[0.1] * 768` to `[0.1] * 1536` on line 28
  - Change `[0.2] * 768` to `[0.2] * 1536` on line 39
  - Change `[0.3] * 768` to `[0.3] * 1536` on line 49
  - Change the `test_init_with_defaults` assertion from `3584` to `1536` on line 68

  **Must NOT do**:
  - Do NOT change test structure or add new tests
  - Do NOT change VectorStore interface being tested

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 7, 8, 10)
  - **Blocks**: None
  - **Blocked By**: Task 1

  **References**:
  - `tests/test_store.py:16-18` — `in_memory_store` fixture with `embedding_dimensions=768`
  - `tests/test_store.py:28,39,49` — Mock embeddings with `768` dimension lists
  - `tests/test_store.py:68` — `assert store.embedding_dimensions == 3584`

  **Acceptance Criteria**:
  - [ ] `grep "768" tests/test_store.py` returns no matches (except in comments)
  - [ ] `grep "3584" tests/test_store.py` returns no matches
  - [ ] `python -m pytest tests/test_store.py -v` passes

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: store tests pass with new dimensions
    Tool: Bash (pytest)
    Preconditions: Task 1 (config) and test update complete
    Steps:
      1. Run: python -m pytest tests/test_store.py -v
      2. Assert all tests pass
    Expected Result: All store tests pass with 1536 dimensions
    Failure Indicators: Any test failure
    Evidence: .sisyphus/evidence/task-9-test-store.txt

  Scenario: No stale dimensions in store tests
    Tool: Bash (grep)
    Preconditions: test_store.py updated
    Steps:
      1. Run: grep -c "768" tests/test_store.py → assert 0
      2. Run: grep -c "3584" tests/test_store.py → assert 0
    Expected Result: No 768 or 3584 references
    Failure Indicators: Old dimension values found
    Evidence: .sisyphus/evidence/task-9-no-stale-dims.txt
  ```

  **Commit**: YES (groups with Tasks 7, 8, 10)
  - Message: `test: update test fixtures and assertions for jina model migration`
  - Files: `tests/test_config.py, tests/test_embedder.py, tests/test_store.py, tests/test_integration.py`

- [x] 10. Update test_integration.py

  **What to do**:
  - Change `[0.1] * 3584` to `[0.1] * 1536` on line 270
  - Change `[0.2] * 3584` to `[0.2] * 1536` on line 281

  **Must NOT do**:
  - Do NOT change test structure or integration test patterns
  - Do NOT change mock structures beyond dimension updates

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 7, 8, 9)
  - **Blocks**: Task 11
  - **Blocked By**: Task 1

  **References**:
  - `tests/test_integration.py:270` — Mock embedding `[0.1] * 3584`
  - `tests/test_integration.py:281` — Mock embedding `[0.2] * 3584`

  **Acceptance Criteria**:
  - [ ] `grep "3584" tests/test_integration.py` returns no matches
  - [ ] `python -m pytest tests/test_integration.py -v` passes (may need Qdrant mock)

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: No stale dimensions in integration tests
    Tool: Bash (grep)
    Preconditions: test_integration.py updated
    Steps:
      1. Run: grep -c "3584" tests/test_integration.py → assert 0
    Expected Result: Zero 3584 references
    Failure Indicators: Old dimension value found
    Evidence: .sisyphus/evidence/task-10-no-stale-dims.txt
  ```

  **Commit**: YES (groups with Tasks 7, 8, 9)
  - Message: `test: update test fixtures and assertions for jina model migration`
  - Files: `tests/test_config.py, tests/test_embedder.py, tests/test_store.py, tests/test_integration.py`

- [x] 11. Full test suite run + grep audit

  **What to do**:
  - Run `python -m pytest tests/ -v` and verify ALL tests pass
  - Run `grep -r "nomic" src/` and verify zero matches for "nomic" in source code
  - Run `grep -r "3584" src/` and verify zero matches for old dimension
  - Run `grep -r "768" src/` and verify zero stale dimension references
  - Run `python -c "from src.config import EMBEDDING_DIMENSIONS, DEFAULT_MODEL, TOKENIZER_NAME; assert EMBEDDING_DIMENSIONS == 1536; assert DEFAULT_MODEL == 'jinaai/jina-code-embeddings-1.5b'; assert TOKENIZER_NAME == 'jinaai/jina-code-embeddings-1.5b'"`
  - Verify embedder.py contains `JINA_TASK_PREFIXES` constant
  - Verify embedder.py uses `torch.bfloat16` not `torch.float16`

  **Must NOT do**:
  - Do NOT fix any failing tests yourself — flag them for manual review
  - Do NOT change any source code in this task

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 4 (sequential, after all other tasks)
  - **Blocks**: Final verification wave
  - **Blocked By**: All previous tasks

  **References**:
  - All source files in `src/`
  - All test files in `tests/`

  **Acceptance Criteria**:
  - [ ] `python -m pytest tests/ -v` passes with 0 failures
  - [ ] `grep -r "nomic" src/` returns no matches (excluding any legitimate nomic mentions)
  - [ ] `grep -r "3584" src/` returns no matches
  - [ ] Config values all assert correct jina model name and 1536 dimensions
  - [ ] `JINA_TASK_PREFIXES` constant exists in embedder.py

  **QA Scenarios (MANDATORY)**:

  ```
  Scenario: Full test suite passes
    Tool: Bash (pytest)
    Preconditions: All previous tasks completed
    Steps:
      1. Run: python -m pytest tests/ -v
      2. Assert all tests pass, 0 failures
    Expected Result: All tests pass
    Failure Indicators: Any test failure
    Evidence: .sisyphus/evidence/task-11-full-test-suite.txt

  Scenario: No stale nomic references in source
    Tool: Bash (grep)
    Preconditions: All source changes complete
    Steps:
      1. Run: grep -r "nomic" src/ → assert 0 matches
      2. Run: grep -r "3584" src/ → assert 0 matches
      3. Run: grep -r "768" src/ → verify only comments or valid refs remain
    Expected Result: Clean source with no stale references
    Failure Indicators: Any nomic or 3584 reference in src/
    Evidence: .sisyphus/evidence/task-11-grep-audit.txt

  Scenario: Config values verify correctly
    Tool: Bash (python)
    Preconditions: All config changes complete
    Steps:
      1. Run: python -c "from src.config import EMBEDDING_DIMENSIONS, DEFAULT_MODEL, TOKENIZER_NAME, EMBEDDING_PROVIDERS; assert EMBEDDING_DIMENSIONS == 1536; assert DEFAULT_MODEL == 'jinaai/jina-code-embeddings-1.5b'; assert TOKENIZER_NAME == 'jinaai/jina-code-embeddings-1.5b'; assert EMBEDDING_PROVIDERS['huggingface']['dimensions'] == 1536; assert EMBEDDING_PROVIDERS['huggingface']['model'] == 'jinaai/jina-code-embeddings-1.5b'; print('ALL CONFIG ASSERTIONS PASS')"
      2. Assert exit code 0 and output contains "ALL CONFIG ASSERTIONS PASS"
    Expected Result: All config assertions pass
    Failure Indicators: AssertionError or ImportError
    Evidence: .sisyphus/evidence/task-11-config-verify.txt

  Scenario: Embedder prefix constants exist and are correct
    Tool: Bash (python)
    Preconditions: embedder.py updated
    Steps:
      1. Run: python -c "from src.embedder import JINA_TASK_PREFIXES; assert JINA_TASK_PREFIXES['code2code']['passage'] == 'Candidate code snippet:\n'; assert JINA_TASK_PREFIXES['nl2code']['query'] == 'Find the most relevant code snippet given the following query:\n'; print('ALL PREFIX ASSERTIONS PASS')"
      2. Assert exit code 0
    Expected Result: Prefix constants loaded correctly with exact values
    Failure Indicators: ImportError, KeyError, or AssertionError
    Evidence: .sisyphus/evidence/task-11-prefix-verify.txt
  ```

  **Commit**: YES
  - Message: `chore: verify full test suite passes after model migration`
  - Files: (no files, verification only — only commit if fixes are needed)

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.

- [ ] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, grep for values). For each "Must NOT Have": search codebase for forbidden patterns (nomic-embed-code, 3584 dims in non-test contexts, search_document prefix, float16 dtype). Check evidence files exist in .sisyphus/evidence/. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [ ] F2. **Code Quality Review** — `unspecified-high`
  Run `python -m pytest tests/ -v`. Review all changed files for: hardcoded nomic references, wrong dimension values, missing prefix logic, import errors. Check AI slop: overcommenting, unnecessary refactoring beyond scope, scope creep.
  Output: `Tests [N pass/N fail] | Files [N clean/N issues] | VERDICT`

- [ ] F3. **Real Manual QA** — `unspecified-high`
  From clean state, verify: config values correct, embedder prefix logic works (mock test), chunker tokenizer ref correct, all tests pass. Test edge cases: empty chunks, single chunk, very long text unchanged. Save to `.sisyphus/evidence/final-qa/`.
  Output: `Scenarios [N/N pass] | Integration [N/N] | Edge Cases [N tested] | VERDICT`

- [ ] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff. Verify 1:1 — everything in spec was built (no missing), nothing beyond spec was built (no creep). Check "Must NOT do" compliance. Flag unaccounted changes.
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

- **Tasks 1-3**: `refactor(config): migrate embedding model from nomic to jina` — config.py, requirements.txt, download_model.py
- **Tasks 4-6**: `feat(embedder): add jina task-specific prefixes and update model config` — embedder.py, chunker.py, store.py
- **Tasks 7-10**: `test: update test fixtures and assertions for jina model migration` — all test files
- **Task 11**: `chore: verify full test suite passes after model migration`

---

## Success Criteria

### Verification Commands
```bash
python -m pytest tests/ -v          # Expected: all tests pass
grep -r "nomic-embed-code" src/      # Expected: no matches (only jina references)
grep -r "3584" src/                  # Expected: no matches in src/ (1536 only)
grep -r "768" src/store.py           # Expected: no matches (was old docstring)
python -c "from src.config import EMBEDDING_DIMENSIONS; assert EMBEDDING_DIMENSIONS == 1536"
python -c "from src.config import DEFAULT_MODEL; assert DEFAULT_MODEL == 'jinaai/jina-code-embeddings-1.5b'"
```

### Final Checklist
- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent
- [ ] All tests pass
- [ ] No nomic-embed-code references in src/
- [ ] Dimension 1536 everywhere (no 3584)
- [ ] Task prefixes implemented (code2code.passage for indexing, nl2code.query for queries)