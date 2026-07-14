"""Tests for the declarative Agent runtime and its governance boundary."""
from __future__ import annotations

import asyncio

import pytest

from app.agents import AGENT_REGISTRY, AgentRegistry, AgentSpec, get_agent, get_agent_spec
from app.agents.base import BaseAgent
from app.agents.executor import AgentExecutor
from app.schemas.agent_schemas import ProductAnalysisSchema


class NoopTelemetry:
    def __init__(self):
        self.events = []

    def start(self, tracer, task_id, step_id):
        self.events.append(("start", step_id))

    def success(self, tracer, task_id, step_id, result):
        self.events.append(("success", step_id))

    def failure(self, tracer, task_id, step_id, result):
        self.events.append(("failure", step_id))


class SlowLLM:
    model = "slow-test-model"

    async def generate_json(self, *args, **kwargs):
        await asyncio.sleep(0.05)
        raise AssertionError("timeout should cancel this call")


class RuntimeTestAgent(BaseAgent):
    step_id = "runtime_test"

    def build_system_prompt(self):
        return "system"

    def build_user_prompt(self, ctx):
        return "user"


def test_registry_exposes_governance_metadata():
    spec = get_agent_spec("product_analysis")
    assert spec.output_schema is ProductAnalysisSchema
    assert spec.timeout_seconds > 0
    assert spec.max_concurrency > 0
    assert spec.retry_policy.max_attempts > 0
    assert spec.idempotency_scope == "task_step"
    assert spec.output_version
    assert get_agent("product_analysis").spec is spec


def test_registry_rejects_duplicate_and_mismatched_steps():
    spec = AgentSpec("runtime_test", RuntimeTestAgent, None)
    registry = AgentRegistry([spec])
    with pytest.raises(ValueError, match="duplicate"):
        registry.register(spec)
    with pytest.raises(ValueError, match="mismatch"):
        AgentRegistry([AgentSpec("wrong_step", RuntimeTestAgent, None)])


def test_registry_specs_view_is_read_only():
    with pytest.raises(TypeError):
        AGENT_REGISTRY.specs["new"] = get_agent_spec("product_analysis")


@pytest.mark.asyncio
async def test_executor_enforces_spec_timeout_and_emits_failure():
    telemetry = NoopTelemetry()
    executor = AgentExecutor(telemetry=telemetry)
    spec = AgentSpec(
        "runtime_test",
        RuntimeTestAgent,
        None,
        timeout_seconds=0.01,
    )
    agent = RuntimeTestAgent(spec=spec, llm=SlowLLM(), executor=executor)

    result = await agent.run({"task_id": "timeout-task"})

    assert result.success is False
    assert result.failure_reason == "MODEL_TIMEOUT"
    assert result.needs_retry is True
    assert "0.01s" in result.error_message
    assert telemetry.events == [
        ("start", "runtime_test"),
        ("failure", "runtime_test"),
    ]
