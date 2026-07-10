# AdAgentFlow-RT AAMAS 2026 Supplementary Material

This zip contains the review artifact for the AAMAS 2026 paper
"AdAgentFlow-RT: A Contractual Runtime for Reliable High-Throughput
Long-Horizon Multi-Agent Workflows". It is regenerable end-to-end from the
scripts in `experiments/harness/` and the runbook in `docs/aamas/experiment_runbook.md`.

## Contents

```
paper/                     # LaTeX source + bibliography + tables + figures
  main.tex                 # Top-level driver (acmart sigconf)
  refs.bib                 # Bibliography
  sections/                # 10 section files (abstract, intro, method, system,
                           #  evaluation, experiments, discussion, related work,
                           #  conclusion, background)
  tables/                  # Generated CSV tables from the audited live-LLM matrix
  figs/                    # Generated PDF/CSV figures from the audited live-LLM matrix

experiments/
  harness/                 # Production-stress harness
    llm.py                 # SyncLLMClient (talks to any OpenAI-compatible endpoint)
    external_data.py       # Public τ³-bench + AgentChangeBench task loaders
    benchmark_adapters/    # Tau3 + AgentChange adapters (external mode)
    runtime_adapters/      # 4 runtime strategies + shared _core.py
    run_real_external.py   # One-step driver for the real-LLM matrix
    aggregate_suite.py     # JSONL → summary.json
    refresh_paper_artifacts.py  # summary.json → paper tables + figures
    audit_results.py       # Gate (--require-external-main --require-agentchange)
    stressors/             # 7 production stressors
    metrics/               # Reliability metric implementations
  results/main/real_full_v2/  # JSONL rows + summary.json + run_plan.json + audit.json

docs/aamas/                # 6 research/design/runbook markdown docs

app/
  contracts/               # Contract definitions (schema/semantic/dependency/budget/recovery)
  runtime/                 # Runtime kernel (monitor, localizer, recovery, scheduler, trace)
  services/llm_client.py   # Async LLM client used by the app (harness uses sync version)

requirements.txt           # Pinned deps
pyproject.toml             # Project metadata
supplementary/README.md    # This artifact description
```

## Reproducing the main matrix

The audited review matrix contains 1,392 live-LLM rows and 116 summary rows.
It completes in approximately four hours on a single Qwen3-8B endpoint served
by vLLM 0.23.0:

```bash
# 1. Start vLLM (on the GPU server)
vllm serve /path/to/Qwen3-8B --enforce-eager --gpu-memory-utilization 0.20 \
  --max-model-len 8192 --served-model-name Qwen3-8B

# 2. Clone τ³-bench and AgentChangeBench (public, MIT licensed)
git clone --depth 1 https://github.com/sierra-research/tau2-bench.git
git clone --depth 1 https://github.com/Maniktherana/AgentChangeBench.git
mkdir -p data/external
ln -s ../../tau2-bench data/external/tau2-bench
ln -s ../../AgentChangeBench data/external/AgentChangeBench

# 3. Install + run
pip install -r requirements.txt
export LLM_BASE_URL=http://localhost:8000/v1
export LLM_MODEL=Qwen3-8B
.venv/bin/python -m experiments.harness.run_real_external \
  --output-dir experiments/results/main/real_full_v2 \
  --num-tasks 6 --num-trials 2 --concurrencies 1,5 --fault-rates 0.0,0.1,0.2

# 4. Aggregate + refresh + audit
.venv/bin/python -m experiments.harness.aggregate_suite \
  --suite-dir experiments/results/main/real_full_v2 \
  --json-output experiments/results/main/real_full_v2/summary.json
.venv/bin/python -m experiments.harness.refresh_paper_artifacts \
  --summary experiments/results/main/real_full_v2/summary.json
.venv/bin/python -m experiments.harness.audit_results \
  --summary experiments/results/main/real_full_v2/summary.json \
  --require-external-main --require-agentchange
```

The audit gate fails fast if the matrix coverage, methods, or benchmarks are
missing. Replacing the vLLM endpoint with the public OpenAI API is a one-line
environment change (`LLM_BASE_URL`); the rest of the harness stays the same.
The scoring is fixture-backed and assertion-based; it preserves public task
data but should not be presented as a full benchmark-native simulator rerun.

## License

Code: MIT. Public benchmark fixtures retain their original licenses
(τ³-bench: MIT, AgentChangeBench: MIT).
