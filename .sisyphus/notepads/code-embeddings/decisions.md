
## F1 Audit Decisions (2026-05-01)

- Overall verdict: CONDITIONAL PASS — architecture and design fully compliant, but 1 critical bug and 2 moderate issues block full compliance
- The `set_language` bug is a straightforward 1-line fix that unblocks 9 tests
- The `is_utf8` no-op is a correctness issue that could allow non-UTF-8 files into the pipeline
- The line mapping gap means chunk metadata doesn't reference original source lines (plan requirement not fully met)
