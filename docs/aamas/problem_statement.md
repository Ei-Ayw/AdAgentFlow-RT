# Problem Statement

AdAgentFlow-RT targets a gap between agent benchmark success and production multi-agent reliability.

Most public agent benchmarks primarily answer whether an agent completed a task. That is necessary, but insufficient for production long-horizon multi-agent systems, where reliability also depends on bounded execution, diagnosability, recovery, idempotency, and stable behavior under concurrency and partial failures.

This paper asks:

```text
Did the multi-agent runtime remain reliable, bounded, diagnosable,
and recoverable under concurrent long-horizon execution?
```

We do not introduce a new task dataset. Instead, we wrap public benchmark workloads, including tau2-bench / tau3-bench and AgentChangeBench, with a production-stress evaluation harness. The harness injects load, duplicated execution, stale context, schema drift, timeouts, partial responses, rate limits, and worker crashes while preserving the benchmark task data and native evaluators.

AdAgentFlow-RT is framed as a contractual runtime kernel rather than an e-commerce ad-generation workflow. The existing advertising workflow remains useful as an internal plugin/example, but the research contribution is the runtime abstraction:

- Contractual Execution Graph
- Contract Registry
- Runtime Scheduler
- Contract Monitor
- Artifact Store
- Fault Localizer
- Bounded Recovery Controller
- Event-Sourced Trace
- Production-Stress Evaluation Harness

The central hypothesis is that explicit contracts and bounded recovery reduce silent failures, retry amplification, fault propagation, and dead-letter rates compared with vanilla tool calling, retry-only execution, and schema-only validation.
