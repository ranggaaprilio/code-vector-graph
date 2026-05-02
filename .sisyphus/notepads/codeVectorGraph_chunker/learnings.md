Change summary:
- Updated chunk_text signature to add 11 new parameters for richer chunk metadata and future analysis.
- Added nesting depth calculation (nesting_depth) after token counting pass.
- Extended chunk metadata in all chunk allocations to include fields: node_type, class_name, parent_function, imports, exports, symbols_defined, call_sites, is_exported, visibility, decorators, file_hash.
- Verified the function signature now exposes 20 parameters.

Notes:
- No tests were executed in this step. Consider adding unit tests to verify metadata propagation.
