# Draft: Code Vector Graph - Impact Analysis Enhancement

## Requirements (confirmed)
- Transform semantic search engine into dependency graph engine
- Extract AST metadata (imports, exports, call_sites, symbols_defined, class_name, node_type, is_exported, visibility, decorators)
- Pass metadata through pipeline: parser → chunker → store
- Add file hashing for incremental updates
- Add Qdrant payload indexes for efficient filtering
- Fix critical global state bug in parser.py
- Fix bare exception handling in parser.py
- All implementations follow the IMPLEMENTATION_GUIDE.md exactly

## Technical Decisions
- Follow IMPLEMENTATION_GUIDE.md as specification (user-provided)
- Fix global state bug first (Phase 0) - threading/parallel safety
- Add `extract_ast_metadata()` function to parser.py
- Update `parse_file()` to parse tree once and return both stripped text + tree
- Add `strip_comments_with_tree()` to avoid double-parsing
- Update `chunk_text()` signature with many new keyword params for impact metadata
- Add `compute_file_hash()` to scanner.py
- Add payload indexes + deterministic UUID5 with file_hash to store.py
- Update main.py pipeline to pass AST metadata through all stages

## Research Findings
- Parser has `_LAST_SOURCE_BYTES` global at line 31, used in `strip_comments` (line 155-156) and `extract_function_name` (line 168-171)
- `parse_file()` currently returns dict with keys: stripped_text, original_line_count, stripped_line_count, line_mapping
- `chunk_text()` current signature: text, start_line, end_line, chunk_size, chunk_overlap, function_name, file_path, language, total_chunks
- Current chunk metadata has: file_path, language, start_line, end_line, chunk_index, function_name, total_chunks
- `discover_files()` returns dicts with: path, extension, language, grammar (NO file_hash currently)
- `compute_file_hash` does NOT exist yet
- VectorStore has NO payload indexes currently
- `_generate_deterministic_id()` currently uses `file_path:chunk_index` (no file_hash)
- Test infrastructure: pytest with test files for all modules (test_parser.py, test_chunker.py, test_scanner.py, test_store.py, test_embedder.py, test_integration.py)
- main.py imports from src.cli for argument parsing, uses src.config constants

## Scope Boundaries
- INCLUDE: All 5 phases from IMPLEMENTATION_GUIDE.md (9 tasks)
- INCLUDE: Bug fixes, AST metadata, chunker updates, file hashing, Qdrant indexes, pipeline update
- EXCLUDE: Phase 5 query examples (these are usage examples, not implementation tasks)
- EXCLUDE: Performance optimization suggestions (parallel processing, etc.) - out of scope
- EXCLUDE: New CLI commands or API endpoints
- EXCLUDE: Graph database integration (guide mentions but says "consider" only)

## Open Questions
- None - the IMPLEMENTATION_GUIDE.md is very specific and complete

## Test Strategy Decision
- **Infrastructure exists**: YES (pytest in requirements.txt, tests/ directory)
- **Automated tests**: YES (Tests-after) - existing tests must pass, new tests for new functionality
- **Agent-Executed QA**: ALWAYS - every task will have QA scenarios