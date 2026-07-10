# Experiment Protocol

## Benchmarks

Main benchmark:

- tau2-bench / tau3-bench
- domains: airline, retail, telecom

Supplement benchmark:

- AgentChangeBench
- domains: airline, retail

The harness does not modify benchmark task data. It wraps benchmark execution with runtime adapters, stressors, tracing, and reliability metrics.

## Methods

- Vanilla Tool Calling: default benchmark agent behavior, no contract runtime.
- Retry-only: bounded retries without contract monitoring or fault localization.
- Schema-only: schema validation plus retry/dead-letter handling.
- AdAgentFlow-RT: contract monitor, fault localizer, bounded recovery, artifact invalidation, checkpoints, dead-letter handling, and runtime trace.

## Stress Dimensions

- concurrency
- repeated trials
- tool fault rate
- schema drift
- timeout
- duplicate execution
- stale context
- worker crash
- recovery budget

## Smoke Matrix

- benchmark: tau3 mock-compatible adapter
- domains: airline, retail
- tasks: 3 per domain
- trials: 1
- concurrency: 1
- fault: none
- methods: vanilla, retry-only, schema-only, adagentflow-rt

Smoke success requires adapter execution, JSONL result output, trace generation, and metric aggregation.

## Main Matrix

- benchmarks: tau2-bench / tau3-bench
- domains: airline, retail, telecom
- tasks: 20-30 per domain
- trials: 3
- concurrency: 1, 5, 10, 20
- fault rates: 0, 0.1, 0.2
- methods: vanilla, retry-only, schema-only, adagentflow-rt

If cost is too high, compress to airline and retail, 20 tasks/domain, 2 trials, concurrency 1/10/20, and fault rates 0/0.2.

## Metrics

Fixture-backed task metrics:

- task success / pass rate
- tool action correctness
- policy compliance
- TSR
- TUE
- TCRR
- GSRT

Runtime-stability metrics:

- throughput_tasks_per_min
- p50_latency_ms
- p95_latency_ms
- p99_latency_ms
- dead_letter_rate
- recovery_success_rate
- contract_violation_rate
- silent_failure_rate
- retry_amplification_factor
- extra_tool_calls
- extra_llm_calls
- cost_per_successful_task
- fault_propagation_depth
- contaminated_artifact_count
- mean_time_to_detect_ms
- mean_time_to_recover_ms

Every experiment writes machine-readable JSONL results keyed by `task_id`, `run_id`, `trial_id`, `benchmark`, `domain`, and `method`.
