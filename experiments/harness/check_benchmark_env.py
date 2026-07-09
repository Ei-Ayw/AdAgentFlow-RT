"""Check external benchmark checkout and command readiness."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import shlex
import shutil
from typing import Any, Dict, Iterable, List, Optional


BENCHMARK_ENV_VARS = {
    "tau3": ("TAU3_BENCHMARK_REPO", "TAU2_BENCHMARK_REPO"),
    "agentchange": ("AGENTCHANGE_REPO", "AGENTCHANGEBENCH_REPO"),
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tau3-repo", default=None)
    parser.add_argument("--agentchange-repo", default=None)
    parser.add_argument("--benchmark-command", default=None)
    parser.add_argument("--require-tau3", action="store_true")
    parser.add_argument("--require-agentchange", action="store_true")
    parser.add_argument("--json-output", default=None)
    args = parser.parse_args()

    report = check_benchmark_env(
        tau3_repo=args.tau3_repo,
        agentchange_repo=args.agentchange_repo,
        benchmark_command=args.benchmark_command,
        require_tau3=args.require_tau3,
        require_agentchange=args.require_agentchange,
    )
    payload = json.dumps(report, indent=2, ensure_ascii=False)
    if args.json_output:
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    if not report["ok"]:
        raise SystemExit(1)


def check_benchmark_env(
    *,
    tau3_repo: Optional[str] = None,
    agentchange_repo: Optional[str] = None,
    benchmark_command: Optional[str] = None,
    require_tau3: bool = False,
    require_agentchange: bool = False,
) -> Dict[str, Any]:
    tools = {
        "tau2": shutil.which("tau2"),
        "uv": shutil.which("uv"),
        "python_tau2_import": _find_module("tau2"),
        "python_agentchange_import": _find_module("agentchange"),
    }
    benchmarks = {
        "tau3": _probe_benchmark(
            "tau3",
            repo_path=tau3_repo,
            benchmark_command=benchmark_command,
            tools=tools,
        ),
        "agentchange": _probe_benchmark(
            "agentchange",
            repo_path=agentchange_repo,
            benchmark_command=benchmark_command,
            tools=tools,
        ),
    }
    required = {
        "tau3": bool(require_tau3),
        "agentchange": bool(require_agentchange),
    }
    errors: List[str] = []
    for benchmark, is_required in required.items():
        if is_required and not benchmarks[benchmark]["ready"]:
            errors.append(f"{benchmark} external benchmark is not ready")
            errors.extend(benchmarks[benchmark]["errors"])

    return {
        "ok": not errors,
        "tools": tools,
        "benchmarks": benchmarks,
        "errors": errors,
    }


def _probe_benchmark(
    benchmark: str,
    *,
    repo_path: Optional[str],
    benchmark_command: Optional[str],
    tools: Dict[str, Optional[str]],
) -> Dict[str, Any]:
    resolved_repo = _repo_path_from_args_or_env(benchmark, repo_path)
    errors: List[str] = []
    warnings: List[str] = []
    command: List[str] = []
    command_source = "unavailable"
    pyproject = False

    if resolved_repo:
        path = Path(resolved_repo).expanduser().resolve()
        repo_exists = path.exists()
        pyproject = (path / "pyproject.toml").exists()
    else:
        path = None
        repo_exists = False
        errors.append(_missing_repo_message(benchmark))

    if path and not repo_exists:
        errors.append(f"benchmark repo does not exist: {path}")

    if benchmark_command:
        command = shlex.split(benchmark_command)
        command_source = "configured"
    elif tools["tau2"]:
        command = ["tau2"]
        command_source = "path"
    elif tools["uv"] and pyproject:
        command = ["uv", "run", "tau2"]
        command_source = "uv_pyproject"
    else:
        errors.append("no tau2 command plan is available")

    command_executable = _command_executable(command)
    if command and not command_executable:
        errors.append(f"command executable is not available: {command[0]}")
    if command_source == "configured":
        warnings.append("configured benchmark_command is split and checked only by its first token")

    return {
        "ready": repo_exists and bool(command) and command_executable and not errors,
        "repo_path": str(path) if path else None,
        "repo_exists": repo_exists,
        "pyproject": pyproject,
        "command": command,
        "command_source": command_source,
        "errors": errors,
        "warnings": warnings,
        "env_vars_checked": list(BENCHMARK_ENV_VARS[benchmark]),
    }


def _repo_path_from_args_or_env(benchmark: str, repo_path: Optional[str]) -> Optional[str]:
    if repo_path:
        return repo_path
    for name in BENCHMARK_ENV_VARS[benchmark]:
        value = _env(name)
        if value:
            return value
    return None


def _env(name: str) -> Optional[str]:
    import os

    return os.environ.get(name)


def _command_executable(command: Iterable[str]) -> bool:
    command = list(command)
    if not command:
        return False
    executable = command[0]
    if Path(executable).expanduser().exists():
        return True
    return shutil.which(executable) is not None


def _find_module(name: str) -> Optional[str]:
    spec = importlib.util.find_spec(name)
    if spec is None:
        return None
    return str(spec.origin)


def _missing_repo_message(benchmark: str) -> str:
    if benchmark == "tau3":
        return "tau3 requires --tau3-repo or TAU3_BENCHMARK_REPO/TAU2_BENCHMARK_REPO"
    return "agentchange requires --agentchange-repo or AGENTCHANGE_REPO/AGENTCHANGEBENCH_REPO"


if __name__ == "__main__":
    main()
