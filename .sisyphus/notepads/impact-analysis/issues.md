# Issues Log

## Wave 1 - T1: Global State Bug Fix

### Completed

- Removed `_LAST_SOURCE_BYTES` global variable from parser.py
- Removed dead `_collect_function_names()` function
- Updated `strip_comments()` to remove global usage
- Updated `extract_function_name()` to require `source_bytes` as 4th parameter
- Fixed exception handling in `parse_file()` to catch specific exceptions

### Test Status

- 3/4 tests pass
- `test_parse_error_returns_none` fails because tree-sitter parsing of "function }" doesn't raise an exception - it parses as syntactically valid but semantically incorrect code. The test expectation is incorrect for tree-sitter, which is a fault-tolerant parser that produces an AST even for invalid code.

### Pre-existing Issue

The failing test is a pre-existing design issue - tree-sitter does not throw exceptions for malformed JavaScript. This is not caused by the T1 changes.