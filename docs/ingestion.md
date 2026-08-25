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
| `--repo-name` | *directory name* | Repository name recorded on every chunk and node |
| `--app-name` | *derived* | Application the repository belongs to (default: first component under `CVG_REPOS_ROOT`, else the repo name) |
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


## Indexing an application made of several repositories

An application can span repositories. Index each one, giving them the same
`--app-name` so the dashboard groups them:

```bash
cvg-ingest --repo-path ~/Repository/onebid/backend/backend_nodejs_global_tnlm \
  --app-name onebid --verbose
cvg-ingest --repo-path ~/Repository/onebid/backend/backend_nodejs_data_sync_onebid \
  --app-name onebid --verbose
```

Both go into the same collection and graph; the `app`/`repo` fields keep them
distinguishable, and every chunk also carries `repo_root` and `rel_path`. Setting
`CVG_REPOS_ROOT=~/Repository` in `.env` makes `--app-name` unnecessary — the
component after the root (`onebid`) becomes the application name.

## Backfilling repositories indexed earlier (`cvg-backfill-repo`)

Data indexed before `app`/`repo` existed has neither. The dashboard still works —
it derives the layout from file-path prefixes — but nothing is stored, so Qdrant
cannot filter on it. `cvg-backfill-repo` writes the identity in place, **without
re-embedding anything** (no model load, no API calls):

```bash
cvg-backfill-repo --dry-run     # print the app -> repo -> root plan and stop
cvg-backfill-repo               # apply it
```

It sets `app`/`repo`/`repo_root` on Qdrant payloads (resolving OKF wiki points
through their `symbol_id` in Neo4j), sets `app`/`repo`/`rel_path` on `File`
nodes, creates the `Application`/`Repository` nodes with their `CONTAINS` edges,
and propagates `repo` to `Chunk` and `WikiPage` nodes. Every step is guarded by
`WHERE repo IS NULL`, so re-running it is a no-op.

| Option | Default | Description |
|--------|---------|-------------|
| `--repos-root` | `CVG_REPOS_ROOT` | Directory whose first child component names the application |
| `--map NAME=ROOT` | *none* | Explicit repository root; repeatable, merged over `CVG_REPO_MAP` |
| `--app NAME=REPO,REPO` | *none* | Explicit application grouping; repeatable, merged over `CVG_APP_MAP` |
| `--wiki-repo` | *none* | Repository for wiki points that cannot be resolved through Neo4j |
| `--collection-name` | *active collection* | Base Qdrant collection name |
| `--no-qdrant` / `--no-neo4j` | `false` | Skip one half |
| `--batch-size` | `500` | Paths/points per write |
| `--dry-run` | `false` | Print the plan; write nothing |

Check the plan before applying it — if the heuristic splits or merges the wrong
directories, correct it with `--map`/`--app` rather than fixing payloads by hand
afterwards. Afterwards, refresh the dashboard's cache with
`POST /api/apps/refresh` (or just wait for `CVG_APPS_CACHE_TTL`).
