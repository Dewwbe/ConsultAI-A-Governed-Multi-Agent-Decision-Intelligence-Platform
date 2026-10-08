"""Layer 1 — deterministic policy engine with versioned cache. No LLM involved."""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml


class Decision(str, Enum):
    ALLOW = "ALLOW"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


@dataclass(frozen=True)
class PolicyResult:
    decision: Decision
    reason: str
    policy_version: str


class PolicyEngine:
    def __init__(self, policy: dict[str, Any], cache_ttl_sec: int = 300):
        self._policy = policy
        self._ttl = cache_ttl_sec
        self._cache: dict[tuple, tuple[float, PolicyResult]] = {}
        self.cache_hits = 0
        self.cache_misses = 0

    @classmethod
    def from_file(cls, path: str | Path) -> PolicyEngine:
        return cls(yaml.safe_load(Path(path).read_text()))

    @property
    def version(self) -> str:
        return str(self._policy.get("version", "unversioned"))

    @property
    def thresholds(self) -> dict[str, float]:
        return self._policy.get("thresholds", {})

    def agent_spec(self, agent: str) -> dict[str, Any]:
        return self._policy.get("agents", {}).get(agent, {})

    def reload(self, policy: dict[str, Any]) -> None:
        """Replacing the policy changes the version, which invalidates cache keys."""
        self._policy = policy
        self._cache.clear()

    def check_tool(self, agent: str, tool: str, resource: str | None = None) -> PolicyResult:
        key = (agent, tool, resource, self.version)
        now = time.monotonic()
        hit = self._cache.get(key)
        if hit and now - hit[0] < self._ttl:
            self.cache_hits += 1
            return hit[1]
        self.cache_misses += 1
        result = self._evaluate(agent, tool, resource)
        self._cache[key] = (now, result)
        return result

    def _evaluate(self, agent: str, tool: str, resource: str | None) -> PolicyResult:
        v = self.version
        spec = self._policy.get("agents", {}).get(agent)
        if spec is None:
            return PolicyResult(Decision.DENY, f"unknown agent '{agent}'", v)
        if tool in spec.get("blocked_tools", []):
            return PolicyResult(Decision.DENY, f"'{tool}' explicitly blocked for {agent}", v)
        if tool in spec.get("requires_approval", []):
            return PolicyResult(Decision.ESCALATE, f"'{tool}' requires human approval", v)
        if tool not in spec.get("allowed_tools", []):
            return PolicyResult(Decision.DENY, f"'{tool}' not in allow-list for {agent}", v)
        tables = spec.get("allowed_tables")
        if resource and tables is not None and resource not in tables:
            return PolicyResult(Decision.DENY, f"table '{resource}' not permitted for {agent}", v)
        return PolicyResult(Decision.ALLOW, "allowed by policy", v)

    def check_financial_commitment(self, amount_usd: float) -> PolicyResult:
        limit = self.thresholds.get("financial_commitment_usd", 0)
        if amount_usd > limit:
            return PolicyResult(Decision.ESCALATE, f"${amount_usd:,.0f} exceeds ${limit:,.0f}", self.version)
        return PolicyResult(Decision.ALLOW, "within financial threshold", self.version)

    def provider_allowed(self, data_classification: str, provider: str) -> bool:
        allowed = (self._policy.get("data_classification", {})
                   .get(data_classification, {}).get("allowed_providers", []))
        return provider in allowed

    def risk_tier(self, action: str) -> str:
        for tier, actions in self._policy.get("risk_tiers", {}).items():
            if action in actions:
                return tier
        return "high"  # unknown actions are treated as high risk
