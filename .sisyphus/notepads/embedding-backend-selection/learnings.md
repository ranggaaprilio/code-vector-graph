# Embedding Backend Selection - Project Context

## Current Architecture

### File Structure
- `src/embedder.py` - Single `CodeEmbedder` class using Ollama
- `src/config.py` - Constants including EMBEDDING_DIMENSIONS=768
- `src/cli.py` - CLI args without embedding provider selection
- `src/store.py` - VectorStore with hardcoded 768 dimensions
- `main.py` - Pipeline orchestration with Ollama health check

### Current Constants (config.py)
- DEFAULT_MODEL = "nomic-embed-text:latest"
- EMBEDDING_DIMENSIONS = 768
- EMBEDDING_PREFIX = "search_document: "
- DEFAULT_OLLAMA_URL = "http://localhost:11434"

### Required Changes

#### Provider Configuration
- Ollama: nomic-embed-text = 768 dims, uses `search_document:` / `search_query:` prefixes
- HuggingFace: Salesforce/codet5p-110m-embedding = 256 dims, NO prefixes

#### Implementation Pattern
1. Abstract base class `Embedder` with:
   - `embed_chunks(chunks, batch_size) -> list[dict]`
   - `embed_query(query) -> list[float]`
   - `check_health() -> bool`
   - `get_dimensions() -> int`

2. `OllamaEmbedder(Embedder)` - refactored from existing CodeEmbedder
3. `HuggingFaceEmbedder(Embedder)` - new implementation using transformers
4. `create_embedder(provider, **kwargs)` - factory function

#### Collection Naming Strategy
Format: `{base_name}_{model_suffix}_{dimensions}`
- Ollama: `code_chunks_nomic-embed-text_768`
- HuggingFace: `code_chunks_codet5p-110m-embedding_256`

#### HuggingFace Implementation Details
- Use `transformers.AutoModel` + `AutoTokenizer`
- `trust_remote_code=True` required
- CPU-only torch (add to requirements.txt)
- Model size: ~440MB
- Truncation warning for chunks > 512 tokens
- No embedding prefixes

## Dependencies to Add
```
torch>=2.0 --index-url https://download.pytorch.org/whl/cpu
transformers>=4.32.1
```

## Testing Strategy
- Mock transformers for HuggingFaceEmbedder tests
- Keep existing Ollama tests with mocks
- Add factory function tests
Summary of verification:
- Verified that the original request to add an embedding provider selector between Ollama (nomic-embed-text, 768-dim) and HuggingFace (codet5p-110m, 256-dim) is implemented.
- Confirmed CLI option --embedding-provider exists and supports 'ollama' and 'huggingface'; defaults to 'ollama' for backward compatibility.
- Ollama backend connectivity and model usage align with nomic-embed-text (768-dim) and local/offline usage.
- HuggingFace backend uses Salesforce/codet5p-110m-embedding (256-dim) via transformers, with no embedding prefixes, as requested.
- README updated with provider comparison, usage examples for both providers, and configuration details.
- No scope creep detected; existing functionality preserved and changes localized to embedding selection and docs.

Fidelity: 9/10
- Small note: README could explicitly list the exact model name for HuggingFace in the technical details, but the provider header and usage confirm the intended model.
