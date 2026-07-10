# AdAgentFlow-RT AAMAS Artifact

This repository is the artifact workspace for the AAMAS submission
`AdAgentFlow-RT: A Contractual Runtime for Reliable High-Throughput Long-Horizon Multi-Agent Workflows`.

It should be read as a runtime-and-evaluation artifact, not as the original
advertising application prototype. The paper studies contract-aware runtime
execution, failure containment, recovery instrumentation, and auditability on
top of public benchmark fixtures. The current evidence supports those runtime
and audit claims; it does not yet validate a full benchmark-native
long-horizon multi-agent workflow execution.

## What Is In Scope

- `paper/aamas2026/`: paper source, generated tables, generated figures, and built PDF
- `experiments/harness/`: live-LLM evaluation harness, stressors, aggregation, audit, and artifact refresh scripts
- `experiments/results/main/real_full_v2/`: audited main-matrix JSONL rows, `summary.json`, reference set, and controlled-fault outputs
- `app/contracts/` and `app/runtime/`: contractual runtime kernel
- `docs/aamas/`: protocol, runbook, and design notes for the research artifact
- `docs/contracts/controlled_fault_injection_design.md`: design note for the controlled fault-injection pipeline
- `scripts/finalize_submission.sh`: local artifact refresh entrypoint

## Key Outputs

- `paper/aamas2026/build/main.pdf`
- `supplementary/aamas2026_supplementary.zip`
- `experiments/results/main/real_full_v2/summary.json`
- `paper/aamas2026/tables/main_matrix_summary.csv`
- `paper/aamas2026/tables/controlled_fault_table.csv`

## Quick Checks

Use a local Python interpreter with the repo on `PYTHONPATH`:

```bash
PYTHONPATH=. python -m compileall -q app experiments scripts
PYTHONPATH=. python -m experiments.harness.validate_suite \
  --suite-config experiments/harness/configs/suite_main_compressed.yaml
PYTHONPATH=. python -m experiments.harness.audit_results \
  --summary experiments/results/main/real_full_v2/summary.json \
  --require-external-main --require-agentchange
```

Expected behavior:

- `compileall` exits cleanly
- `validate_suite` reports the compressed main matrix as valid
- `audit_results` passes and reports `116 summary rows`

## Refreshing Paper Artifacts

To regenerate the paper-facing tables, figures, supplementary zip, and PDF
from the audited local result directory:

```bash
PYTHON_BIN=python ./scripts/finalize_submission.sh --local-only
```

This script:

- rebuilds `summary.json` from the JSONL matrix
- refreshes paper tables and figures
- rebuilds `paper/aamas2026/tables/evidence_status.csv`
- generates the controlled-fault reference set and aggregated table when the external benchmark fixtures are present under `data/external/`
- runs the audit gate
- rebuilds the supplementary zip
- rebuilds the PDF if `tectonic` is installed

## Reproducing the Live-LLM Matrix

The live matrix depends on:

- a running OpenAI-compatible endpoint, used here with Qwen3-8B via vLLM
- local checkouts of public `tau2-bench` and `AgentChangeBench` under `data/external/`

The end-to-end protocol is documented in:

- `docs/aamas/experiment_runbook.md`
- `supplementary/README.md`

## Important Interpretation Notes

- The artifact does not introduce a new benchmark dataset.
- The paper's main claims are based on the audited external matrix, not on mock smoke runs.
- `fixture_success_rate` and `runtime_success_rate` are distinct and should not be conflated.
- The current controlled fault-injection outputs are included for auditability, but they are exploratory and should not be read as strong causal evidence yet.
