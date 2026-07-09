from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from experiments.harness.benchmark_adapters.base import MockBenchmarkAdapter
from experiments.harness.benchmark_adapters.agentchange_adapter import AgentChangeBenchmarkAdapter
from experiments.harness.benchmark_adapters.tau3_adapter import Tau3BenchmarkAdapter
from experiments.harness.config import config_methods, config_stressors, load_simple_config
from experiments.harness.export_paper_tables import load_summaries, write_failure_breakdown, write_table
from experiments.harness.finalize_suite import finalize_suite
from experiments.harness.import_external_results import import_external_results
from experiments.harness.aggregate_results import main as aggregate_results_main
from experiments.harness.aggregate_suite import main as aggregate_suite_main
from experiments.harness.metrics.runtime_metrics import compute_runtime_metrics
from experiments.harness.metrics.trace_metrics import compute_trace_metrics
from experiments.harness.plot_results import build_figure_rows, write_ablation_table, write_figures
from experiments.harness.refresh_paper_artifacts import refresh_paper_artifacts
from experiments.harness.run_suite import build_suite_plan
from experiments.harness.runtime_adapters.adagentflow_rt import AdAgentFlowRTAdapter
from experiments.harness.stressors.schema_drift import SchemaDriftStressor
from experiments.harness.validate_suite import validate_suite_config
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


def test_run_experiment_cli_accepts_external_benchmark_fields(tmp_path):
    repo = tmp_path / "tau2-bench"
    repo.mkdir()
    (repo / "pyproject.toml").write_text("[project]\nname = 'tau2-bench'\n", encoding="utf-8")
    output = tmp_path / "planned.jsonl"

    subprocess.run(
        [
            sys.executable,
            "-m",
            "experiments.harness.run_experiment",
            "--benchmark",
            "tau3",
            "--domain",
            "airline",
            "--num-tasks",
            "1",
            "--num-trials",
            "1",
            "--methods",
            "vanilla",
            "--benchmark-repo-path",
            str(repo),
            "--benchmark-command",
            "uv run tau2",
            "--agent-llm",
            "gpt-test-agent",
            "--user-llm",
            "gpt-test-user",
            "--task-ids",
            "task_a",
            "--output",
            str(output),
        ],
        check=True,
        cwd=str(Path(__file__).resolve().parents[1]),
    )

    [row] = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert row["benchmark_adapter_mode"] == "external"
    assert row["task_id"] == "task_a"
    assert row["external_command"][:3] == ["uv", "run", "tau2"]
    assert "gpt-test-agent" in row["external_command"]


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


def test_import_external_results_normalizes_agentchange_json(tmp_path):
    source = tmp_path / "agentchange_results.json"
    source.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "example_id": "retail_change_1",
                        "trial": 2,
                        "passed": True,
                        "metrics": {"TSR": 0.8, "TUE": 4},
                        "TCRR": 0.75,
                        "GSRT": 11.2,
                        "duration_ms": 3400,
                        "num_tool_calls": 7,
                        "num_llm_calls": 3,
                        "trajectory_path": "runs/retail_change_1.json",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    [result] = import_external_results(
        input_path=source,
        benchmark="agentchange",
        domain="retail",
        method="external_native",
    )

    assert result.benchmark == "agentchange"
    assert result.domain == "retail"
    assert result.task_id == "retail_change_1"
    assert result.trial_id == 2
    assert result.success is True
    assert result.benchmark_adapter_mode == "external"
    assert result.native_metrics["TSR"] == 0.8
    assert result.native_metrics["TCRR"] == 0.75
    assert result.native_metrics["GSRT"] == 11.2
    assert result.trajectory_path == "runs/retail_change_1.json"
    assert result.latency_ms == 3400
    assert result.tool_calls == 7
    assert result.llm_calls == 3


