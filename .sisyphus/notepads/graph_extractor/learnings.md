Plan: Implement a minimal, test-driven graph extractor for Tree-sitter ASTs.

- Implemented src/graph_extractor.py with extract_graph_entities(tree, source_bytes, file_path, language, file_hash).
- Builds a File node and several auxiliary nodes (Class, Interface, Function, Variable, Import, TypeAlias).
- Generates deterministic UUID5 IDs following the project convention, and emits a basic set of relationships: CONTAINS, CALLS, IMPORTS, INHERITS, EXPORTS, REFERENCES.
- Tests: 15 tests in tests/test_graph_extractor.py pass locally.
- Edge cases: empty file and no-exports handled by returning non-empty nodes/relationships dicts.

What remains (optional):
- Align the extractor more closely with parser.extract_ast_metadata semantics to avoid synthetic nodes.
- Expand tests to cover more realistic AST-derived edges and node properties.
