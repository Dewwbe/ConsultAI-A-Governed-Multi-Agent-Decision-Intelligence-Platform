"""Model router: picks a model tier by task, risk, budget and data classification."""
from __future__ import annotations

from dataclasses import dataclass

from .policy import PolicyEngine

TASK_TIER = {
    "intent_classification": "small", "schema_repair": "small", "simple_sql": "small",
    "routing": "small", "extraction": "small",
    "research_synthesis": "medium", "summarization": "medium", "report": "medium",
    "strategy": "reasoning", "risk": "reasoning", "financial": "reasoning",
    "guardian_eval": "reasoning",
}
# Price per 1K tokens (illustrative placeholders; load real prices from model_registry)
PRICE_PER_1K = {"small": 0.0005, "medium": 0.003, "reasoning": 0.015}


class NoProviderAvailable(RuntimeError):
    """No provider is both permitted for this data classification and currently available."""


@dataclass(frozen=True)
class Route:
    tier: str
    provider: str
    model_env_key: str
    est_cost_usd: float


class ModelRouter:
    def __init__(self, policy: PolicyEngine, providers: list[str] | None = None, tier_boost: int = 0):
        self.policy = policy
        self.tier_boost = tier_boost  # set while quality is degraded: use a stronger model
        self.providers = providers or ["azure_openai", "openai", "gemini", "local"]

    def route(self, task: str, *, risk_level: str = "low", data_classification: str = "confidential",
              est_tokens: int = 2000, remaining_budget_usd: float = 1.0,
              unavailable: set[str] | None = None, tier_override: str | None = None) -> Route:
        tier = TASK_TIER.get(task, "medium")
        if risk_level == "high" and tier == "small":
            tier = "medium"
        order = ["reasoning", "medium", "small"]
        if tier_override:  # explicit escalation (e.g. fallback model): never budget-downgraded
            tier = tier_override
        else:
            if self.tier_boost and task != "schema_repair":  # the cheap repair step stays cheap
                strong_first = ["small", "medium", "reasoning"]
                tier = strong_first[min(len(strong_first) - 1, strong_first.index(tier) + self.tier_boost)]
            # Downgrade when the budget cannot cover the chosen tier
            while tier != "small" and PRICE_PER_1K[tier] * est_tokens / 1000 > remaining_budget_usd:
                tier = order[order.index(tier) + 1]
        unavailable = unavailable or set()
        for provider in self.providers:
            if provider in unavailable:
                continue
            if not self.policy.provider_allowed(data_classification, provider):
                continue
            return Route(tier, provider, f"MODEL_{tier.upper()}",
                         PRICE_PER_1K[tier] * est_tokens / 1000)
        permitted = [p for p in self.providers if self.policy.provider_allowed(data_classification, p)]
        if not permitted:
            raise NoProviderAvailable(f"no provider is permitted for '{data_classification}' data")
        raise NoProviderAvailable(
            f"every provider permitted for '{data_classification}' data is unavailable ({', '.join(permitted)})")
