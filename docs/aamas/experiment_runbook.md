# Experiment Runbook

The experiment workflow is intentionally staged. Do not run full experiments before smoke outputs and aggregation pass.

## Smoke

Run the deterministic mock smoke:

```bash
.venv/bin/python -m experiments.harness.run_experiment \
  --benchmark mock \
  --domain airline \
  --num-tasks 3 \
  --num-trials 1 \
  --methods vanilla,retry_only,schema_only,adagentflow_rt \
  --output experiments/results/smoke/mock_smoke.jsonl
```

Aggregate:

```bash
.venv/bin/python -m experiments.harness.aggregate_results \
  --input experiments/results/smoke/mock_smoke.jsonl \
  --json-output experiments/results/smoke/summary.json \
  --csv-output experiments/results/smoke/summary.csv
```

## Config Matrix

Run smoke configs directly:

```bash
.venv/bin/python -m experiments.harness.run_matrix \
  --config experiments/harness/configs/tau3_airline_smoke.yaml \
  --stress-config experiments/harness/configs/stress_none.yaml \
  --output experiments/results/smoke/tau3_airline_smoke.jsonl
```

Run a fault-injection smoke:

```bash
.venv/bin/python -m experiments.harness.run_matrix \
  --config experiments/harness/configs/tau3_airline_smoke.yaml \
  --stress-config experiments/harness/configs/stress_medium.yaml \
  --output experiments/results/smoke/tau3_airline_stress_medium.jsonl
```

## Suite Planning

Full experiment suites are dry-run planned by default. This is the safe way to inspect the matrix before spending model/API budget:

```bash
.venv/bin/python -m experiments.harness.run_suite \
  --suite-config experiments/harness/configs/suite_main_compressed.yaml \
  --output-dir experiments/results/main/compressed_plan
```

The command writes `suite_manifest.json` with one JSONL output target per planned run. Add `--execute` only after smoke validation and external benchmark setup:

```bash
.venv/bin/python -m experiments.harness.run_suite \
  --suite-config experiments/harness/configs/suite_main_compressed.yaml \
  --output-dir experiments/results/main/compressed \
  --execute
```

For smoke suites, aggregate all JSONL outputs in one directory:

```bash
.venv/bin/python -m experiments.harness.aggregate_suite \
  --suite-dir experiments/results/smoke/suite_smoke_all \
  --json-output experiments/results/smoke/suite_smoke_all/summary.json
```

Available suite configs:

- `suite_smoke_all.yaml`
- `suite_main_compressed.yaml`
- `suite_main_full.yaml`
- `suite_agentchange_supplement.yaml`
- `suite_ablation_schema_drift.yaml`

## External Benchmarks

For tau2-bench / tau3-bench and AgentChangeBench, set `benchmark_repo_path` in the config. If the repo path is missing, adapters fail with instructions instead of silently changing benchmark data. If omitted, the adapter uses deterministic mock tasks that preserve the normalized result shape.

External configs are examples because the public benchmark checkouts are not vendored into this repository:

```bash
.venv/bin/python -m experiments.harness.run_matrix \
  --config experiments/harness/configs/tau3_airline_external_example.yaml \
  --stress-config experiments/harness/configs/stress_none.yaml \
  --output experiments/results/external/tau3_airline_planned.jsonl
```

When `benchmark_repo_path` exists and contains a `pyproject.toml`, the adapter records a command plan using:

```bash
uv run tau2 run --domain <domain> --agent-llm <model> --user-llm <model> --num-trials <n> --num-tasks <n>
```

Rows written by the harness include `benchmark_adapter_mode` and `external_command` so downstream aggregation can separate deterministic mock smoke rows from external benchmark plans.

## Required Artifacts

Each run should produce JSONL rows with:

- `benchmark`
- `domain`
- `task_id`
- `trial_id`
- `method`
- `run_id`
- `native_metrics`
- `runtime_metrics`
- `events`
- `injected_faults`
- `recovered`
- `dead_letter`

Aggregation produces JSON and CSV summaries. Plotting writes placeholder PDFs until main experiment results are available.

Export paper tables from one or more summaries:

```bash
.venv/bin/python -m experiments.harness.export_paper_tables \
  --summary experiments/results/smoke/tau3_airline_stress_medium_summary.json \
  --summary experiments/results/ablation/full_schema_drift_summary.json \
  --summary experiments/results/ablation/without_contract_monitor_summary.json
```

This writes:

- `paper/aamas2026/tables/main_tau3_results.csv`
- `paper/aamas2026/tables/runtime_stability_metrics.csv`
- `paper/aamas2026/tables/agentchange_recovery_metrics.csv`
- `paper/aamas2026/tables/failure_recovery_breakdown.csv`
