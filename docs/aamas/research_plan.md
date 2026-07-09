# Research Plan

Working title:

```text
AdAgentFlow-RT: A Contractual Runtime for Reliable High-Throughput Long-Horizon Multi-Agent Workflows
```

## Contributions

1. Contractual Execution Graph for long-horizon multi-agent workflows.
2. Production-grade MAS runtime with idempotency, bounded recovery, event traceability, dead-letter handling, and fault containment.
3. Fault localization and recovery policy layer that maps violations to actionable runtime decisions.
4. Public-benchmark-based stress harness on top of tau2-bench / tau3-bench and AgentChangeBench.

## Scope

The project does not create a new benchmark dataset. Public benchmarks provide task environments and native metrics. AdAgentFlow-RT contributes the runtime substrate and a stress/evaluation layer for production reliability.

The existing advertising workflow should be retained as a domain plugin/example, not the main abstraction.

## Milestones

M0: repository audit and AAMAS design docs.

M1: contract models, registry, validators, policies, and example contracts.

M2: in-memory contractual execution graph runtime skeleton.

M3: benchmark harness skeleton with deterministic mock benchmark support.

M4: tau2-bench / tau3-bench adapter skeleton with graceful missing-dependency behavior.

M5: AgentChangeBench adapter skeleton with native metric preservation.

M6: runtime strategy adapters for vanilla, retry-only, schema-only, and AdAgentFlow-RT.

M7: reproducible stressors for timeouts, rate limits, partial responses, schema drift, stale context, duplicates, and worker crashes.

M8: runtime reliability metrics, aggregation, and JSONL outputs.

M9: plotting scripts for paper figures and ablation tables.

M10: AAMAS LaTeX draft skeleton.

## Near-Term Deliverable

The minimum useful version is a runnable smoke harness with deterministic mock tasks, runtime adapters, stressors, JSONL result output, aggregation, and a paper skeleton. This establishes the experiment substrate before external benchmark integrations are fully wired.
