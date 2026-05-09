# Learnings from Graph Extractor TDD (Plan: graph extractor tests)

- Created tests/test_graph_extractor.py to outline RED-phase tests for graph_extractor.
- The tests reference the upcoming graph_extractor API (extract_graph_entities) and rely on existing fixtures (sample.ts, sample.js, component.tsx).
- Current status: graph_extractor.py not implemented yet; tests are designed to fail/predictable skip paths until implementation is provided.
- Next steps: implement graph_extractor.extract_graph_entities and align with graph_schema.py expectations; then run full verification (lsp_diagnostics, relevant tests, build).
