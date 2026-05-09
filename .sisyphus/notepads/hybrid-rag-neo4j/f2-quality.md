# F2: Code Quality Review Report

**Date:** 2026-05-06
**Scope:** src/graph_schema.py, src/graph_extractor.py, src/graph_store.py, src/hybrid_retriever.py + tests

---

## Executive Summary

| Metric | Result |
|--------|--------|
| Build | N/A (Python) |
| Lint | PASS (no LSP errors) |
| Tests | **128 passed, 13 failed** |
| Coverage | **71% overall** |
| New Module Coverage | graph_schema: 29%, graph_extractor: 90%, graph_store: 94%, hybrid_retriever: 24% |
| Files Clean | **2/4** |
| Files with Issues | **2/4** |
| **VERDICT** | **NEEDS WORK** |

---

## Test Results

### Test Execution Summary
```
Total: 141 tests
Passed: 128 (91%)
Failed: 13 (9%)
```

### Failed Tests

#### Pre-existing Failures (Not related to new modules):
1. `test_embedder.py::TestHuggingFaceEmbedderInit::test_init_with_defaults`
2. `test_embedder.py::TestHuggingFaceEmbedderInit::test_init_with_custom_params`
   - **Reason:** Tests expect `trust_remote_code=True` but code passes `local_files_only=True` too

3. `test_integration.py::TestPipelineDryRun::test_dry_run_does_not_embed`
4. `test_integration.py::TestPipelineDryRun::test_dry_run_prints_stats`
5. `test_integration.py::TestPipelineFullRun::test_full_pipeline_with_mocked_services`
6. `test_integration.py::TestVerboseOutput::test_verbose_enables_info_logging`
7. `test_integration.py::TestVerboseOutput::test_non_verbose_only_warning`
8. `test_integration.py::TestErrorHandling::test_skip_failed_parse_files`
9. `test_integration.py::TestErrorHandling::test_pipeline_continues_on_parse_error`
   - **Reason:** Tests reference `main.CodeEmbedder` which doesn't exist in main.py

10. `test_integration.py::TestCLIHelp::test_cli_help`
    - **Reason:** File path error - looking for non-existent directory

11. `test_parser.py::test_parse_error_returns_none`
    - **Reason:** Test expects None on parse error but parser returns partial result

#### New Module Failures (Related to new code):
12. `test_hybrid_retriever.py::test_hybrid_search_vector_mode_calls_vector_only`
13. `test_hybrid_retriever.py::test_hybrid_search_calls_both_stores_and_merges`
    - **Reason:** Tests mock `retriever.search` but then assert on `vector_store.search` - test logic issue

### New Module Test Results

| Test File | Result | Notes |
|-----------|--------|-------|
| test_graph_extractor.py | **15/15 PASSED** | All tests pass |
| test_graph_store.py | **8/8 PASSED** | All tests pass |
| test_hybrid_retriever.py | **5/7 PASSED** | 2 test logic issues |

---

## Coverage Report

| Module | Stmts | Miss | Cover | Missing Lines |
|--------|-------|------|-------|---------------|
| src/graph_schema.py | 35 | 25 | **29%** | 129-156, 160-162 |
| src/graph_extractor.py | 58 | 6 | **90%** | 61-70 |
| src/graph_store.py | 47 | 3 | **94%** | 27-29 |
| src/hybrid_retriever.py | 104 | 79 | **24%** | 42-48, 51-83, 87-105, 109-132, 135-138, 141-158 |

### Coverage Analysis

- **graph_schema.py (29%)**: Only validation functions not covered (validate_node, get_required_properties)
- **graph_extractor.py (90%)**: Excellent coverage - only _maybe_add_node fallback not hit
- **graph_store.py (94%)**: Excellent coverage - only error handling path not hit
- **hybrid_retriever.py (24%)**: **CRITICAL** - Most functionality not tested by unit tests, only RRF utility function tested

---

## Code Quality Issues by File

### ✅ src/graph_schema.py - CLEAN

**No quality issues found.**

- Clean imports (no unused)
- No bare except blocks
- No print statements
- No `# type: ignore` comments
- No `as any` type annotations
- Proper logging usage

### ⚠️ src/graph_extractor.py - MINOR ISSUES

**Issues Found:**

