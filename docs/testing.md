# Testing

```bash
# Run the whole suite (testpaths=tests is set in pyproject.toml)
pytest

# One module
pytest tests/embeddings/test_embedder.py -v

# With coverage
pytest --cov=code_vector_graph --cov-report=term-missing
```

Tests mirror the package layout:

| Directory | Covers |
|---|---|
| `tests/parsing/` | scanner, parser, chunker, graph_extractor, glossary |
| `tests/stores/` | `vector_store` (Qdrant), `graph_store` (Neo4j) |
| `tests/retrieval/` | hybrid retrieval + RRF fusion |
| `tests/embeddings/` | embedder, model/dtype dispatch |
| `tests/ingestion/` | `reinit_graph`, and `okf/` for the wiki layer |
| `tests/test_integration.py` | end-to-end pipeline wiring |
| `tests/fixtures/` | JS/TS/TSX sample files (shared; resolved via `tests/conftest.py`) |

`tests/manual/` is **excluded from the default run** — those scripts download
real multi-GB models and hit live services. Run one explicitly when you want it:

```bash
pytest tests/manual/test_jina_embedder.py -v
```

## Known failing test

`tests/parsing/test_parser.py::test_parse_error_returns_none` fails, and has
since the initial commit. It asserts that `parse_file()` returns `None` for
syntactically invalid input, but that check was never implemented — Tree-sitter
is error-tolerant by design and returns a tree containing ERROR nodes rather
than raising. Whether the indexer *should* skip files with syntax errors is an
open question: doing so would also drop files using syntax the pinned grammar
does not recognise.