def test_import_external_results_jsonl_feeds_existing_aggregator(tmp_path):
    source = tmp_path / "tau3.jsonl"
    output = tmp_path / "normalized.jsonl"
    source.write_text(
        "\n".join(
            [
                json.dumps({"task_id": "airline_1", "success": True, "latency_ms": 1000, "tool_calls": 2, "llm_calls": 1}),
                json.dumps({"task_id": "airline_2", "success": False, "error": "policy failure"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    rows = import_external_results(input_path=source, benchmark="tau3", domain="airline", method="external_native")
    output.write_text("\n".join(json.dumps(row.to_dict()) for row in rows) + "\n", encoding="utf-8")

    metrics = compute_runtime_metrics(rows)

    assert len(rows) == 2
    assert rows[0].benchmark_adapter_mode == "external"
    assert rows[1].dead_letter is False
    assert metrics["total_tasks"] == 2
    assert metrics["task_success_rate"] == 0.5


def test_import_external_results_attaches_matrix_metadata(tmp_path):
    source = tmp_path / "tau3.jsonl"
    source.write_text('{"task_id":"airline_1","success":true}\n', encoding="utf-8")

    [result] = import_external_results(
        input_path=source,
        benchmark="tau3",
        domain="airline",
        method="external_native",
        suite_run="main_external",
        fault_rate=0.2,
        max_concurrency=20,
        stress="tool_timeout,schema_drift",
        ablation="without_fault_localizer",
    )

    assert result.suite_run == "main_external"
    assert result.fault_rate == 0.2
    assert result.max_concurrency == 20
    assert result.stress == "tool_timeout,schema_drift"
    assert result.ablation == "without_fault_localizer"


def test_aggregate_results_preserves_matrix_dimensions(tmp_path, monkeypatch):
    input_path = tmp_path / "matrix.jsonl"
    output = tmp_path / "summary.json"
    csv_output = tmp_path / "summary.csv"
    input_path.write_text(
        '{"benchmark":"tau3","domain":"airline","task_id":"t1","trial_id":0,'
        '"method":"adagentflow_rt","run_id":"r1","success":true,'
        '"suite_run":"main_compressed","fault_rate":0.2,"max_concurrency":10,'
        '"stress":"schema_drift","native_metrics":{"task_success":true},'
        '"runtime_metrics":{},"events":[],"latency_ms":1000,"tool_calls":2,'
        '"llm_calls":1,"attempts":1,"injected_faults":[],"recovered":false,'
        '"dead_letter":false}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "aggregate_results",
            "--input",
            str(input_path),
            "--json-output",
            str(output),
            "--csv-output",
            str(csv_output),
        ],
    )

    aggregate_results_main()

    [row] = json.loads(output.read_text(encoding="utf-8"))
    assert row["suite_run"] == "main_compressed"
    assert row["fault_rate"] == 0.2
    assert row["max_concurrency"] == 10
    assert row["stress"] == "schema_drift"


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


def test_plot_results_writes_data_backed_figures(tmp_path):
    rows = [
        {
            "benchmark": "tau3",
            "domain": "airline",
            "method": "adagentflow_rt",
            "ablation": None,
            "task_success_rate": 1.0,
            "p95_latency_ms": 1500,
            "recovery_success_rate": 1.0,
            "dead_letter_rate": 0.0,
            "cost_per_successful_task": 4.0,
        },
        {
            "benchmark": "tau3",
            "domain": "airline",
            "method": "adagentflow_rt",
            "ablation": "without_contract_monitor",
            "task_success_rate": 1.0,
            "p95_latency_ms": 1200,
            "recovery_success_rate": 0.0,
            "dead_letter_rate": 0.0,
            "cost_per_successful_task": 3.0,
            "silent_failure_rate": 1.0,
        },
    ]
    figure_rows = build_figure_rows(rows)
    fig_dir = tmp_path / "figs"
    table_path = tmp_path / "ablation.csv"

    write_figures(fig_dir, figure_rows)
    write_ablation_table(table_path, rows)

    assert (fig_dir / "system_architecture.pdf").exists()
    assert (fig_dir / "ablation_study.csv").exists()
    assert "without_contract_monitor" in table_path.read_text(encoding="utf-8")
    assert any(row["metric"] == "task_success_rate" for row in figure_rows["success_vs_concurrency"])


def test_refresh_paper_artifacts_writes_tables_and_figures(tmp_path):
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(
        json.dumps(
            [
                {
                    "benchmark": "tau3",
                    "domain": "airline",
                    "method": "adagentflow_rt",
                    "ablation": None,
                    "benchmark_adapter_mode": "external",
                    "task_success_rate": 0.9,
                    "p95_latency_ms": 2200,
                    "dead_letter_rate": 0.02,
                    "recovery_success_rate": 0.8,
                    "cost_per_successful_task": 5.5,
                    "fault_rate": 0.2,
                    "max_concurrency": 10,
                    "fault_class_counts": {"artifact_fault": 2},
                    "recovery_action_counts": {"quick_repair": 2},
                },
                {
                    "benchmark": "agentchange",
                    "domain": "retail",
                    "method": "adagentflow_rt",
                    "TSR": 0.7,
                    "TUE": 5,
                    "TCRR": 0.6,
                    "GSRT": 12.0,
                    "recovery_success_rate": 0.75,
                    "mean_time_to_recover_ms": 900,
                },
                {
                    "benchmark": "tau3",
                    "domain": "airline",
                    "method": "retry_only",
                    "ablation": None,
                    "task_success_rate": 0.75,
                    "dead_letter_rate": 0.1,
                    "recovery_success_rate": 0.4,
                    "silent_failure_rate": 0.0,
                    "mean_time_to_recover_ms": 0,
                },
            ]
        ),
        encoding="utf-8",
    )
    table_dir = tmp_path / "tables"
    fig_dir = tmp_path / "figs"
    plot_dir = tmp_path / "plots"

    written = refresh_paper_artifacts(
        summary_paths=[str(summary_path)],
        table_dir=table_dir,
        fig_dir=fig_dir,
        plot_dir=plot_dir,
    )

    assert table_dir.joinpath("main_tau3_results.csv").exists()
    assert table_dir.joinpath("runtime_stability_metrics.csv").exists()
    assert table_dir.joinpath("agentchange_recovery_metrics.csv").exists()
    assert table_dir.joinpath("failure_recovery_breakdown.csv").exists()
    assert table_dir.joinpath("ablation_table.csv").exists()
    assert fig_dir.joinpath("success_vs_concurrency.pdf").exists()
    assert plot_dir.joinpath("recovery_vs_fault_rate.csv").exists()
    assert "agentchange" in table_dir.joinpath("agentchange_recovery_metrics.csv").read_text(encoding="utf-8")
    assert "retry_only" in table_dir.joinpath("ablation_table.csv").read_text(encoding="utf-8")
    assert table_dir.joinpath("main_tau3_results.csv") in written


def test_suite_plan_expands_protocol_matrix(tmp_path):
    suite = load_simple_config("experiments/harness/configs/suite_ablation_schema_drift.yaml")
    plan = build_suite_plan(suite, output_dir=tmp_path)

    assert plan["suite_name"] == "ablation_schema_drift"
    assert plan["run_count"] == 5
    assert plan["execute_by_default"] is False
    labels = {item["label"] for item in plan["runs"]}
    assert any("without_contract_monitor" in label for label in labels)
    assert all(item["output"].endswith(".jsonl") for item in plan["runs"])


def test_suite_plan_propagates_external_command_config(tmp_path):
    plan = build_suite_plan(
        {
            "suite_name": "external_smoke",
            "benchmarks": ["tau3"],
            "domains": ["airline"],
            "num_tasks": 1,
            "num_trials": 1,
            "execution_mode": "external",
            "benchmark_repo_path": "/tmp/tau2",
            "benchmark_command": "uv run tau2",
            "output_dir": "experiments/results/external/tau3_airline",
            "task_ids": ["task_a", "task_b"],
        },
        output_dir=tmp_path,
    )

    config = plan["runs"][0]["config"]
    assert config["execution_mode"] == "external"
    assert config["benchmark_repo_path"] == "/tmp/tau2"
    assert config["benchmark_command"] == "uv run tau2"
    assert config["output_dir"] == "experiments/results/external/tau3_airline"
    assert config["task_ids"] == ["task_a", "task_b"]


def test_validate_suite_reports_main_compressed_matrix(tmp_path):
    suite = load_simple_config("experiments/harness/configs/suite_main_compressed.yaml")
    report = validate_suite_config(suite, output_dir=tmp_path)

    assert report["ok"] is True
    assert report["suite_name"] == "main_compressed"
    assert report["run_count"] == 24
    assert report["expected_run_count"] == 24
    assert report["benchmarks"] == ["tau3"]
    assert "adagentflow_rt" in report["methods"]
    assert "schema_drift" in report["stressors"]
    assert report["warnings"]


def test_validate_suite_rejects_missing_external_repo(tmp_path):
    report = validate_suite_config(
        {
            "suite_name": "bad_external",
            "benchmarks": ["tau3"],
            "domains": ["airline"],
            "execution_mode": "external",
        },
        output_dir=tmp_path,
    )

    assert report["ok"] is False
    assert any("benchmark_repo_path" in error for error in report["errors"])


def test_validate_suite_rejects_unknown_runtime_method(tmp_path):
    report = validate_suite_config(
        {
            "suite_name": "bad_method",
            "benchmarks": ["tau3"],
            "domains": ["airline"],
            "methods": ["vanilla", "invented_runtime"],
        },
        output_dir=tmp_path,
    )

    assert report["ok"] is False
    assert "unknown runtime method: invented_runtime" in report["errors"]


def test_aggregate_suite_summarizes_jsonl_directory(tmp_path, monkeypatch):
    suite_dir = tmp_path / "suite"
    suite_dir.mkdir()
    (suite_dir / "one.jsonl").write_text(
        '{"benchmark":"mock","domain":"airline","task_id":"t1","trial_id":0,'
        '"method":"vanilla","run_id":"r1","success":true,'
        '"native_metrics":{"task_success":true},"runtime_metrics":{},'
        '"events":[],"latency_ms":1000,"tool_calls":2,"llm_calls":1,'
        '"attempts":1,"injected_faults":[],"recovered":false,"dead_letter":false}\n',
        encoding="utf-8",
    )
    output = tmp_path / "summary.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "aggregate_suite",
            "--suite-dir",
            str(suite_dir),
            "--json-output",
            str(output),
        ],
    )

    aggregate_suite_main()

    assert '"total_tasks": 1' in output.read_text(encoding="utf-8")


def test_aggregate_suite_groups_mixed_method_jsonl(tmp_path, monkeypatch):
    suite_dir = tmp_path / "suite"
    suite_dir.mkdir()
    (suite_dir / "mixed.jsonl").write_text(
        '{"benchmark":"tau3","domain":"airline","task_id":"t1","trial_id":0,'
        '"method":"vanilla","run_id":"r1","success":true,'
        '"fault_rate":0.2,"max_concurrency":20,'
        '"native_metrics":{"task_success":true},"runtime_metrics":{},'
        '"events":[],"latency_ms":1000,"tool_calls":2,"llm_calls":1,'
        '"attempts":1,"injected_faults":[],"recovered":false,"dead_letter":false}\n'
        '{"benchmark":"tau3","domain":"airline","task_id":"t1","trial_id":0,'
        '"method":"adagentflow_rt","run_id":"r2","success":true,'
        '"fault_rate":0.2,"max_concurrency":20,'
        '"native_metrics":{"task_success":true},"runtime_metrics":{},'
        '"events":[],"latency_ms":1200,"tool_calls":2,"llm_calls":1,'
        '"attempts":1,"injected_faults":[],"recovered":false,"dead_letter":false}\n',
        encoding="utf-8",
    )
    output = tmp_path / "summary.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "aggregate_suite",
            "--suite-dir",
            str(suite_dir),
            "--json-output",
            str(output),
        ],
    )

    aggregate_suite_main()

    rows = json.loads(output.read_text(encoding="utf-8"))
    assert {row["method"] for row in rows} == {"vanilla", "adagentflow_rt"}
    assert {row["max_concurrency"] for row in rows} == {20}
    assert {row["fault_rate"] for row in rows} == {0.2}