1. **Excessive Comments** (Lines 100-213)
   - Too many inline comments explaining obvious code
   - Comments like "# Class", "# Function", "# Variable" are redundant
   - The module docstring already explains the pragmatic approach

2. **Generic Variable Names**
   - Line 206: `_rel(t: str, a: str, b: str)` - `t`, `a`, `b` are generic
   - Line 102: `added_ids` could be more descriptive

3. **Unused Import**
   - Line 31: `from src.graph_schema import NODE_PROPERTIES` - Imported but never used

**Lines:** 1, 100-213, 206

### ✅ src/graph_store.py - CLEAN

**No quality issues found.**

- Clean implementation
- Proper error handling with logging
- No bare except blocks (uses `except Exception as exc` with logging)
- No print statements
- No type ignores

### ⚠️ src/hybrid_retriever.py - ISSUES FOUND

**Issues Found:**

1. **`# type: ignore` Comments** (Lines 74, 76, 153)
   - Line 74: `doc_id, payload, score = r  # type: ignore`
   - Line 76: `doc_id, score = r  # type: ignore`
   - Line 153: `graph_context = self.graph_store.get_related_nodes(...)  # type: ignore`
   - **Fix:** Use proper type annotations or structural pattern matching

2. **Bare Exception Handling** (Lines 57, 95, 154)
   - Lines 57, 95: `except Exception as e:` - Should use specific exceptions
   - Line 154: `except Exception as e:` - Same issue
   - **Fix:** Catch specific exceptions like `(ConnectionError, ValueError, AttributeError)`

3. **Missing Docstrings**
   - Most methods lack proper docstrings
   - `_vector_search`, `_graph_search`, `_hybrid_search`, `_enrich_result` undocumented

**Lines:** 74, 76, 153, 57, 95, 154

---

## Test File Quality Review

### test_graph_extractor.py - CLEAN
- Well-structured tests
- Good use of pytest patterns
- Proper skipping when module unavailable
- No quality issues

### test_graph_store.py - CLEAN
- Clean mock usage
- Good test coverage
- No quality issues

### test_hybrid_retriever.py - ISSUES

1. **Broken Test Logic** (Lines 52-72)
   - Tests mock `retriever.search` but then assert on `vector_store.search`
   - This means the mock prevents the actual method from being called
   - Test will always fail because assertions check the wrong thing

   **Problematic Pattern:**
   ```python
   retriever = HybridRetriever(vector_store=vector_store, graph_store=graph_store)
   retriever.search = MagicMock(return_value=[...])  # This breaks the test!
   retriever.search("query", mode="vector")
   vector_store.search.assert_called_once()  # Never called because of mock
   ```

---

## Other Project-Wide Issues (Not in new modules)

### src/embedder.py
- **Lines 256, 260, 264, 268, 274:** `print()` statements in production code
- **Lines 284, 303, 435:** Bare `except Exception:` blocks

### src/parser.py
- **Lines 18-24:** `# type: ignore` on imports with bare `except Exception`
- **Lines 196, 256:** Bare `except Exception:` blocks

### src/chunker.py
- **Lines 54, 62, 64:** `# type: ignore` and bare `except`

---

## Recommendations

### High Priority
1. **Fix hybrid_retriever.py:** Remove `# type: ignore` comments by adding proper types
2. **Fix test_hybrid_retriever.py:** Correct broken test logic (don't mock the method being tested)
3. **Add tests for hybrid_retriever.py:** Currently only 24% coverage

### Medium Priority
4. **Clean up graph_extractor.py comments:** Remove redundant inline comments
5. **Remove unused import:** `NODE_PROPERTIES` from graph_extractor.py
6. **Add docstrings:** Document methods in hybrid_retriever.py

### Low Priority
7. **Increase graph_schema.py coverage:** Add tests for validate_node function
8. **Address pre-existing issues:** Consider fixing bare except blocks in parser.py and embedder.py

---

## Final Verdict

**BUILD: PASS | LINT: PASS | TESTS: 128/141 PASS | COVERAGE: 71% | FILES: 2/4 CLEAN | VERDICT: NEEDS WORK**

The new modules are mostly well-implemented but require:
1. Fix to test logic in test_hybrid_retriever.py
2. Better type annotations in hybrid_retriever.py (remove type: ignores)
3. More comprehensive tests for hybrid_retriever.py (currently only 24% coverage)
4. Minor cleanup in graph_extractor.py (remove redundant comments, unused import)
