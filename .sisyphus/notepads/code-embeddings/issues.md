
## F1 Plan Compliance Audit — Issues Found (2026-05-01)

### CRITICAL: Parser API Incompatibility (9 test failures)
- **File**: `src/parser.py` line 59-61
- **Bug**: Uses `parser.set_language(lang)` which is removed in tree-sitter v0.25.2
- **Fix**: Change to `Parser(lang)` constructor (modern API)
- **Impact**: All parser-dependent tests and integration tests fail

### MODERATE: is_utf8() is a no-op
- **File**: `src/scanner.py` lines 21-28
- **Bug**: Opens file in binary mode (`"rb"`), reads bytes, never decodes — `UnicodeDecodeError` can never be raised
- **Fix**: Change to `f.read(8192).decode("utf-8")` inside try block

### MODERATE: Line mapping not wired through to chunks
- **File**: `main.py` lines 148-149
- **Bug**: `chunk_text()` called with `start_line=1` (hardcoded) instead of using `parsed["line_mapping"]` to translate to original source lines
- **Impact**: Chunk metadata references stripped text line numbers, not original source lines as required by plan
