Summary of changes:
- Updated main.py to wire AST metadata from the scanner/parser/tree into the chunking step.
- Imported extract_ast_metadata from src.parser and used it to enrich chunk metadata with imports, exports, symbols_defined, and more.
- Propagated file_hash from file discovery into chunk metadata for idempotent storage.
- Ensured the dry-run workflow remains intact (no embedding or storage during dry-run).

Rationale:
- Enables richer search indexing by maintaining granular code metadata per chunk (imports, exports, etc.).
- Keeps compatibility with existing storage and embedding layers; no breaking changes to embedder or store APIs.

Notes:
- AST metadata extraction runs only after successful parsing of a file and is then threaded into chunk_text calls.
- The flattening step remains compatible with the expanded metadata set.
