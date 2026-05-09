Title: GraphStore Neo4j ingestion implementation learnings

- Implemented src/graph_store.py providing a GraphStore class that uses the Neo4j5+ driver via driver.execute_query() per tests.
- Core methods implemented: check_health, create_constraints, upsert_nodes, upsert_relationships, query_graph, get_related_nodes, close.
- Constraints created per label from NODE_LABELS with id uniqueness using the CREATE CONSTRAINT ... IF NOT EXISTS pattern. Tests verify presence of CREATE CONSTRAINT and IS UNIQUE.
- Node upserts group by label and perform MERGE with per-label Cypher to ensure idempotent upserts; properties are set via SET n += item.properties.
- Relationships upserts executed in batches with UNWIND, MATCH, MERGE (s)-[:REL_TYPE]->(t) and property updates via SET r += item.properties.
- Implemented query_graph to return the raw result, as tests assert exact call signature.
- get_related_nodes uses a depth-bounded traversal with MATCH path and returns related nodes via relationships(path).
- All tests in tests/test_graph_store.py pass (GREEN phase) for the new implementation.

- Next: consider additional tests for edge cases such as labels not in NODE_LABELS, empty inputs, and error handling during ingestion.
