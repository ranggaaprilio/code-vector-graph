# tests/ - AGENTS.md

**Generated:** 2025-01-09

## OVERVIEW

pytest-based test suite. Mix of class-based and function-based tests.

## STRUCTURE

```
tests/
├── test_*.py       # One per src module + integration
├── fixtures/       # JS/TS/TSX sample files
└── __init__.py     # Empty marker
```

## TEST PATTERNS

**Class-Based:**
```python
class TestScannerDiscovery:
    def test_discovers_js_files(self):
        results = discover_files(FIXTURES_DIR)
        assert any("sample.js" in p for p in paths)
```

**Function-Based:**
```python
def test_js_comment_stripping():
    result = parser.parse_file(path, "javascript")
    assert result is not None
```

**Convention:**
```python
FIXTURES_DIR = Path(__file__).parent / "fixtures"
```

## WHERE TO LOOK

| File | Tests |
|------|-------|
| `test_scanner.py` | File discovery, SKIP_DIRS |
| `test_parser.py` | Tree-sitter, comment stripping |
| `test_chunker.py` | BERT tokenization |
| `test_embedder.py` | Ollama + HuggingFace mocks |
| `test_store.py` | Qdrant upserts |
| `test_integration.py` | Full pipeline |

## CONVENTIONS

- **Naming:** `test_*.py`, `test_*` functions, `Test*` classes
- **Mocking:** `unittest.mock.patch` and `MagicMock`
- **Temp files:** `tmp_path` fixture
- **Exceptions:** `pytest.raises(ValueError, match="...")`
- **Fixtures:** `fixtures/` dir for JS/TS samples

## COMMANDS

```bash
python -m pytest tests/ -v
python -m pytest tests/ --cov=src --cov-report=term-missing
python -m pytest tests/test_integration.py -v  # Needs services
```

## NOTES

- No `conftest.py` or `pytest.ini`
- Integration tests require Ollama + Qdrant running
