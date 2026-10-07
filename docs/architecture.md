# Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Scanner   │────▶│   Parser    │────▶│   Chunker   │
│  (discover  │     │(Tree-sitter │     │(model-aware │
│   JS/TS)    │     │ + metadata) │     │+ sliding)   │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                                │
                       ┌─────────────┐          │
                       │    Store    │◀─────────┤
                       │  (Qdrant)   │    ┌─────┴──────┐
                       └─────────────┘    │  Embedder   │
                                          │(Nomic/Jina) │
                       ┌─────────────┐    └─────────────┘
                       │  GraphStore │◀─── Graph Extractor
                       │   (Neo4j)   │    (AST ontology)
                       └─────────────┘
                              │
                     ┌────────┴────────┐
                     │ Hybrid Retriever│
                     │  (RRF fusion)   │
                     └────────┬────────┘
                              │
                    ┌─────────┴─────────┐
                    │    MCP Server     │
                    │  (search_code,    │
                    │   check_health)   │
                    └───────────────────┘
```

## Pipeline Flow

1. **Scan**: Discover all JS/TS files (excludes `node_modules`, `.git`, etc.)
2. **Parse**: Parse each file with Tree-sitter, strip comments, extract AST metadata
3. **Chunk**: Create overlapping, token-aware chunks (400 tokens, 64 overlap, line-based, never mid-line)
4. **Embed**: Generate embeddings using the selected model (Nomic: 3584-dim, no prefixes; Jina: 1536-dim with task prefixes)
5. **Store**: Upsert chunks into Qdrant with full metadata
6. **Graph Extract**: Extract code ontology entities (Files, Classes, Functions, Methods, Fields, Variables, Imports, Interfaces, TypeAliases) and relationships (CALLS, IMPORTS, INHERITS, CONTAINS, REFERENCES, etc.)
7. **Glossary Enrich**: Attach manual glossary entries and nearby comments/JSDoc to matching symbols with `HAS_GLOSSARY`
8. **Graph Store**: Upsert nodes and relationships into Neo4j



## Embedding Models

Two models, selectable via `--model`, each with its own Qdrant collection.
See [Embedding Models](models.md) for dimensions, precision and prefix behaviour.

## Chunking Strategy

- **Chunk Size**: 400 tokens (default, configurable via `--chunk-size`)
- **Overlap**: 64 tokens (configurable via `--chunk-overlap`)
- **Line-based**: Never splits mid-line; if a single line exceeds chunk size, it's split at token boundaries
- **Token limit**: 512 tokens per embedding input (model max)

## Hybrid Retrieval (RRF)

Hybrid search combines vector similarity with graph traversal using **Reciprocal Rank Fusion**:

```
fused_score = (vector_weight / (k + vector_rank)) + (graph_weight / (k + graph_rank))
```

Default weights: vector=0.7, graph=0.3, k=60.

## Metadata Stored Per Chunk

Each vector in Qdrant includes indexed payload fields: `file_path`, `language`, `start_line`, `end_line`, `chunk_index`, `function_name`, `class_name`, `parent_function`, `imports`, `exports`, `symbols_defined`, `call_sites`, `is_exported`, `visibility`, `decorators`, `file_hash`, `text_content`, `node_type`, `nesting_depth`, `token_count`.

## Collection Naming

Collection names are auto-generated from the base name + model + dimensions:
- Nomic: `code_chunks_nomic-embed-code_3584`
- Jina: `code_chunks_jina-code-embeddings-1.5b_1536`

