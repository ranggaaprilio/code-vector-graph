# Embedding Backend Selection: Ollama vs HuggingFace

## TL;DR

> **Quick Summary**: Add `--embedding-provider` CLI flag to choose between Ollama (nomic-embed-text) and HuggingFace (Salesforce/codet5p-110m-embedding) for embedding generation. Refactor `CodeEmbedder` into an abstract base + two implementations + factory. Auto-separate Qdrant collections by dimensions. Update README.
> 
> **Deliverables**:
> - Abstract `Embedder` base class with `OllamaEmbedder` and `HuggingFaceEmbedder` implementations
> - `create_embedder()` factory function
> - `--embedding-provider` CLI flag with backward-compatible default (`ollama`)
> - Dynamic collection naming based on provider dimensions
> - Conditional Ollama health check (skipped for HuggingFace)
> - Updated `requirements.txt` with `transformers` and CPU-only `torch`
> - Updated `tests/test_embedder.py` with mocked HuggingFace tests
> - Updated `README.md` with provider comparison and usage docs
> 
> **Estimated Effort**: Medium
> **Parallel Execution**: YES - 3 waves
> **Critical Path**: T1 → T2 → T3+T4 → T7 → T8/T9

---

## Context

### Original Request
User wants to add an option to choose between using Ollama with the nomic model or Salesforce/codet5p-110m-embedding from HuggingFace for embedding. They also want the README updated to document how to choose the model.

### Interview Summary
**Key Discussions**:
- **Dimension mismatch**: nomic-embed-text = 768 dims, codet5p-110m-embedding = 256 dims. User chose auto-separate collections.
- **CLI design**: User chose `--embedding-provider ollama|huggingface` flag (not auto-detection).
- **Test strategy**: User chose mocks only (no real model download in CI).
- **Prefix behavior**: nomic uses `search_document:` / `search_query:` prefixes; codet5p uses no prefixes.

**Research Findings**:
- **codet5p-110m-embedding**: Uses `transformers.AutoModel` + `AutoTokenizer` with `trust_remote_code=True`. Not compatible with `sentence-transformers`. 256 dimensions, L2 normalized, max 512 tokens, no prefix needed. Requires `transformers>=4.32.1`.
- **Dimension mismatch**: Qdrant collections have fixed vector size. Switching backends requires different collections.

### Metis Review
**Identified Gaps** (addressed):
- **Token limit**: codet5p has hard 512-token limit. Current chunker uses BERT tokenizer at 512 tokens but codet5p uses a different tokenizer. Resolution: Use `truncation=True` in tokenizer and log a warning for truncated chunks.
- **Default provider**: Must default to `ollama` for backward compatibility. Resolution: `DEFAULT_PROVIDER = "ollama"`.
- **CPU-only torch**: Full PyTorch is ~2GB. Resolution: Add note in requirements about CPU-only torch and model size.
- **`trust_remote_code=True`**: Executes arbitrary code from HuggingFace Hub. Resolution: Document security consideration in README.
- **First-run model download**: codet5p model is ~440MB. Resolution: Add loading message and document in README.

---

## Work Objectives

### Core Objective
Allow users to choose between Ollama (nomic-embed-text) and HuggingFace (Salesforce/codet5p-110m-embedding) embedding backends via a `--embedding-provider` CLI flag, with proper dimension handling and clear documentation.

### Must Have
- Backward compatibility: default behavior unchanged (Ollama, nomic-embed-text, 768 dimensions)
- `--embedding-provider ollama|huggingface` CLI flag
- `HuggingFaceEmbedder` using `transformers.AutoModel` with `trust_remote_code=True`
- Collection auto-naming to avoid dimension mismatch (e.g., `code_chunks_codet5p-110m-embedding_256`)
- Conditional health check: skip `check_ollama_health()` when provider is `huggingface`
- HuggingFaceEmbedder token truncation with warning log
- No prefixes for HuggingFace backend (no `search_document:` or `search_query:`)
- Full mock tests for HuggingFaceEmbedder
- README provider comparison table

