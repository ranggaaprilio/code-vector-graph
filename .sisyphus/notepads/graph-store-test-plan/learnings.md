What I learned:
- Added tests/test_graph_store.py to drive TDD for a Neo4j GraphStore interface.
- Tests rely on mocking the neo4j GraphDatabase driver using unittest.mock.patch.
- The tests verify that MERGE is used (not CREATE) and that UNWIND/MERGE patterns are present for upserts.
- Currently, test collection fails because src.graph_store is not yet implemented. This confirms the GraphStore API contract must be provided before tests can pass.
