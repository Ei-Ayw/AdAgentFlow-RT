# Related Work Notes

These notes keep the paper narrative anchored on runtime reliability rather than a new task dataset.

## Agent Benchmarks

Public benchmarks such as tau2-bench / tau3-bench and AgentChangeBench are workload providers in this project. They evaluate task completion, tool-use behavior, policy compliance, and goal-change recovery. The current artifact preserves task fixtures and metric fields while adding production runtime metrics; a full benchmark-native simulator rerun remains future validation.

Positioning:

- We do not replace benchmark-native evaluators; current scoring is fixture-backed.
- We do not mutate benchmark task data.
- We add concurrency, fault injection, recovery budgets, and trace analysis around public tasks.

## Multi-Agent Frameworks

Common multi-agent frameworks emphasize agent composition, conversation routing, tool invocation, memory, planning, and developer ergonomics. The paper should compare these capabilities against production runtime requirements:

- explicit input/output/artifact contracts
- bounded retries and recovery budgets
- downstream invalidation and rollback
- dead-letter handling
- event-sourced traces by `task_id` and `run_id`
- runtime-level reliability metrics

## Runtime Verification

The contract monitor draws from runtime verification ideas: check preconditions before execution, postconditions after execution, and emit violations that trigger policy-driven recovery. The key adaptation is that agent outputs are probabilistic and tool environments may fail, so contracts need schema, semantic, dependency, resource, and recovery dimensions.

## Fault Injection and Chaos Engineering

The stress harness borrows from fault injection and chaos engineering, but applies those ideas at the multi-agent runtime boundary. Stressors include timeout, rate-limit, partial-response, schema-drift, stale-context, duplicate-message, and worker-crash faults.

## Production Observability

The event-sourced trace is the bridge from benchmark evaluation to production diagnosis. Every runtime event must be attributable to a `task_id`, `run_id`, and when applicable a `node_id`. Trace-derived metrics support fault propagation depth, contaminated artifact count, time to detect, time to recover, and recovery action distribution.
