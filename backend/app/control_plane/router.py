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


@dataclass(frozen=True)
class Route:
    tier: str
    provider: str
    model_env_key: str
    est_cost_usd: float


class ModelRouter:
    def __init__(self, policy: PolicyEngine, providers: list[str] | None = None):
        self.policy = policy
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
        raise RuntimeError(f"no provider permitted for classification '{data_classification}'")