### Must NOT Have (Guardrails)
- NO `sentence-transformers` dependency
- NO config file parsing or `.env` support beyond what already exists
- NO model caching beyond HuggingFace default (`~/.cache/huggingface/`)
- NO GPU computation (CPU-only torch in requirements)
- NO mixing 768-dim and 256-dim vectors in same collection
- NO removal of existing Ollama functionality
- NO `trust_remote_code=True` bypass (it's required, document it)
- NO silent embedding dimension mismatch (always validate dimensions match collection)

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately - foundation):
├── Task 1: Update config with provider constants + requirements.txt [quick]
└── Task 2: Refactor embedder.py — abstract base + factory [deep]

Wave 2 (After Wave 1 - implementations + CLI + store):
├── Task 3: Implement OllamaEmbedder (depends: 2) [unspecified-high]
├── Task 4: Implement HuggingFaceEmbedder (depends: 2) [deep]
├── Task 5: Update CLI with --embedding-provider flag (depends: 1) [unspecified-low]
└── Task 6: Update store.py for dynamic dimensions (depends: 1) [quick]

Wave 3 (After Wave 2 - integration + tests + docs):
├── Task 7: Update main.py for factory + conditional health check (depends: 3, 4, 5, 6) [unspecified-high]
├── Task 8: Add/update tests for both backends (depends: 7) [unspecified-high]
└── Task 9: Update README.md with provider docs (depends: 7) [writing]

Wave FINAL (After ALL tasks — 4 parallel reviews):
├── Task F1: Plan compliance audit (oracle)
├── Task F2: Code quality review (unspecified-high)
├── Task F3: Real manual QA (unspecified-high)
└── Task F4: Scope fidelity check (deep)
```

### Dependency Matrix

| Task | Depends On | Blocks |
|------|-----------|--------|
| 1 | - | 5, 6 |
| 2 | - | 3, 4 |
| 3 | 2 | 7 |
| 4 | 2 | 7 |
| 5 | 1 | 7 |
| 6 | 1 | 7 |
| 7 | 3, 4, 5, 6 | 8, 9 |
| 8 | 7 | F1-F4 |
| 9 | 7 | F1-F4 |

---

## TODOs

- [x] 1. Update config.py with provider constants and requirements.txt
- [x] 2. Refactor embedder.py — abstract base class + factory function
- [x] 3. Implement OllamaEmbedder (refactor from CodeEmbedder)
- [x] 4. Implement HuggingFaceEmbedder class
- [x] 5. Update CLI with --embedding-provider flag
- [x] 6. Update store.py for dynamic dimensions and collection naming
- [x] 7. Update main.py for factory + conditional health check + dimension passing
- [x] 8. Add/update tests for both backends
- [x] 9. Update README.md with provider selection documentation

---

## Final Verification Wave

- [x] F1. Plan Compliance Audit — oracle ✅
- [x] F2. Code Quality Review — unspecified-high ⚠️ (minor cleanup needed)
- [x] F3. Real Manual QA — unspecified-high ✅
- [x] F4. Scope Fidelity Check — deep ✅

---

## Success Criteria

### Verification Commands
```bash
python -c "from src.embedder import create_embedder, OllamaEmbedder, HuggingFaceEmbedder; print('OK')"
python -c "from src.embedder import create_embedder; e = create_embedder('ollama'); print(type(e).__name__)"
python -c "from src.embedder import create_embedder; e = create_embedder('huggingface'); print(type(e).__name__)"
python -c "from src.embedder import create_embedder; e = create_embedder('ollama'); print(e.get_dimensions())"
python -c "from src.embedder import create_embedder; e = create_embedder('huggingface'); print(e.get_dimensions())"
python main.py --help
python -m pytest tests/test_embedder.py -v
```

### Final Checklist
- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent
- [ ] All tests pass
- [ ] README documents both providers
- [ ] Backward compatibility preserved (default = ollama)
