# `code_vector_graph.embeddings` — Model Download Process

This package owns two things:

| File | Role |
|------|------|
| `download.py` | **Pre-download** an embedding model + tokenizer from HuggingFace into the local cache. Exposed as the `cvg-download-model` CLI. |
| `embedder.py` | **Load** an already-downloaded model (`HuggingFaceEmbedder`) and turn code chunks / queries into vectors. Never downloads anything. |

The split is deliberate: downloading is a one-time, network-bound, auth-sensitive
step, while embedding runs inside long indexing jobs. Keeping them apart means a
missing model or a bad `HF_TOKEN` fails fast — before `cvg-ingest` has spent
minutes parsing a repository.

---

## 1. Why pre-download?

`HuggingFaceEmbedder` loads models with `local_files_only=True`
(`embedder.py`). It will **not** reach out to HuggingFace on its own. If the
weights are not in the cache, `cvg-ingest` / `cvg-query` / `cvg-mcp` abort with
an error like:

```
ERROR: Failed to load model 'nomic-ai/nomic-embed-code'.
Details: ...
Please ensure the model files are downloaded correctly:
  python -c "from transformers import AutoModel, AutoTokenizer; ..."
```

So the download step is mandatory, once per model, per machine. It gives you:

- No multi-GB fetch stalling the first indexing run.
- Auth problems (missing / unscoped `HF_TOKEN`) surfaced immediately.
- A smoke test proving the weights actually load and run a forward pass.

---

## 2. Quick start

```bash
# 1. Make sure HF_TOKEN is set (copy .env.example → .env and fill it in)
cp .env.example .env

# 2. Download the default model (nomic, ~28 GB on disk!)
cvg-download-model

# 3. ...or the Jina model (~3 GB) — the practical choice for laptops
cvg-download-model --model jina

# 4. Download-only: skip loading the weights + forward pass (fast, low-RAM — ideal for CI)
cvg-download-model --model jina --no-smoke-test
```

Equivalent module invocation (no console script needed):

```bash
python -m code_vector_graph.embeddings.download --model nomic
```

### CLI reference

```
usage: cvg-download-model [-h] [--model {nomic,jina}] [--no-smoke-test]

  --model {nomic,jina}   Model to download (default: value of EMBEDDING_MODEL_ID, else "nomic")
  --no-smoke-test        Download files only; skip loading the weights and the forward pass
```

Exit code is `0` on success, `1` on any failure (the error is printed to stderr
prefixed with `✗ Error:`).

---

## 3. Supported models

Model IDs are keys into `MODEL_CONFIGS` in `code_vector_graph/config.py`.

| ID | HuggingFace repo | Dimensions | Native dtype | Approx. size | Task prefixes |
|----|------------------|-----------:|--------------|-------------:|---------------|
| `nomic` (default) | `nomic-ai/nomic-embed-code` | 3584 | float16 | ~28 GB (6 fp32 safetensors shards) | none |
| `jina` | `jinaai/jina-code-embeddings-1.5b` | 1536 | bfloat16 | ~3.1 GB | `code2code` / `nl2code` |

The default is controlled by the `EMBEDDING_MODEL_ID` env var (see `.env.example`).
Whatever you download **must match** the `--model` you later pass to `cvg-ingest`
and the `CVG_MODEL_ID` the MCP server reads — the Qdrant collection name is
suffixed with model + dimension, so mixing models silently points at an empty
or incompatible collection.

To add a new model, add an entry to `MODEL_CONFIGS`; `download.py` picks it up
automatically through `argparse` `choices`.

---

## 4. What `download_model()` actually does

```
cvg-download-model --model nomic
        │
        ▼
load_dotenv()                       # .env → os.environ
        │
        ▼
HF_HOME defaults to ~/.cache/huggingface   (respects an existing HF_HOME)
        │
        ▼
_resolve_token()                    # HF_TOKEN required → ValueError if missing
        │
        ▼
from huggingface_hub import snapshot_download   # lazy: `--help` stays fast
        │
        ▼
get_model_config(model_id)["model_name"]
        │
        ▼
snapshot_download(name, token=token)  # files only — nothing deserialised
        │
        └─► (smoke_test only)
              import torch, transformers
              AutoTokenizer / AutoModel.from_pretrained(name, local_files_only=True)
              tokenizer("def hello(): pass") → model(**inputs)
              prints output shape from last_hidden_state / pooler_output / tensor
        │
        ▼
returns resolved model_name  →  main() prints the matching cvg-ingest command
```

Key details:

