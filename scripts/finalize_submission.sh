#!/usr/bin/env bash
# Finalize the AAMAS submission after the fuller real-LLM matrix completes.
#
# Usage (from a Mac terminal):
#   ./scripts/finalize_submission.sh [--matrix-dir DIR] [--local-only]
#
# Steps:
#   1. Pull the new real-LLM result set from the GPU server to local
#   2. Aggregate + refresh paper artifacts
#   3. Re-render the supplementary zip
#   4. Build the final PDF via tectonic (if installed)
#   5. Update paper sections with the new numbers (helper invoked from Python)
set -euo pipefail

GPU_HOST="connect.westd.seetacloud.com"
GPU_PORT="30421"
GPU_USER="root"
MATRIX_DIR="${MATRIX_DIR:-/root/experiments/results/real_full_v2}"
LOCAL_DIR="experiments/results/main/real_full_v2"
SUPP_ZIP="supplementary/aamas2026_supplementary.zip"

usage() {
  cat <<EOF
Usage: $0 [--matrix-dir DIR] [--local-only]
  --matrix-dir DIR   Path on the GPU server where the matrix was written
                     (default: ${MATRIX_DIR})
  --local-only       Skip GPU rsync and finalize the existing local result dir
EOF
}

LOCAL_ONLY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --matrix-dir) MATRIX_DIR="$2"; shift 2 ;;
    --local-only) LOCAL_ONLY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1"; usage; exit 2 ;;
  esac
done

cd "$(dirname "$0")/.."

if [[ "${LOCAL_ONLY}" == "1" ]]; then
  echo "[1/5] Using existing local matrix in ${LOCAL_DIR}"
  test -d "${LOCAL_DIR}"
else
  echo "[1/5] Pulling ${MATRIX_DIR} from ${GPU_USER}@${GPU_HOST}:${GPU_PORT}"
  mkdir -p "${LOCAL_DIR}"
  rsync -avz --delete \
    -e "ssh -p ${GPU_PORT} -o BatchMode=yes" \
    "${GPU_USER}@${GPU_HOST}:${MATRIX_DIR}/" "${LOCAL_DIR}/" | tail -3
fi

echo "[2/5] Aggregating + refreshing paper artifacts"
.venv/bin/python -m experiments.harness.aggregate_suite \
  --suite-dir "${LOCAL_DIR}" \
  --json-output "${LOCAL_DIR}/summary.json"
.venv/bin/python -m experiments.harness.refresh_paper_artifacts \
  --summary "${LOCAL_DIR}/summary.json"

echo "[3/5] Audit gate"
.venv/bin/python -m experiments.harness.audit_results \
  --summary "${LOCAL_DIR}/summary.json" \
  --require-external-main --require-agentchange \
  --json-output "${LOCAL_DIR}/audit.json"

echo "[4/5] Re-rendering supplementary zip"
if command -v zip >/dev/null 2>&1; then
  rm -f "${SUPP_ZIP}"
  ZIP_INPUTS=(
    paper/aamas2026/main.tex \
    paper/aamas2026/refs.bib \
    paper/aamas2026/sections/ \
    paper/aamas2026/tables/ \
    paper/aamas2026/figs/ \
    docs/aamas/ \
    "${LOCAL_DIR}/" \
    app/contracts/ \
    app/runtime/ \
    app/services/llm_client.py \
    experiments/harness/ \
    README.md \
    requirements.txt \
    supplementary/README.md \
  )
  if [[ -f pyproject.toml ]]; then
    ZIP_INPUTS+=(pyproject.toml)
  fi
  zip -rq "${SUPP_ZIP}" "${ZIP_INPUTS[@]}" -x '*/__pycache__/*' '*.pyc'
  echo "zip: $(ls -la ${SUPP_ZIP} | awk '{print $5}') bytes"
else
  echo "zip not installed; skipping supp zip rebuild"
fi

echo "[5/5] PDF build"
if command -v tectonic >/dev/null 2>&1; then
  mkdir -p paper/aamas2026/build
  cd paper/aamas2026
  tectonic --keep-intermediates --outdir build main.tex 2>&1 | tail -5
  cd ../..
  echo "pdf: $(ls -la paper/aamas2026/build/main.pdf | awk '{print $5}') bytes"
else
  echo "tectonic not installed; run 'brew install tectonic' to enable PDF build"
fi

echo "DONE — paper artifacts in paper/aamas2026/, results in ${LOCAL_DIR}/, supp zip in ${SUPP_ZIP}"
