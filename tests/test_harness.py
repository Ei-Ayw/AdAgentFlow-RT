from __future__ import annotations

from experiments.harness.benchmark_adapters.base import MockBenchmarkAdapter
from experiments.harness.benchmark_adapters.agentchange_adapter import AgentChangeBenchmarkAdapter
from experiments.harness.benchmark_adapters.tau3_adapter import Tau3BenchmarkAdapter
from experiments.harness.config import config_methods, config_stressors, load_simple_config
from experiments.harness.export_paper_tables import load_summaries, write_failure_breakdown, write_table
from experiments.harness.metrics.runtime_metrics import compute_runtime_metrics
from experiments.harness.metrics.trace_metrics import compute_trace_metrics
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
    assert metrics["fault_propagation_depth"] == 2
    assert metrics["contaminated_artifact_count"] == 4
    assert metrics["mean_time_to_detect_ms"] > 0
    assert metrics["mean_time_to_recover_ms"] > 0

    trace = compute_trace_metrics(results[0].events)
    assert trace["event_types"]["contract.violated"] == 1
    assert trace["fault_class_counts"]["artifact_fault"] == 1
    assert trace["recovery_action_counts"]["quick_repair"] >= 1


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


def test_tau3_external_adapter_builds_command_plan(tmp_path):
    repo = tmp_path / "tau2-bench"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname = 'tau2-bench'\n", encoding="utf-8")
    adapter = Tau3BenchmarkAdapter()

    tasks = list(
        adapter.load_tasks(
            {
                "benchmark_repo_path": str(repo),
                "domain": "airline",
                "num_tasks": 2,
                "num_trials": 1,
                "agent_llm": "gpt-test-agent",
                "user_llm": "gpt-test-user",
                "benchmark_command": "uv run tau2",
            }
        )
    )

    assert len(tasks) == 2
    assert all(task.adapter_mode == "external" for task in tasks)
    assert tasks[0].external_command[:3] == ["uv", "run", "tau2"]
    assert "--domain" in tasks[0].external_command
    assert "gpt-test-agent" in tasks[0].external_command


def test_agentchange_external_adapter_preserves_native_metric_slots(tmp_path):
    repo = tmp_path / "AgentChangeBench"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname = 'agentchangebench'\n", encoding="utf-8")
    [task] = list(
        AgentChangeBenchmarkAdapter().load_tasks(
            {
                "benchmark_repo_path": str(repo),
                "domain": "retail",
                "num_tasks": 1,
                "num_trials": 1,
                "benchmark_command": "uv run tau2",
            }
        )
    )

    assert task.adapter_mode == "external"
    assert {"TSR", "TUE", "TCRR", "GSRT"}.issubset(task.native_metrics)


def test_external_adapter_missing_repo_has_clear_error():
    try:
        list(Tau3BenchmarkAdapter().load_tasks({"benchmark_repo_path": "/does/not/exist"}))
    except RuntimeError as exc:
        assert "repo was not found" in str(exc)
        assert "mock smoke tasks" in str(exc)
    else:
        raise AssertionError("expected missing repo error")


def test_export_paper_tables_writes_runtime_csvs(tmp_path):
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(
        """
[
  {
    "benchmark": "tau3",
    "domain": "airline",
    "method": "adagentflow_rt",
    "ablation": null,
    "benchmark_adapter_mode": "mock",
    "task_success": 1.0,
    "task_success_rate": 1.0,
    "p95_latency_ms": 1500,
    "dead_letter_rate": 0.0,
    "recovery_success_rate": 1.0,
    "cost_per_successful_task": 4.0,
    "fault_class_counts": {"artifact_fault": 3},
    "recovery_action_counts": {"quick_repair": 3}
  }
]
""",
        encoding="utf-8",
    )
    rows = load_summaries([str(summary_path)])
    main_table = tmp_path / "main.csv"
    failure_table = tmp_path / "failure.csv"

    write_table(main_table, rows, ["benchmark", "domain", "method", "task_success_rate"])
    write_failure_breakdown(failure_table, rows)

    assert "adagentflow_rt" in main_table.read_text(encoding="utf-8")
    assert "artifact_fault" in failure_table.read_text(encoding="utf-8")
