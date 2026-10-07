#!/usr/bin/env bash
set -euo pipefail

# Apple Silicon/MPS settings tuned for a 24 GB unified-memory Mac.
#
# Defaults to the Jina 1.5B model in bfloat16 (DTYPE=auto -> bf16 on MPS),
# which is ~4.5x smaller than the 7B Nomic model and roughly halves memory vs
# float32 -- so we can run a much larger batch than the old float32 profile.
#
# Usage:
#   scripts/run_mac_mps_24gb.sh /path/to/js-or-ts-repo
#
# After indexing, it also builds an OKF LLM wiki and syncs it into the SAME Qdrant
# collection and Neo4j graph (ENABLE_OKF=1 by default; needs DEEPSEEK_API_KEY in .env).
#
# Optional overrides:
#   MODEL=nomic BATCH_SIZE=8 CHUNK_SIZE=320 ENABLE_GRAPH=1 scripts/run_mac_mps_24gb.sh /path/to/repo
#   DTYPE=float32 scripts/run_mac_mps_24gb.sh /path/to/repo   # force the old precision
#   ENABLE_OKF=0 scripts/run_mac_mps_24gb.sh /path/to/repo    # skip the OKF wiki step

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

REPO_PATH="${1:-}"
if [[ -z "${REPO_PATH}" ]]; then
  echo "Usage: scripts/run_mac_mps_24gb.sh /path/to/js-or-ts-repo" >&2
  exit 2
fi

if [[ ! -d "${REPO_PATH}" ]]; then
  echo "Repository path does not exist or is not a directory: ${REPO_PATH}" >&2
  exit 2
fi

# Console scripts installed by `pip install -e .`. Prefer the project venv,
# fall back to whatever is on PATH.
VENV_BIN="${VENV_BIN:-${PROJECT_ROOT}/.venv/bin}"
cvg() {
  local name="$1"; shift
  if [[ -x "${VENV_BIN}/${name}" ]]; then
    "${VENV_BIN}/${name}" "$@"
  else
    "${name}" "$@"
  fi
}

MODEL="${MODEL:-jina}"
DTYPE="${DTYPE:-auto}"
BATCH_SIZE="${BATCH_SIZE:-32}"
CHUNK_SIZE="${CHUNK_SIZE:-400}"
CHUNK_OVERLAP="${CHUNK_OVERLAP:-64}"
COLLECTION_NAME="${COLLECTION_NAME:-code_chunks_mac_mps_24gb}"
QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
GLOSSARY_FILE="${GLOSSARY_FILE:-glossary.yml}"
ENABLE_GRAPH="${ENABLE_GRAPH:-1}"
ENABLE_OKF="${ENABLE_OKF:-1}"          # OKF LLM wiki generation on by default (set 0 to skip)
OKF_OUT_DIR="${OKF_OUT_DIR:-okf-wiki}" # OKF bundle directory (build output / sync input)

# Let unsupported MPS ops fall back to CPU instead of crashing.
export PYTORCH_ENABLE_MPS_FALLBACK="${PYTORCH_ENABLE_MPS_FALLBACK:-1}"

ARGS=(
  --repo-path "${REPO_PATH}"
  --qdrant-url "${QDRANT_URL}"
  --collection-name "${COLLECTION_NAME}"
  --model "${MODEL}"
  --dtype "${DTYPE}"
  --chunk-size "${CHUNK_SIZE}"
  --chunk-overlap "${CHUNK_OVERLAP}"
  --batch-size "${BATCH_SIZE}"
  --glossary-file "${GLOSSARY_FILE}"
  --verbose
)

if [[ "${ENABLE_GRAPH}" != "1" ]]; then
  ARGS+=(--no-graph)
fi

echo "Running code-vector-graph with Mac MPS 24 GB profile:"
echo "  repo: ${REPO_PATH}"
echo "  model: ${MODEL}"
echo "  dtype: ${DTYPE}"
echo "  chunk-size: ${CHUNK_SIZE}"
echo "  chunk-overlap: ${CHUNK_OVERLAP}"
echo "  batch-size: ${BATCH_SIZE}"
echo "  graph: $([[ "${ENABLE_GRAPH}" == "1" ]] && echo enabled || echo disabled)"
echo "  okf-wiki: $([[ "${ENABLE_OKF}" == "1" ]] && echo "enabled -> ${OKF_OUT_DIR}" || echo disabled)"
echo

cd "${PROJECT_ROOT}"

# Index code first. `set -e` aborts here if cvg-ingest fails, so the OKF steps
# below only run after a successful code index. (No `exec`: the shell must live on.)
cvg cvg-ingest "${ARGS[@]}"

# ---- OKF LLM wiki: enrich the repo and connect it to the SAME Qdrant collection
# ---- and the SAME Neo4j graph as the code just indexed above.
if [[ "${ENABLE_OKF}" == "1" ]]; then
  echo
  echo "Generating OKF LLM wiki (ENABLE_OKF=1) ..."
  echo "  bundle:     ${OKF_OUT_DIR}"
  echo "  collection: ${COLLECTION_NAME} (shared with code; model=${MODEL})"

  # Wiki -> Neo4j only when the code graph was built; otherwise the WikiPage
  # DOCUMENTS edges would point at code nodes that were never created.
  OKF_SYNC_ARGS=(
    --bundle "${OKF_OUT_DIR}"
    --model "${MODEL}"
    --collection-name "${COLLECTION_NAME}"
    --qdrant-url "${QDRANT_URL}"
    --verbose
  )
  if [[ "${ENABLE_GRAPH}" != "1" ]]; then
    OKF_SYNC_ARGS+=(--no-neo4j)
  fi

  # Phase 1 build (DeepSeek enrichment; reads DEEPSEEK_API_KEY from .env), then
  # Phase 2 sync. Guarded by `if` so a failure warns but does NOT undo the
  # already-successful code index (errexit is suspended inside an `if` condition).
  if cvg cvg-okf-build \
        --repo-path "${REPO_PATH}" --out-dir "${OKF_OUT_DIR}" --verbose \
     && cvg cvg-okf-sync "${OKF_SYNC_ARGS[@]}"; then
    echo "OKF wiki generated and synced (Qdrant collection '${COLLECTION_NAME}_...' + Neo4j)."
  else
    echo "WARNING: OKF wiki step failed; code index is unaffected." >&2
  fi
else
  echo
  echo "Skipping OKF wiki (set ENABLE_OKF=1 to enable)."
fi
