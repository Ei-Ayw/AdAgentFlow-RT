#!/usr/bin/env bash
# 一键跑所有压测场景
#
# 用法:
#   bash scripts/scenarios/run_all.sh               # 用默认 50 并发跑完所有场景
#   CONCURRENCY=200 bash scripts/scenarios/run_all.sh
#
set -e

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

CONCURRENCY="${CONCURRENCY:-50}"
BAD_JSON_RATE="${BAD_JSON_RATE:-0.7}"
TIMEOUT_RATE="${TIMEOUT_RATE:-0.3}"
CRASH_AT="${CRASH_AT:-50}"
REPLICATION="${REPLICATION:-2}"
SEED="${SEED:-42}"

mkdir -p reports

echo "==============================================================="
echo " AdAgentFlow 一键压测 - CONCURRENCY=${CONCURRENCY}"
echo "==============================================================="

run_scenario() {
  local scenario="$1"
  echo ""
  echo "[$(date +%H:%M:%S)] >>> 跑场景: ${scenario}"
  python scripts/load_test.py \
    --scenario "${scenario}" \
    --concurrency "${CONCURRENCY}" \
    --bad-json-rate "${BAD_JSON_RATE}" \
    --timeout-rate "${TIMEOUT_RATE}" \
    --crash-at "${CRASH_AT}" \
    --replication "${REPLICATION}" \
    --seed "${SEED}" \
    --reports-dir reports
}

run_scenario concurrent
run_scenario bad_json
run_scenario worker_crash
run_scenario duplicate
run_scenario timeout
run_scenario judge_fail

echo ""
echo "==============================================================="
echo " 全部场景跑完，报告: ${ROOT}/reports/"
echo "==============================================================="
ls -la reports/