- **Cache location** — HuggingFace's standard cache. `HF_HOME` is honoured if
  already set; otherwise `~/.cache/huggingface`. Downloaded files land under
  `$HF_HOME/hub/models--<org>--<name>/`. Subsequent runs of
  `cvg-download-model` are near-instant because `transformers` reuses the cache.
- **`trust_remote_code=True`** — both models ship custom modelling code in their
  HF repo; without this flag they cannot be instantiated. This is also why the
  embedder loads with the same flag.
- **`HF_TOKEN` is required** even for public repos. The script fails loudly
  rather than falling back to anonymous access so that gated/rate-limited
  situations are diagnosed here, not mid-ingest.
- **Download vs. load are separate** — the fetch uses
  `huggingface_hub.snapshot_download`, which only writes files to the cache.
  Both repos ship safetensors only, so this pulls exactly the same files
  `from_pretrained` would. The weights are deserialised into RAM **only** when
  the smoke test runs; `--no-smoke-test` is therefore a true download-only mode
  and safe on low-RAM machines / CI (the nomic model is ~7B params, i.e. tens of
  GB when loaded in fp32).
- **Smoke test** — loads tokenizer + model with `local_files_only=True` (so it
  proves the *cache* is usable, not the network) and runs a single
  `torch.no_grad()` forward pass on a tiny snippet. It catches corrupted/partial
  downloads and missing runtime dependencies (e.g. an incompatible `torch`
  build) that a pure file download would not.
- **Device** — the smoke test runs on CPU in float32 (the model is not moved
  to MPS/CUDA). Device and dtype selection happen later, in
  `HuggingFaceEmbedder`, not here.

---

## 5. Programmatic use

```python
from code_vector_graph.embeddings.download import download_model

model_name = download_model("jina", smoke_test=False)
# -> "jinaai/jina-code-embeddings-1.5b"
```

`download_model` raises on failure (`ValueError` for a missing token, whatever
`huggingface_hub` raises for network/auth issues, and whatever `transformers`
raises if the smoke test hits corrupted weights). Only the CLI `main()`
swallows exceptions into an exit code.

---

## 6. Where the model is used afterwards

```python
from code_vector_graph.embeddings.embedder import create_embedder

embedder = create_embedder("nomic")          # local_files_only=True under the hood
vecs = embedder.embed_chunks([{"text": "def add(a, b): return a + b"}])
q    = embedder.embed_query("function that adds two numbers")
```

`HuggingFaceEmbedder.__init__` resolves the device (`mps` → `cuda` → `cpu`) and a
device-appropriate dtype (bfloat16 on MPS, float32 on CPU/ROCm, model-native on
CUDA), then loads from cache. If the cache is missing it prints the recovery
hint shown in §1 and re-raises.

---

## 7. Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `✗ Error: HF_TOKEN not found...` | `.env` missing or token not set | `cp .env.example .env`, add `HF_TOKEN=hf_...` |
| `401 Unauthorized` / `403` from HF | Token invalid or lacks read scope | Regenerate a **read** token at huggingface.co/settings/tokens |
| `OSError: ... is not a local folder and is not a valid model identifier` at ingest time | Model not downloaded, or downloaded under a different `HF_HOME` | Re-run `cvg-download-model --model <id>` in the same shell env as `cvg-ingest` |
| Download restarts from 0 every run | `HF_HOME` differs between runs (e.g. set in one shell only) | Put `HF_HOME` in `.env` or leave it unset everywhere |
| Smoke test fails but download succeeded | Incompatible `torch`/`transformers` versions, or partial download | `pip install -e ".[ingest]"` again; delete `$HF_HOME/hub/models--<org>--<name>` and re-download |
| Ingest finds an empty collection after switching models | Collection name is suffixed by model + dims | Pass the same `--model` to `cvg-ingest` and set `CVG_MODEL_ID` for the MCP server |
| Disk pressure | Both models cached (nomic alone is ~28 GB) | Remove the unused one, e.g. `rm -rf ~/.cache/huggingface/hub/models--nomic-ai--nomic-embed-code` |

Inspect what is cached:

```bash
ls ~/.cache/huggingface/hub/ | grep -E "nomic|jina"
# or, with huggingface_hub installed:
huggingface-cli scan-cache
```

---

## 8. Related docs

- [`docs/setup.md`](../../../docs/setup.md) — full environment setup, step 6 covers this download.
- [`.env.example`](../../../.env.example) — `HF_TOKEN`, `EMBEDDING_MODEL_ID`, `CVG_MODEL_ID`.
- `code_vector_graph/config.py` — `MODEL_CONFIGS`, `DEFAULT_MODEL_ID`, `get_model_config()`.
- `code_vector_graph/cli/download_model.py` — thin wrapper that registers the `cvg-download-model` entry point.
