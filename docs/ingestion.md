# Ingestion (`cvg-ingest`)

```bash
cvg-ingest --repo-path /path/to/repo [OPTIONS]
```

## Dry Run (Preview Mode)

See what would be processed without generating embeddings:

```bash
cvg-ingest --repo-path /path/to/your/repo --dry-run
```

## Skip Graph Ingestion

```bash
cvg-ingest --repo-path /path/to/your/repo --no-graph
```

## Verbose Output

```bash
cvg-ingest --repo-path /path/to/your/repo --verbose
```

## Glossary Enrichment

By default, the pipeline looks for `glossary.yml` in the repository root. Missing glossary files are ignored.

```bash
cvg-ingest --repo-path /path/to/your/repo --glossary-file glossary.yml
```

Example `glossary.yml`:

```yaml
entries:
  - term: userId
    kind: variable
    file_path: src/auth/session.ts
    summary: Unique identifier for the authenticated user.
    source: manual

  - term: SessionManager
    kind: class
    file_path: src/auth/session.ts
    summary: Coordinates session lifecycle and token refresh behavior.
```

Supported `kind` values match graph symbols: `class`, `function`, `method`, `field`, `variable`, `interface`, and `type_alias`.

Manual entries take precedence over comments/JSDoc for the same `file_path + kind + term`. Comments immediately above a symbol are also extracted automatically:

```ts
/** Unique identifier for the authenticated user. */
const userId = session.user.id;
```

Glossary entries are stored as `GlossaryEntry` nodes in Neo4j, linked to symbols with `HAS_GLOSSARY`, and also indexed in Qdrant as `node_type="glossary_entry"` records for semantic search.

## Custom Configuration

```bash
cvg-ingest \
  --repo-path /path/to/repo \
  --qdrant-url http://localhost:6333 \
  --collection-name my_code_chunks \
  --chunk-size 400 \
  --chunk-overlap 64 \
  --batch-size 64 \
  --neo4j-uri bolt://localhost:7687 \
  --verbose
```

## CLI Options
| Option | Default | Description |
|--------|---------|-------------|
| `--repo-path` | *required* | Path to the repository to process |
| `--model` | `nomic` | Embedding model: `nomic` (3584-dim) or `jina` (1536-dim) |
| `--device` | `auto` | Compute device: `auto`, `mps`, `cuda`, or `cpu` |
| `--dtype` | `auto` | Model precision: `auto`, `float16`, `bfloat16`, `float32` (auto → bfloat16 on MPS) |
| `--qdrant-url` | `http://localhost:6333` | Qdrant server URL |
| `--collection-name` | `code_chunks` | Base Qdrant collection name (model suffix + dimensions appended automatically) |
| `--chunk-size` | `400` | Tokens per chunk |
| `--chunk-overlap` | `64` | Token overlap between chunks |
| `--batch-size` | `64` | Embedding batch size |
| `--glossary-file` | `glossary.yml` | Manual glossary YAML file path |
| `--no-graph` | `false` | Skip Neo4j graph ingestion |
| `--neo4j-uri` | `bolt://localhost:7687` | Neo4j bolt URI |
| `--neo4j-user` | `neo4j` | Neo4j username |
| `--neo4j-password` | `testpassword` | Neo4j password |
| `--dry-run` | `false` | Preview without embedding/storing |
| `--verbose` | `false` | Enable verbose (INFO-level) logging |

#### Examples

```bash
# Basic usage with default model (Nomic):
cvg-ingest --repo-path ./my-project --verbose

# Use Jina model:
cvg-ingest --repo-path ./my-project --model jina --verbose

# Dry run to preview what gets processed:
cvg-ingest --repo-path ./my-project --dry-run --verbose

# Skip Neo4j (vectors only, no graph):
cvg-ingest --repo-path ./my-project --no-graph

# Custom Qdrant and Neo4j:
cvg-ingest --repo-path ./my-project \
  --qdrant-url http://localhost:6333 \
  --neo4j-uri bolt://localhost:7687 \
  --neo4j-user neo4j \
  --neo4j-password mypassword

# Reduce memory for large repos:
cvg-ingest --repo-path /large/repo --batch-size 32
```

