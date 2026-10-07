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
# It also builds an OKF LLM wiki (per-symbol pages, ENABLE_OKF=1 by default)
# and feature-level business-logic docs (ENABLE_DOCS=1 by default) into the
# SAME Qdrant collection and Neo4j graph as the code (needs DEEPSEEK_API_KEY
# in .env, or OKF_LLM_PROVIDER=omlx + a running local oMLX server). Order: cvg-okf-build (no DB — populates the per-file summary
# cache) -> cvg-ingest [+--docs] (code index, then feature docs, reusing the
# just-built cache) -> cvg-okf-sync (pushes the per-symbol wiki bundle in).
#
# Optional overrides:
#   MODEL=nomic BATCH_SIZE=8 CHUNK_SIZE=320 ENABLE_GRAPH=1 scripts/run_mac_mps_24gb.sh /path/to/repo
#   DTYPE=float32 scripts/run_mac_mps_24gb.sh /path/to/repo   # force the old precision
#   ENABLE_OKF=0 scripts/run_mac_mps_24gb.sh /path/to/repo    # skip the per-symbol OKF wiki step
#   ENABLE_DOCS=0 scripts/run_mac_mps_24gb.sh /path/to/repo   # skip the feature-docs step
#   CVG_DOCS_LANGUAGE=id scripts/run_mac_mps_24gb.sh /path/to/repo   # feature-doc prose language

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
COLLECTION_NAME="${COLLECTION_NAME:-code_chunks}"
QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
GLOSSARY_FILE="${GLOSSARY_FILE:-glossary.yml}"
ENABLE_GRAPH="${ENABLE_GRAPH:-1}"
ENABLE_OKF="${ENABLE_OKF:-1}"          # OKF LLM wiki generation on by default (set 0 to skip)
OKF_OUT_DIR="${OKF_OUT_DIR:-okf-wiki}" # OKF bundle directory (build output / sync input)
ENABLE_DOCS="${ENABLE_DOCS:-1}"        # feature-level business-logic docs on by default (set 0 to skip)
DOCS_LANGUAGE="${CVG_DOCS_LANGUAGE:-en}"

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

# --docs requires the code graph (IMPLEMENTED_BY edges need real code nodes),
# so it only applies when ENABLE_GRAPH=1.
DOCS_ENABLED_THIS_RUN="0"
if [[ "${ENABLE_DOCS}" == "1" && "${ENABLE_GRAPH}" == "1" ]]; then
  ARGS+=(--docs --docs-bundle-dir "${OKF_OUT_DIR}" --docs-language "${DOCS_LANGUAGE}")
  DOCS_ENABLED_THIS_RUN="1"
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
if [[ "${ENABLE_DOCS}" == "1" && "${ENABLE_GRAPH}" != "1" ]]; then
  echo "  feature-docs: skipped (ENABLE_DOCS=1 but ENABLE_GRAPH!=1 — --docs needs the graph)"
else
  echo "  feature-docs: $([[ "${DOCS_ENABLED_THIS_RUN}" == "1" ]] && echo "enabled -> ${OKF_OUT_DIR} (lang=${DOCS_LANGUAGE})" || echo disabled)"
fi
echo

cd "${PROJECT_ROOT}"

# ---- OKF LLM wiki, phase 1: enrich per-symbol/per-file pages first (no DB
# needed) so their one-line summaries are already cached when --docs runs the
# feature-map discovery below, on the very first run.
if [[ "${ENABLE_OKF}" == "1" ]]; then
  echo "Building OKF LLM wiki bundle (ENABLE_OKF=1) -> ${OKF_OUT_DIR} ..."
  if ! cvg cvg-okf-build --repo-path "${REPO_PATH}" --out-dir "${OKF_OUT_DIR}" --verbose; then
    echo "WARNING: cvg-okf-build failed; continuing without a per-file summary cache." >&2
  fi
  echo
else
  echo "Skipping OKF wiki build (set ENABLE_OKF=1 to enable)."
fi

# Index code (and, if enabled, feature-level docs right after). `set -e`
# aborts here if cvg-ingest fails, so the OKF sync step below only runs after
# a successful code index. (No `exec`: the shell must live on.)
cvg cvg-ingest "${ARGS[@]}"
if [[ "${DOCS_ENABLED_THIS_RUN}" == "1" ]]; then
  echo "(feature docs generated as part of the cvg-ingest run above; see 'Feature docs:' summary)"
fi

# ---- OKF LLM wiki, phase 2: push the per-symbol bundle into the SAME Qdrant
# ---- collection and the SAME Neo4j graph as the code just indexed above.
if [[ "${ENABLE_OKF}" == "1" ]]; then
  echo
  echo "Syncing OKF LLM wiki (ENABLE_OKF=1) ..."
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

  # Guarded by `if` so a failure warns but does NOT undo the already-successful
  # code index (errexit is suspended inside an `if` condition).
  if cvg cvg-okf-sync "${OKF_SYNC_ARGS[@]}"; then
    echo "OKF wiki synced (Qdrant collection '${COLLECTION_NAME}_...' + Neo4j)."
  else
    echo "WARNING: cvg-okf-sync failed; code index is unaffected." >&2
  fi
else
  echo
  echo "Skipping OKF wiki sync (set ENABLE_OKF=1 to enable)."
fi
