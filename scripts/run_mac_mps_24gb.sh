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
# Optional overrides:
#   MODEL=nomic BATCH_SIZE=8 CHUNK_SIZE=320 ENABLE_GRAPH=1 scripts/run_mac_mps_24gb.sh /path/to/repo
#   DTYPE=float32 scripts/run_mac_mps_24gb.sh /path/to/repo   # force the old precision

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

PYTHON_BIN="${PYTHON_BIN:-${PROJECT_ROOT}/.venv/bin/python}"
if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="python"
fi

MODEL="${MODEL:-jina}"
DTYPE="${DTYPE:-auto}"
BATCH_SIZE="${BATCH_SIZE:-32}"
CHUNK_SIZE="${CHUNK_SIZE:-400}"
CHUNK_OVERLAP="${CHUNK_OVERLAP:-64}"
COLLECTION_NAME="${COLLECTION_NAME:-code_chunks_mac_mps_24gb}"
QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
GLOSSARY_FILE="${GLOSSARY_FILE:-glossary.yml}"
ENABLE_GRAPH="${ENABLE_GRAPH:-1}"

# Let unsupported MPS ops fall back to CPU instead of crashing.
export PYTORCH_ENABLE_MPS_FALLBACK="${PYTORCH_ENABLE_MPS_FALLBACK:-1}"

ARGS=(
  "${PROJECT_ROOT}/main.py"
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
echo

cd "${PROJECT_ROOT}"
exec "${PYTHON_BIN}" "${ARGS[@]}"
