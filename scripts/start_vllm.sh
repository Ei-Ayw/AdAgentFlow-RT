#!/bin/bash
# Start vLLM with FlashInfer disabled (GPU is RTX PRO 6000 Blackwell, sm75+ check fails)
export VLLM_USE_FLASHINFER_SAMPLER=0
export VLLM_FLASHINFER_FORCE_DISABLE=1
export VLLM_ATTENTION_BACKEND=FLASH_ATTN
export LD_LIBRARY_PATH=/root/miniconda3/lib/python3.12/site-packages/scipy.libs:$LD_LIBRARY_PATH
export CONDA_LIB=/root/miniconda3/lib

MODEL=/root/.cache/huggingface/hub/models--Qwen--Qwen3-8B/snapshots/$(ls /root/.cache/huggingface/hub/models--Qwen--Qwen3-8B/snapshots/ | head -1)

exec /root/miniconda3/bin/python -m vllm.entrypoints.openai.api_server \
  --model "$MODEL" \
  --host 0.0.0.0 --port 8000 \
  --served-model-name Qwen3-8B \
  --max-model-len 8192 \
  --dtype bfloat16 \
  --enforce-eager \
  --gpu-memory-utilization 0.20 \
  --max-num-seqs 8