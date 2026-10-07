# OKF LLM Wiki

Generate a human-readable, cross-linked **wiki** of your codebase — in the spirit of Andrej Karpathy's "LLM wiki" and DeepWiki — stored in Google Cloud's **Open Knowledge Format (OKF v0.1)**: a directory ("bundle") of Markdown files with YAML frontmatter, where each `.md` file is one concept (a File, Class, Function, …) and Markdown links between files are the relationships. An LLM (**DeepSeek**) reads the source and writes plain-language explanations per concept; a second step syncs that wiki into Qdrant and Neo4j.

```
                    ┌── cvg-okf-build ──┐          ┌── cvg-okf-sync ──┐
source code ──▶ skeleton (Tree-sitter) ──▶ DeepSeek enrichment ──▶ OKF bundle ──┬──▶ Qdrant (embedded prose, source="okf_wiki")
                                                                                 └──▶ Neo4j  (WikiPage nodes + DOCUMENTS/REFERENCES)
```

The two steps are independent: **build** needs only the repo + a DeepSeek key (no databases); **sync** needs Qdrant/Neo4j running but no LLM.

## Prerequisites

The enrichment LLM is selected by `OKF_LLM_PROVIDER` in your `.env` (see setup step 4). Two providers are supported; both speak the OpenAI chat-completions protocol, so the rest of the pipeline is identical.

### Option A — DeepSeek (cloud, default)

```bash
# .env (defaults shown — only DEEPSEEK_API_KEY is required)
DEEPSEEK_API_KEY=sk-...
# OKF_LLM_PROVIDER=deepseek
# DEEPSEEK_BASE_URL=https://api.deepseek.com
# OKF_MODEL_FLASH=deepseek-v4-flash   # concept pages
# OKF_MODEL_PRO=deepseek-v4-pro       # repo architecture overview
```

### Option B — oMLX (local, offline)

