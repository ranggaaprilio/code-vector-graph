# OKF LLM Wiki

Generate a human-readable, cross-linked **wiki** of your codebase — in the spirit of Andrej Karpathy's "LLM wiki" and DeepWiki — stored in Google Cloud's **Open Knowledge Format (OKF v0.1)**: a directory ("bundle") of Markdown files with YAML frontmatter, where each `.md` file is one concept (a File, Class, Function, …) and Markdown links between files are the relationships. An LLM (**DeepSeek**) reads the source and writes plain-language explanations per concept; a second step syncs that wiki into Qdrant and Neo4j.

```
                    ┌── cvg-okf-build ──┐          ┌── cvg-okf-sync ──┐
source code ──▶ skeleton (Tree-sitter) ──▶ DeepSeek enrichment ──▶ OKF bundle ──┬──▶ Qdrant (embedded prose, source="okf_wiki")
                                                                                 └──▶ Neo4j  (WikiPage nodes + DOCUMENTS/REFERENCES)
```

The two steps are independent: **build** needs only the repo + a DeepSeek key (no databases); **sync** needs Qdrant/Neo4j running but no LLM.

## Prerequisites

Set `DEEPSEEK_API_KEY` in your `.env` (see setup step 4). DeepSeek is OpenAI-compatible; the base URL and models are configurable:

```bash
# .env (defaults shown — only DEEPSEEK_API_KEY is required)
DEEPSEEK_API_KEY=sk-...
# DEEPSEEK_BASE_URL=https://api.deepseek.com
# OKF_MODEL_FLASH=deepseek-v4-flash   # concept pages
# OKF_MODEL_PRO=deepseek-v4-pro       # repo architecture overview
```

## Step 1 — Build the wiki (`cvg-okf-build`)

```bash
# Preview first — builds the bundle with metadata-only pages, no DeepSeek calls:
cvg-okf-build --repo-path ./my-project --dry-run --verbose

# Real run (needs DEEPSEEK_API_KEY). Start small to gauge cost:
cvg-okf-build --repo-path ./my-project --limit 20 --verbose

# Full repo, with GitHub links in each page's `resource` field:
cvg-okf-build \
  --repo-path ./my-project \
  --out-dir okf-wiki \
  --repo-base-url https://github.com/your-org/my-project/blob/main \
  --verbose
```

Open `okf-wiki/` in any editor, Obsidian, or GitHub (each `.md` renders with working links), or load the bundle in Google's OKF reference HTML visualizer. Re-runs are **incremental**: an `.okf-cache.json` in the bundle keys each concept by content hash, so unchanged files are skipped and only changed code is re-enriched (use `--force` to re-enrich everything).

#### `cvg-okf-build` Options

| Option | Default | Description |
|--------|---------|-------------|
| `--repo-path` | `.` | Repository to document |
| `--repo-name` | *directory name* | Repository name recorded in page frontmatter and the root index |
| `--app-name` | *repo name* | Application this repository belongs to (e.g. `onebid` for a repo that is one of several backend services) |
| `--out-dir` | `okf-wiki` | Output bundle directory |
| `--model-flash` | `deepseek-v4-flash` | Model for concept pages |
| `--model-pro` | `deepseek-v4-pro` | Model for the repo architecture overview |
| `--concurrency` | `6` | Concurrent enrichment requests |
| `--labels` | *File,Class,Function,Method,Interface,TypeAlias* | Comma-separated node labels to enrich |
| `--exclude-labels` | *Import,Variable,Field,…* | Comma-separated labels to exclude |
| `--repo-base-url` | *none* | Base URL for `resource` links (e.g. a GitHub blob URL) |
| `--repo-root` | `--repo-path` | Path prefix stripped from `resource` |
| `--limit` | *none* | Cap the number of concepts (smoke tests) |
| `--force` | `false` | Ignore the incremental cache; re-enrich everything |
| `--dry-run` | `false` | Build metadata-only pages; make no DeepSeek calls |
| `--verbose` | `false` | Verbose logging |

#### Bundle layout

```
okf-wiki/
├── index.md          # root: okf_version + architecture overview + per-type index
├── log.md            # generation timestamp, model tiers, counts
├── file/    index.md + <slug>-<hash>.md
├── class/   function/  method/  interface/  typealias/   # one dir per concept type
└── .okf-cache.json   # incremental cache (safe to delete to force a full rebuild)
```

Each concept page has YAML frontmatter (`type`, `title`, `description`, `resource`, `tags`, …) and body sections (`# Summary`, `# Overview`, `# How it works`, `# Parameters`, `# Relationships`). Relationships are grouped Markdown links under `## Calls`, `## Contains`, `## Inherits`, `## Imports`, and `## Related`.

## Step 2 — Sync the wiki into Qdrant + Neo4j (`cvg-okf-sync`)

Requires Qdrant and Neo4j running (`docker-compose up -d`):

```bash
# Preview what would be written (no DB writes):
cvg-okf-sync --bundle okf-wiki --dry-run

# Sync into both stores:
cvg-okf-sync --bundle okf-wiki --verbose

# Graph only (no embedder needed):
cvg-okf-sync --bundle okf-wiki --no-qdrant
```

- **Qdrant**: each page's prose is embedded and upserted into a dedicated `okf_wiki_<model>_<dims>` collection, tagged `source="okf_wiki"` so it's distinguishable from code chunks.
- **Neo4j**: one `WikiPage` node per concept, linked to the code node it documents via `DOCUMENTS` (the `WikiPage` shares the documented node's id), and to other pages via `REFERENCES` (the LLM's "Related" links). Run the main indexer (`cvg-ingest`) first so the code nodes exist for `DOCUMENTS` edges to attach to. The bundle's root `index.md` (type `Repository`) is synced too — it becomes the `WikiPage` the dashboard's Application Overview tab shows for that repository, `DOCUMENTS`-linked to the `Repository` node `cvg-ingest`/`cvg-backfill-repo` created.

Browse the result in Neo4j:

```cypher
MATCH (w:WikiPage)-[:DOCUMENTS]->(n) RETURN w, n LIMIT 25
```

#### `cvg-okf-sync` Options

| Option | Default | Description |
|--------|---------|-------------|
| `--bundle` | `okf-wiki` | OKF bundle directory to sync |
| `--no-qdrant` | `false` | Skip the Qdrant sync |
| `--no-neo4j` | `false` | Skip the Neo4j sync |
| `--model` | `nomic` | Embedding model for the prose (`nomic` or `jina`) |
| `--qdrant-url` | `http://localhost:6333` | Qdrant server URL |
| `--collection-name` | `okf_wiki` | Base Qdrant collection name (model + dims appended) |
| `--collection-name-is-final` | `false` | Use `--collection-name` verbatim (no suffixing) |
| `--neo4j-uri` / `--neo4j-user` / `--neo4j-password` | *localhost defaults* | Neo4j connection |
| `--batch-size` | `64` | Embedding batch size |
| `--dry-run` | `false` | Parse the bundle and report; make no writes |
| `--verbose` | `false` | Verbose logging |

> **Note**: the embedder is a *code* model (Nomic/Jina). Embedding natural-language wiki prose works, but is a slight NL/code mismatch — retrieval quality is best treated as a POC. The wiki vectors live in their own collection, so they don't affect code-chunk search.

