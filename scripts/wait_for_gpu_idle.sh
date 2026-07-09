#!/usr/bin/env bash
# Wait for the GPU server to be idle, then run a fuller real-LLM matrix.
#
# Usage:
#   ./scripts/wait_for_gpu_idle.sh
#
# Polls `nvidia-smi` on the GPU server over SSH. When the GPU utilization
# stays below --threshold (default 25%) for --quiet-for (default 120s) AND the
# vLLM endpoint is healthy AND no other harness run is in progress, launches
# the fuller matrix from run_real_external.py.
#
# The script exits non-zero if --timeout elapses without finding idle time.
set -euo pipefail

GPU_HOST="connect.westd.seetacloud.com"
GPU_PORT="30421"
GPU_USER="root"
THRESHOLD="${THRESHOLD:-25}"             # max GPU util % to count as idle
QUIET_FOR="${QUIET_FOR:-120}"            # seconds GPU must stay below THRESHOLD
POLL_INTERVAL="${POLL_INTERVAL:-30}"     # seconds between polls
TIMEOUT="${TIMEOUT:-14400}"              # total wait budget (4 hours)
OUTPUT_DIR="${OUTPUT_DIR:-/root/experiments/results/real_full_v2}"
NUM_TASKS="${NUM_TASKS:-6}"
NUM_TRIALS="${NUM_TRIALS:-2}"
CONCURRENCIES="${CONCURRENCIES:-1,5}"
FAULT_RATES="${FAULT_RATES:-0.0,0.1,0.2}"

ssh_base() { ssh -o BatchMode=yes -p "${GPU_PORT}" "${GPU_USER}@${GPU_HOST}" "$@"; }

gpu_util() {
  ssh_base 'nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader,nounits' \
    2>/dev/null | awk -F',' '{ print $1, $2, $3 }'
}

vllm_healthy() {
  local code
  code=$(ssh_base 'curl -s -o /dev/null -w "%{http_code}" --max-time 5 http://localhost:8000/health' 2>/dev/null || echo 000)
  [[ "${code}" == "200" ]]
}

other_run_active() {
  # Any other vllm.entrypoints or harness process is running?
  ssh_base "pgrep -af 'vllm.entrypoints|run_real_external' | grep -v pgrep | wc -l" 2>/dev/null \
    | awk '{ exit ($1 > 0) ? 0 : 1 }'
}

log() { printf '[%s] %s\n' "$(date '+%H:%M:%S')" "$*"; }

log "Waiting for GPU idle (<${THRESHOLD}% util) for ${QUIET_FOR}s, polling every ${POLL_INTERVAL}s, total budget ${TIMEOUT}s"
log "Target: ${NUM_TASKS} tasks × ${NUM_TRIALS} trials × fault {${FAULT_RATES}} × concurrency {${CONCURRENCIES}}"

start_ts=$(date +%s)
deadline=$((start_ts + TIMEOUT))
idle_started=0
while :; do
  now=$(date +%s)
  if (( now > deadline )); then
    log "TIMEOUT: GPU never became idle within ${TIMEOUT}s"
    exit 2
  fi

  read -r util mem_used mem_total <<<"$(gpu_util || echo "? ? ?")"
  if [[ "${util}" == "?" ]]; then
    log "nvidia-smi unreachable; will retry"
    idle_started=0
    sleep "${POLL_INTERVAL}"
    continue
  fi

  if ! vllm_healthy; then
    log "vLLM endpoint not healthy (util=${util}% mem=${mem_used}MiB); will retry"
    idle_started=0
    sleep "${POLL_INTERVAL}"
    continue
  fi

  if (( util <= THRESHOLD )); then
    if (( idle_started == 0 )); then
      idle_started=$((now))
      log "GPU became idle (util=${util}%); sustaining for ${QUIET_FOR}s"
    fi
    elapsed_quiet=$((now - idle_started))
    if (( elapsed_quiet >= QUIET_FOR )); then
      log "GPU idle for ${elapsed_quiet}s — ready to launch"
      break
    fi
  else
    if (( idle_started != 0 )); then
      log "GPU busy again (util=${util}%); resetting quiet timer"
    fi
    idle_started=0
  fi
  sleep "${POLL_INTERVAL}"
done

log "Launching fuller matrix to ${OUTPUT_DIR}"
ssh_base "mkdir -p ${OUTPUT_DIR}"
ssh_base "cd /root/AdAgentFlow && \
  export LLM_BASE_URL=http://localhost:8000/v1 && \
  export LLM_MODEL=Qwen3-8B && \
  export LLM_API_KEY=EMPTY && \
  PYTHONPATH=. .venv/bin/python -m experiments.harness.run_real_external \
    --output-dir ${OUTPUT_DIR} \
    --num-tasks ${NUM_TASKS} \
    --num-trials ${NUM_TRIALS} \
    --concurrencies ${CONCURRENCIES} \
    --fault-rates ${FAULT_RATES}"

log "Matrix finished; aggregating + refreshing paper artifacts"
ssh_base "cd /root/AdAgentFlow && \
  PYTHONPATH=. .venv/bin/python -m experiments.harness.aggregate_suite \
    --suite-dir ${OUTPUT_DIR} \
    --json-output ${OUTPUT_DIR}/summary.json && \
  PYTHONPATH=. .venv/bin/python -m experiments.harness.refresh_paper_artifacts \
    --summary ${OUTPUT_DIR}/summary.json && \
  PYTHONPATH=. .venv/bin/python -m experiments.harness.audit_results \
    --summary ${OUTPUT_DIR}/summary.json \
    --require-external-main --require-agentchange"

log "DONE — artifacts under ${OUTPUT_DIR}"