def test_finalize_suite_writes_summary_and_paper_artifacts(tmp_path):
    suite_dir = tmp_path / "suite"
    suite_dir.mkdir()
    (suite_dir / "run.jsonl").write_text(
        '{"benchmark":"tau3","domain":"airline","task_id":"t1","trial_id":0,'
        '"method":"adagentflow_rt","run_id":"r1","success":true,'
        '"suite_run":"smoke","fault_rate":0.2,"max_concurrency":10,'
        '"native_metrics":{"task_success":true},"runtime_metrics":{},'
        '"events":[],"latency_ms":1000,"tool_calls":2,"llm_calls":1,'
        '"attempts":1,"injected_faults":[],"recovered":false,"dead_letter":false}\n',
        encoding="utf-8",
    )
    summary_json = tmp_path / "summary.json"
    summary_csv = tmp_path / "summary.csv"
    table_dir = tmp_path / "tables"
    fig_dir = tmp_path / "figs"
    plot_dir = tmp_path / "plots"

    report = finalize_suite(
        suite_dir=suite_dir,
        summary_json=summary_json,
        summary_csv=summary_csv,
        table_dir=table_dir,
        fig_dir=fig_dir,
        plot_dir=plot_dir,
    )

    assert report["summary_rows"] == 1
    assert summary_json.exists()
    assert summary_csv.exists()
    assert table_dir.joinpath("main_tau3_results.csv").exists()
    assert fig_dir.joinpath("success_vs_concurrency.pdf").exists()
    assert plot_dir.joinpath("success_vs_concurrency.csv").exists()
