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

Validate the suite before execution:

```bash
.venv/bin/python -m experiments.harness.validate_suite \
  --suite-config experiments/harness/configs/suite_main_compressed.yaml \
  --output-dir experiments/results/main/compressed_plan \
  --json-output experiments/results/main/compressed_plan/validation_report.json
```

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

Matrix and suite aggregation preserve `suite_run`, `max_concurrency`, `fault_rate`, and the concrete stressor list in `stress`. These fields drive the success-vs-concurrency, latency-vs-concurrency, and recovery-vs-fault-rate figures.

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

After running an external benchmark command, normalize its native JSON or JSONL output into the harness schema before aggregation:

```bash
.venv/bin/python -m experiments.harness.import_external_results \
  --input /path/to/tau3_native_results.jsonl \
  --output experiments/results/external/tau3_airline_normalized.jsonl \
  --benchmark tau3 \
  --domain airline \
  --method external_native \
  --suite-run main_external \
  --max-concurrency 10 \
  --fault-rate 0.2 \
  --stress tool_timeout,schema_drift
```

For AgentChangeBench:

```bash
.venv/bin/python -m experiments.harness.import_external_results \
  --input /path/to/agentchange_results.json \
  --output experiments/results/external/agentchange_retail_normalized.jsonl \
  --benchmark agentchange \
  --domain retail \
  --method external_native \
  --suite-run agentchange_external \
  --max-concurrency 1 \
  --fault-rate 0.0 \
  --stress none
```

The importer preserves benchmark-native metric fields such as `TSR`, `TUE`, `TCRR`, `GSRT`, `task_success`, and `policy_compliance`, and maps common fields such as `task_id`, `example_id`, `success`, `passed`, `latency_ms`, `duration_ms`, `tool_calls`, and `num_tool_calls` into the common `RuntimeResult` row format.
Pass `suite-run`, `max-concurrency`, `fault-rate`, `stress`, and `ablation` during import when the external benchmark output does not already contain those fields; otherwise concurrency and fault-rate figures will not have the required grouping keys.

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
- `trajectory_path`
- `runtime_trace_path`

Aggregation produces JSON and CSV summaries. Plotting writes data-backed PDFs and CSVs from those summaries.

Refresh all paper-facing tables and figures from one or more summaries:

```bash
.venv/bin/python -m experiments.harness.refresh_paper_artifacts \
  --summary experiments/results/smoke/tau3_airline_stress_medium_summary.json \
  --summary experiments/results/ablation/full_schema_drift_summary.json \
  --summary experiments/results/ablation/without_contract_monitor_summary.json
```

This writes:

- `paper/aamas2026/tables/main_tau3_results.csv`
- `paper/aamas2026/tables/runtime_stability_metrics.csv`
- `paper/aamas2026/tables/agentchange_recovery_metrics.csv`
- `paper/aamas2026/tables/failure_recovery_breakdown.csv`
- `paper/aamas2026/tables/ablation_table.csv`
- `paper/aamas2026/figs/*.pdf`
- `paper/aamas2026/figs/*.csv`
- `experiments/results/plots/*.pdf`
- `experiments/results/plots/*.csv`

The lower-level `export_paper_tables` and `plot_results` commands remain available when only one artifact family needs to be regenerated.
