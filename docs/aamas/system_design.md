# System Design

AdAgentFlow-RT is a contractual runtime kernel for reliable long-horizon multi-agent workflows.

## Runtime Components

Contract Registry: stores named contracts that define capability, schemas, preconditions, postconditions, semantic checks, resource budgets, and recovery policies.

Contractual Execution Graph: represents runtime nodes, artifact dependencies, fallback branches, rollback targets, and terminal nodes. The first implementation supports DAG execution.

Runtime Scheduler: chooses runnable nodes whose dependencies have been satisfied and dispatches them to a runtime strategy.

Contract Monitor: checks preconditions, artifact availability, output schema, semantic invariants, duplicate execution, and resource budgets. It emits `ContractViolation` objects.

Artifact Store: records produced artifacts with validation status, provenance, and downstream consumers.

Fault Localizer: maps contract violations into operational fault classes such as `agent_local_fault`, `artifact_fault`, `coordination_fault`, `resource_fault`, `tool_environment_fault`, `runtime_fault`, and `verifier_fault`.

Recovery Controller: selects bounded recovery actions such as `quick_repair`, `retry_same_agent`, `reroute_agent`, `rollback_to_checkpoint`, `invalidate_downstream`, `degrade_output`, `human_escalate`, and `dead_letter`.

Event-Sourced Trace: records runtime events by `task_id` and `run_id`, including graph creation, contract checks, node execution, violation detection, fault localization, recovery decisions, checkpoints, rollbacks, dead letters, and task finalization. Replay diagnostics reconstruct a trace from event objects or serialized event rows, check required lifecycle events and ordering, and extract the recovery chain used for audit evidence.

Production-Stress Harness: runs benchmark tasks through comparable runtime strategies under controlled concurrency and fault injection.

## Execution Model

1. Load contracts from the registry.
2. Build or load a contractual execution graph.
3. Schedule runnable nodes.
4. Execute a node through a runtime adapter.
5. Store produced artifacts.
6. Monitor contract compliance.
7. Localize faults when violations occur.
8. Select bounded recovery or dead-letter.
9. Emit machine-readable trace events.
10. Aggregate fixture-backed task scores and runtime-stability metrics.

The runtime initially supports sequential execution, fan-out, joins, fallback branches, and rollback targets in an in-memory implementation. Integration with the existing orchestrator is intentionally deferred until the skeleton is testable.
