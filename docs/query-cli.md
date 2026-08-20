# Query CLI (`cvg-query`)

Ask questions about your indexed code using retrieval + OpenAI (`gpt-4o-mini`):

```bash
# Requires OPENAI_API_KEY in your .env
cvg-query --question "How does authentication work?"

# Hybrid retrieval (vector + graph with RRF fusion)
cvg-query --question "Where is the database connection established?" --retrieval hybrid

# Filter by language or file pattern
cvg-query --question "What API routes exist?" --language typescript --file-pattern "src/routes/*"

# Expand query with code-specific synonyms
cvg-query --question "What functions handle errors?" --expand-query

# Graph-only traversal
cvg-query --question "class UserService" --retrieval graph
```

#### Query CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `--question` | *required* | Your question about the code |
| `--retrieval` | `vector` | Retrieval mode: `vector` (default), `hybrid` (vector+graph RRF), `graph` (Neo4j traversal) |
| `--top-k` | `20` | Number of code chunks to retrieve |
| `--language` | *none* | Filter: `javascript`, `typescript`, `tsx` |
| `--file-pattern` | *none* | Filter by file path glob |
| `--min-score` | `0.0` | Minimum similarity score (0.0–1.0) |
| `--expand-query` | `false` | Expand query with code synonyms |
| `--vector-weight` | `0.7` | Vector weight in hybrid mode |
| `--graph-weight` | `0.3` | Graph weight in hybrid mode |
| `--neo4j-uri` | `bolt://localhost:7687` | Neo4j bolt URI |
| `--neo4j-user` | `neo4j` | Neo4j username |
| `--neo4j-password` | `testpassword` | Neo4j password |

