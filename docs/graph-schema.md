# Code Ontology (Neo4j Graph)

## Node Types

| Label | Description | Key Properties |
|-------|-------------|----------------|
| `File` | Source file | path, language, file_hash, imports, exports, repo, app, rel_path |
| `Module` | ES module | name, path, is_package |
| `Class` | Class declaration | name, start_line, end_line, is_exported, visibility, decorators, parent_class |
| `Function` | Function declaration | name, start_line, end_line, is_async, parameters, call_sites, decorators |
| `Method` | Class method | name, parent_class, is_async, parameters, call_sites |
| `Field` | Class field/property | name, parent_class, type_annotation, visibility |
| `Variable` | Variable declaration | name, is_constant, type_annotation, visibility |
| `Import` | Import statement | module, names, is_wildcard |
| `Interface` | TypeScript interface | name, extends |
| `TypeAlias` | TypeScript type alias | name, type_expression |
| `Chunk` | Code chunk (linked to Qdrant) | qdrant_id, file_path, start_line, end_line, token_count, repo |
| `GlossaryEntry` | Manual or comment-derived term explanation | term, kind, summary, source, confidence, symbol_id |
| `WikiPage` | OKF LLM-wiki page documenting a code node | concept_id, path, type, title, summary, overview, how_it_works, tags, resource, source, repo, app |
| `Application` | A product made of one or more repositories | name |
| `Repository` | One indexed repository | name, root, app, indexed_at |

## Relationship Types

| Type | Description |
|------|-------------|
| `CONTAINS` | File contains class/function/variable; also `Application`→`Repository`→`File` |
| `CALLS` | Function calls another function |
| `IMPORTS` | File/module imports from another |
| `INHERITS` | Class extends another class |
| `EXPORTS` | File exports a symbol |
| `REFERENCES` | Symbol references another |
| `DEFINES` | Module defines a symbol |
| `TYPE_OF` | Type relationship |
| `DEPENDS_ON` | Module dependency |
| `HAS_GLOSSARY` | Symbol has a glossary explanation |
| `DOCUMENTS` | OKF `WikiPage` documents a code node |


## Application and repository identity

An **application** is a product; it may span several **repositories**. `onebid`, for
example, is one application made of `backend_nodejs_global_tnlm` and
`backend_nodejs_data_sync_onebid`. The dashboard uses this to scope search, graph
browsing and chat to one application (across its repos) or to a single repo.

```
(:Application {name:"onebid"})-[:CONTAINS]->(:Repository {name:"backend_nodejs_global_tnlm", root:"/…/onebid/backend/backend_nodejs_global_tnlm"})
                                              └─[:CONTAINS]->(:File {repo:"backend_nodejs_global_tnlm", rel_path:"src/main.ts"})
```

`cvg-ingest` records this from `--repo-name` / `--app-name` (defaults: the resolved
directory name, and the first path component under `CVG_REPOS_ROOT`).

### Legacy data

Repositories indexed before this existed have no `repo`/`app` property. Those
properties are **optional in the schema** (`OPTIONAL_NODE_PROPERTIES` in
`stores/graph_schema.py`), so old nodes stay valid, and the dashboard derives the
application layout from `File.path` prefixes at read time. To make it permanent
without re-embedding anything, run:

```bash
cvg-backfill-repo --dry-run     # print the app → repo → root plan
cvg-backfill-repo               # write repo/app onto Qdrant payloads and Neo4j nodes
```

Note that `cvg-reinit-graph --clear` deletes `Application`, `Repository` and
`WikiPage` nodes along with everything else; re-run `cvg-backfill-repo` (and
`cvg-okf-sync --no-qdrant` if you have a wiki) afterwards.

### Indexes

`GraphStore.create_constraints()` creates a uniqueness constraint on `id` for every
label, plus indexes on `File.repo`, `File.app` and `WikiPage.repo` — the three
properties every scoped query filters on.
