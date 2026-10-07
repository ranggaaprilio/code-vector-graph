# Embedding Models

| Model ID | Full Name | Dimensions | Dtype | Task Prefixes | Default |
|----------|-----------|------------|-------|---------------|---------|
| `nomic` | `nomic-ai/nomic-embed-code` | 3584 | float16 (CUDA) / bfloat16 (MPS) / float32 (ROCm, CPU) | None | Yes |
| `jina` | `jinaai/jina-code-embeddings-1.5b` | 1536 | bfloat16 (CUDA, MPS) / float32 (ROCm, CPU) | `code2code` + `nl2code` | No |

Precision is auto-selected per device and can be overridden with `--dtype {auto,float16,bfloat16,float32}`. On Apple Silicon (MPS) the default is **bfloat16** — roughly half the memory and ~2x the throughput of float32, with float32's exponent range (no overflow/NaN risk). ROCm and CPU stay on float32.

- **Nomic** (default): Higher-dimensional (3584), no task prefixes needed, uses `float16` precision. Good general-purpose code embedding.
- **Jina**: Lower-dimensional (1536), prepends task-specific prefixes (`code2code` for code passages, `nl2code` for queries) to improve retrieval accuracy. Uses `bfloat16` precision.

Switch models with `--model`:
```bash
cvg-ingest --repo-path /path/to/repo --model nomic   # default
cvg-ingest --repo-path /path/to/repo --model jina
```

> **Important**: Each model creates a separate Qdrant collection (e.g., `code_chunks_nomic-embed-code_3584` vs `code_chunks_jina-code-embeddings-1.5b_1536`). If you switch models, you must re-index your repository.


Collection naming is described in [Architecture](architecture.md#collection-naming).
