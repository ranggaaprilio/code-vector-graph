# Architectural Decisions (Plan: graph extractor tests)
- Tests are written in a red-first style to define the contract for graph_extractor.py before implementation.
- We rely on existing parser output (parse_file) and plan to confirm via graph_schema.py that node/relationship shapes are correct.
- Do not modify parser.py or graph_schema.py in this phase; tests should specify expected contracts only.
