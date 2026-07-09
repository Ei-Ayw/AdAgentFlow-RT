from __future__ import annotations

from experiments.harness.benchmark_adapters.base import MockBenchmarkAdapter
from experiments.harness.config import config_methods, config_stressors, load_simple_config
from experiments.harness.metrics.runtime_metrics import compute_runtime_metrics
from experiments.harness.runtime_adapters.adagentflow_rt import AdAgentFlowRTAdapter
from experiments.harness.stressors.schema_drift import SchemaDriftStressor
from experiments.harness.workload.concurrency_runner import run_tasks


def test_mock_harness_runs_adagentflow_rt_with_recovery():
    tasks = list(MockBenchmarkAdapter().load_tasks({"domain": "airline", "num_tasks": 2, "num_trials": 1}))
    results = run_tasks(
        tasks=tasks,
        adapter=AdAgentFlowRTAdapter(),
        stressors=[SchemaDriftStressor(rate=1.0, seed=7)],
        runtime_config={"max_retries": 2},
        max_concurrency=1,
    )

    assert len(results) == 2
    assert all(result.success for result in results)
    assert all(result.recovered for result in results)
    assert all(result.events for result in results)
    metrics = compute_runtime_metrics(results)
    assert metrics["total_tasks"] == 2
    assert metrics["recovery_success_rate"] == 1.0


def test_simple_config_loader_reads_harness_yaml_subset():
    config = load_simple_config("experiments/harness/configs/tau3_airline_smoke.yaml")
    stress = load_simple_config("experiments/harness/configs/stress_medium.yaml")

    assert config["benchmark"] == "tau3"
    assert config["num_tasks"] == 3
    assert config_methods(config) == ["vanilla", "retry_only", "schema_only", "adagentflow_rt"]
    assert "schema_drift" in config_stressors(stress)
    assert stress["fault_rate"] == 0.2


def test_adagentflow_rt_contract_monitor_ablation_can_create_silent_failure():
    tasks = list(MockBenchmarkAdapter().load_tasks({"domain": "airline", "num_tasks": 1, "num_trials": 1}))
    [result] = run_tasks(
        tasks=tasks,
        adapter=AdAgentFlowRTAdapter(),
        stressors=[SchemaDriftStressor(rate=1.0, seed=7)],
        runtime_config={"max_retries": 2, "ablation": "without_contract_monitor"},
        max_concurrency=1,
    )

    assert result.success is True
    assert result.native_metrics["task_success"] is False
    assert result.runtime_metrics["contract_violations"] == 0
    assert result.ablation == "without_contract_monitor"