Run the wiki generation entirely on your Mac with an [oMLX](https://github.com/jundot/omlx) server and an MLX model such as Gemma or Qwen. No data leaves the machine and there is no per-token cost; the trade-off is speed (a few seconds per concept on an 8-GB-class model) and somewhat terser prose from small models.

```bash
# .env
OKF_LLM_PROVIDER=omlx
OMLX_BASE_URL=http://localhost:8000/v1      # oMLX default host/port
OMLX_API_KEY=...                            # from the oMLX menu-bar app → Settings → API key
OMLX_MODEL=gemma-4-e2b-it-4bit              # a folder name under ~/.omlx/models
# OKF_MODEL_PRO=Qwen3-8B-4bit               # optional: a bigger model for the overview page
# OKF_CONCURRENCY=2                         # default for omlx (deepseek: 6)
```

Check which model ids the server exposes:

```bash
curl -s -H "Authorization: Bearer $OMLX_API_KEY" http://localhost:8000/v1/models | jq '.data[].id'
```

Notes for local models:

- `cvg-okf-build` probes the server on startup and fails fast if it is down, the key is wrong, or the model id is not served — so a misconfiguration never silently produces metadata-only pages.
- Thinking mode is disabled per request (`chat_template_kwargs.enable_thinking=false`), which matters for Qwen3; Gemma ignores it.
- The feature-docs mapper sends up to `OKF_FEATURE_MAP_MAX_CHARS` (60k chars) of file inventory in one prompt. If your model's context window is small (oMLX defaults to 32k tokens), lower it, e.g. `OKF_FEATURE_MAP_MAX_CHARS=30000`.
- The incremental cache (`.okf-cache.json` in the bundle) is keyed by content only, so switching providers reuses pages already written by the other one; pass `--force` to regenerate everything with the new model.

## Step 1 — Build the wiki (`cvg-okf-build`)

```bash
# Preview first — builds the bundle with metadata-only pages, no LLM calls:
cvg-okf-build --repo-path ./my-project --dry-run --verbose

# Real run (needs DEEPSEEK_API_KEY, or OKF_LLM_PROVIDER=omlx + a running oMLX server). Start small to gauge cost/speed:
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
| `--model-flash` | `OKF_MODEL_FLASH` (`deepseek-v4-flash`, or `OMLX_MODEL` for omlx) | Model for concept pages |
| `--model-pro` | `OKF_MODEL_PRO` (`deepseek-v4-pro`, or `OMLX_MODEL` for omlx) | Model for the repo architecture overview |
| `--concurrency` | `6` | Concurrent enrichment requests |
| `--labels` | *File,Class,Function,Method,Interface,TypeAlias* | Comma-separated node labels to enrich |
| `--exclude-labels` | *Import,Variable,Field,…* | Comma-separated labels to exclude |
| `--repo-base-url` | *none* | Base URL for `resource` links (e.g. a GitHub blob URL) |
| `--repo-root` | `--repo-path` | Path prefix stripped from `resource` |
| `--limit` | *none* | Cap the number of concepts (smoke tests) |
| `--force` | `false` | Ignore the incremental cache; re-enrich everything |
| `--dry-run` | `false` | Build metadata-only pages; make no LLM calls |
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

## Feature docs

On top of the per-symbol wiki above, `ingestion/okf/features/` generates coarser, **business-logic** documentation: one validated Markdown page per *feature* (a cluster of files that together implement a piece of business functionality — "Order Checkout", "User Authentication" — not a single file). It's a two-stage LLM process: first group the repo's files into features (`discover_features`), then write one page per feature (`generate_feature_doc`) covering Overview, Business Rules, Process Flow, Key Entities & Data, Entry Points, Dependencies & Integrations, Edge Cases & Error Handling, and Open Questions — always in that order, always structurally validated (`validate_feature_body`) before it's stored.

- **Generate**: `cvg-ingest --docs` (runs right after indexing, reusing the just-loaded embedder/stores) or standalone `cvg-docs-build --repo-path <repo> [--app-name <app>] [--only slug,slug]`. `scripts/run_mac_mps_24gb.sh` runs it by default (`ENABLE_DOCS=1`); also triggerable from the dashboard's Docs tab ("Generate docs" button).
- **Storage**: Neo4j `WikiPage {type:"Feature"}` nodes (same label as the per-symbol wiki, so the existing wiki tooling picks them up for free), linked to their member code nodes via `IMPLEMENTED_BY` and to their `Repository` via `DOCUMENTS`. Prose is embedded into the same Qdrant collection as the code (`source="okf_wiki"`, `kind="Feature"`). The bundle's `feature/<slug>.md` files are an export/preview, not the source of truth.
- **Editable, and edits are never overwritten.** The dashboard's Docs tab lets you edit a feature page directly. Once a page is human-edited (`source: human`), later `cvg-docs-build`/`cvg-ingest --docs` runs never touch its content again — they only refresh which files currently implement it and recompute staleness: if the code has drifted since the edit, the page is marked `stale` (with a "Regenerate draft" action that proposes a fresh AI draft without applying it) rather than silently overwritten.
- **Language**: prose language is controlled by `CVG_DOCS_LANGUAGE` (default `en`).

See `ingestion/okf/features/template.py` for the exact template/validator rules and `api/routers/docs.py` for the `/api/apps/{app}/docs*` endpoints.

## Manual documents

Alongside the LLM-generated Feature pages above, the Docs tab lets anyone add a **manually-authored Document**: free-form Markdown (only an `# H1` title is required — no fixed section template), created directly in the dashboard or pasted from a `.md` file in the standalone [Editor](dashboard.md) page's "Save to Docs…" panel.

- **Storage**: same `WikiPage` label, `type:"Document"` instead of `type:"Feature"`. Linked to its `Repository` (or, for an app-level document with no repo chosen, its `Application`) via `DOCUMENTS`, and to every file path it mentions — auto-detected from inline `` `backtick` `` spans and Markdown link targets in the body — via `MENTIONS` edges (shown as "Mentions" chips in the dashboard, next to the equivalent "Implemented by" chips on a Feature page). Prose is embedded into the same Qdrant collection as Feature pages and code (`source: "okf_wiki"`, `kind: "Document"`), so it's retrieved by Vectors search and AI Chat with no extra configuration.
- **Never touched by builds.** `cvg-docs-build`/`cvg-ingest --docs`/"Generate docs" only ever load and (re)generate `type:"Feature"` pages — a Document is exclusively created, edited, reindexed, and deleted through its own dashboard actions (or the `POST`/`PUT`/`POST .../reindex`/`DELETE` endpoints in `api/routers/docs.py`).
- **Indexing runs as a background job**, same mechanism as "Generate docs" (`api/services/docs_jobs.py`), so creating, editing, or reindexing a Document shows a live stage-by-stage progress panel (saving to the graph → linking mentions → embedding → writing vectors → mirroring to the bundle) rather than blocking the request. If no embedder is configured on the server (`CVG_API_EMBEDDER=off`, or the model failed to load), the job still completes and the page is flagged `needs_reembed` with a "Search index pending" badge — click **Reindex** once an embedder is available to catch it up.
- **Bundle mirror**: like Feature pages, a Document is best-effort mirrored to `<bundle>/document/<slug>.md` when the OKF bundle directory exists on this host — an export/preview only, not re-imported by `cvg-okf-sync`; Neo4j remains the source of truth.

See `ingestion/okf/features/documents.py` for the Neo4j/Qdrant IO (mirrors `features/store.py`'s Feature-page functions) and `ingestion/okf/features/validate.py:validate_document_body` for the (much looser than Feature pages') structural checks: closed code fences, no raw HTML outside a fence, and a size cap — no required sections.

