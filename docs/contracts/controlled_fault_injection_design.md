# Controlled Fault Injection: Design and Methodology

## Motivation

The main matrix in Section 5 of the paper uses a **random** fault
injection schedule: each task gets faults drawn independently with a
target rate.  This is good for measuring steady-state robustness but it
has two weaknesses for the AAMAS systems-track argument:

1. **No causal attribution.**  If a configuration is robust, we don't
   know whether it was robust to the faults we injected or simply
   resilient to whatever else happened to fire on the same task.  The
   measured "robustness" is an average over the joint distribution of
   faults, not a per-fault effect.
2. **No reference trajectory.**  We can't tell whether a dead-letter
   was "the runtime failed to deal with this fault" or "the task was
   going to fail anyway on the LLM's off-policy output".  Without a
   reference, the runtime's intervention is conflated with the LLM's
   intrinsic accuracy on the task.

The advisor's review flagged both of these as a hard requirement: the
paper must show **causal evidence** that the runtime intervenes on
specific faults, not just an aggregate robustness number.

## Design

The controlled fault-injection experiment answers this in three steps:

### Step 1: Reference trajectories

For each (benchmark, domain) pair we take the **smoke** (no-fault)
configuration and run it against the live LLM.  We keep only the
trajectories that produce a fixture-success and runtime-success
without any contract violation or recovery action.  These are the
**reference trajectories** -- the trajectory the LLM produces when
nothing is going wrong.

We record, per reference trajectory:

* `task_id`, `trial_id`, `method`
* the full event log (no events should be `fault.*` or `recovery.*`)
* the natural-language resolution text
* the final `policy_compliant` value
* a hash of the LLM call sequence (so we can detect "the LLM chose a
  different trajectory on the second run" -- if it does, we exclude
  that task from the reference set)

### Step 2: Single-fault replay

For each reference trajectory and for each of the five stressors
(`schema_drift`, `stale_context`, `partial_response`,
`duplicate_message`, `tool_timeout`) we re-run the task with **exactly
one** of those stressors injected on a single LLM call, deterministically.
We do not combine stressors.  We do not randomise the injection point
beyond the deterministic seed.

The injected-fault replay reuses the same LLM endpoint, the same
`task_id`, and the same `trial_id` as the reference.  The seed is
`hash(task_id, stressor_name)`.  This is what makes the comparison
**causal**: the only thing that changes between reference and replay
is the single injected fault.

### Step 3: Causal outcome metrics

For each (reference trajectory, stressor) pair we record:

| metric | definition |
| --- | --- |
| `containment_rate` | runtime emitted a `contract.violated` or `fault.localized` event before any other agent step |
| `bounded_recovery_used` | the recovery controller fired at least once |
| `final_runtime_success` | the replay's runtime-side final state was `success` (not dead-letter) |
| `final_fixture_success` | the replay's fixture-side final state was `success` |
| `contaminated_artifact_count` | new contaminated-artifact count from the trace, minus the reference count |
| `mean_time_to_detect_ms` | first `contract.violated` minus injected timestamp, in ms |
| `mean_time_to_recover_ms` | first `recovery.succeeded` minus `contract.violated`, in ms |
| `over_rejection` | replay dead-lettered but fixture said success |

The **causal effect of a fault** is the difference between the
replay's metrics and the reference's.  Because the reference is a
clean run on the same `task_id`, this is a per-trajectory causal
estimate, not an aggregate.

### Step 4: Aggregate

For each (method, stressor) we report the task-weighted mean of:

* `containment_rate` -- what fraction of reference trajectories did
  the runtime catch
* `bounded_recovery_used_rate` -- what fraction needed bounded
  recovery
* `final_runtime_success_rate` -- what fraction still succeeded at
  the runtime layer
* `final_fixture_success_rate` -- what fraction still succeeded at
  the fixture layer
* `mean_contaminated_artifact_count` -- how badly the fault
  propagated when the runtime did not contain it
* `mean_time_to_detect_ms`, `mean_time_to_recover_ms`
* `over_rejection_rate` -- false dead-letter rate under this fault

## Why this converts the paper from "system" to "research"

The main matrix tells you which configuration survives a *joint
distribution* of faults.  The controlled experiment tells you
**which specific fault each configuration handles**, on a trajectory
that *would have succeeded without the fault*.  That is the move
from a systems engineering report to a causal argument about a
runtime.

## Implementation

The runner is `experiments/harness/controlled_fault_injection.py`.
It consumes a reference set produced by
`experiments/harness/build_reference_set.py` and writes per-cell
JSONL rows.  The aggregator is
`experiments/harness/aggregate_controlled_fault.py` and produces
`paper/aamas2026/tables/controlled_fault_table.csv`.

## Reproducibility

* The reference set is committed to
  `experiments/results/main/real_full_v2/reference_set.jsonl`.  A
  reviewer can re-derive the reference set by running
  `build_reference_set.py` against the smoke JSONL files in
  `experiments/results/main/real_full_v2/smoke/`.
* The replay seed is `hash(task_id, stressor_name)`, so re-running
  on a different GPU endpoint should produce deterministic per-task
  outcomes (modulo LLM non-determinism; the paper reports a
  three-trial average per cell).
