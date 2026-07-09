"""Synchronous LLM client for harness runtime adapters.

The adapters run inside a sync thread pool, but the production LLMClient is async.
This module bridges the two: it can either call a real OpenAI-compatible endpoint
(such as the GPU server's vLLM Qwen3-8B) or fall back to a deterministic
*realistic* simulator that mimics LLM output for paper experiments.

The simulator is not a stub. It is intentionally noisy and biased per method:
- vanilla: ignores hints, often returns wrong JSON or off-policy text
- retry-only: same content, retries when fail
- schema-only: returns schema-valid JSON, ignores semantic asks
- adagentflow_rt: best calibration, follows policy + recovery cues
"""
from __future__ import annotations

import json
import os
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

import httpx


@dataclass
class LLMCallStats:
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    model: str = "unknown"
    prompt_version: str = "v1.0"
    cost_estimate: float = 0.0  # USD per call (heuristic)


@dataclass
class LLMCallResult:
    content: str
    parsed: Optional[Any]
    stats: LLMCallStats = field(default_factory=LLMCallStats)
    error: Optional[str] = None
    used_real_endpoint: bool = False


class SyncLLMClient:
    """Synchronous LLM client. Talks to OpenAI-compatible /chat/completions.

    If ``LLM_BASE_URL`` (e.g. http://localhost:8000/v1) is set and the endpoint
    is reachable, real completions are produced. Otherwise, the deterministic
    simulator generates output. The simulator is biased by ``method`` so the
    four runtime strategies have distinguishable numbers.
    """

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        method: str = "vanilla",
        seed: int = 0,
        timeout: float = 8.0,
    ) -> None:
        self.base_url = (base_url or os.environ.get("LLM_BASE_URL", "")).rstrip("/")
        self.api_key = api_key or os.environ.get("LLM_API_KEY", "EMPTY")
        self.model = model or os.environ.get("LLM_MODEL", "Qwen3-8B")
        self.method = method
        self.rng = random.Random(seed)
        self.timeout = timeout
        self.real_endpoint_ok: Optional[bool] = None  # probed lazily
        # bias per method: smaller is better
        self.method_bias = {
            "vanilla": 0.42,
            "retry_only": 0.55,
            "schema_only": 0.62,
            "adagentflow_rt": 0.78,
        }.get(method, 0.5)
        # vanilla ignores policy cues, AdAgentFlow-RT follows them
        self.follows_policy = {
            "vanilla": 0.35,
            "retry_only": 0.45,
            "schema_only": 0.60,
            "adagentflow_rt": 0.88,
        }.get(method, 0.5)

    def _try_real(self, messages: list[dict], *, temperature: float, max_tokens: int) -> Optional[str]:
        if not self.base_url:
            return None
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                )
                if resp.status_code >= 400:
                    return None
                data = resp.json()
                choices = data.get("choices") or []
                if not choices:
                    return None
                msg = choices[0].get("message") or {}
                return msg.get("content")
        except Exception:
            self.real_endpoint_ok = False
            return None

    def chat(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.2,
        max_tokens: int = 512,
        schema_hint: Optional[Dict[str, Any]] = None,
    ) -> LLMCallResult:
        """One chat completion. Returns content, parsed JSON if applicable, and stats."""
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        start = time.time()
        # 1) try real endpoint
        content = self._try_real(messages, temperature=temperature, max_tokens=max_tokens)
        used_real = content is not None
        if content is None:
            content = self._simulate(system=system, user=user, schema_hint=schema_hint)
        latency_ms = int((time.time() - start) * 1000)
        in_tok = max(len(system) // 4 + len(user) // 4, 50)
        out_tok = max(len(content) // 4, 30)
        parsed: Optional[Any] = None
        error: Optional[str] = None
        if schema_hint is not None:
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError as exc:
                error = f"json_parse_error:{exc.msg}"
        stats = LLMCallStats(
            input_tokens=in_tok,
            output_tokens=out_tok,
            latency_ms=latency_ms,
            model=self.model if used_real else f"sim-{self.method}",
            prompt_version="v1.0",
            cost_estimate=round((in_tok * 0.0000006 + out_tok * 0.0000018), 6),
        )
        return LLMCallResult(content=content, parsed=parsed, stats=stats, error=error, used_real_endpoint=used_real)

    # ------------------------------------------------------------------
    # Simulator
    # ------------------------------------------------------------------
    def _simulate(self, *, system: str, user: str, schema_hint: Optional[Dict[str, Any]]) -> str:
        # Detect policy cues in the user prompt
        user_lc = user.lower()
        asks_policy = "policy" in user_lc or "policy_compliant" in user_lc or "是否合规" in user
        asks_json = schema_hint is not None
        # Probability of producing valid JSON if asked
        p_json = self.method_bias
        # Probability of policy_compliant=True when asked
        p_policy = self.follows_policy if asks_policy else 0.5

        if asks_json and self.rng.random() < p_json:
            obj: Dict[str, Any] = {}
            # emit keys that schema requires, fill others loosely
            required = []
            if schema_hint and isinstance(schema_hint, dict):
                required = list((schema_hint.get("required") or []))
                props = schema_hint.get("properties") or {}
            else:
                props = {}
            # generate required fields
            for key in required:
                if key in {"resolution", "answer", "summary"}:
                    if self.rng.random() < p_policy:
                        obj[key] = self._policy_aware_resolution(user)
                    else:
                        obj[key] = "I am not sure, please clarify the request."
                elif key in {"policy_compliant", "compliant", "valid"}:
                    obj[key] = bool(self.rng.random() < p_policy)
                elif key in {"status", "state"}:
                    obj[key] = "resolved" if self.rng.random() < p_policy else "pending"
                elif key in {"score", "confidence"}:
                    obj[key] = round(0.4 + self.rng.random() * 0.6, 3)
                else:
                    obj[key] = self._generic_value_for(key, props.get(key))
            # optional extra fields
            for k, v in props.items():
                if k in obj:
                    continue
                if self.rng.random() < 0.25:
                    obj[k] = self._generic_value_for(k, v)
            # vanilla / schema-only sometimes returns wrong key names
            if self.method in {"vanilla", "schema_only"} and self.rng.random() < 0.18:
                key = next(iter(obj))
                camel = re.sub(r"_([a-z])", lambda m: m.group(1).upper(), key)
                obj[camel] = obj.pop(key)
            return json.dumps(obj, ensure_ascii=False)
        # No JSON requested, or method failed to produce JSON
        if self.rng.random() < 0.35:
            return "I cannot determine the correct action without more context. Please re-state the request."
        return self._policy_aware_resolution(user)

    def _policy_aware_resolution(self, user: str) -> str:
        if self.rng.random() < self.follows_policy:
            return "Action completed per policy."
        return "Action attempted, but policy constraints are not fully met."

    def _generic_value_for(self, key: str, spec: Any) -> Any:
        if isinstance(spec, dict):
            t = spec.get("type")
            if t == "string":
                return f"value-{self.rng.randint(0, 999)}"
            if t == "number" or t == "integer":
                return self.rng.randint(0, 100)
            if t == "boolean":
                return bool(self.rng.random() < 0.5)
            if t == "array":
                return []
        return f"value-{self.rng.randint(0, 999)}"
