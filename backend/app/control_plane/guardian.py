"""Guardian: policy + risk classification -> ALLOW / BLOCK / MODIFY / RETRY / ESCALATE.

Deterministic rules run first. An optional LLM reviewer (Phase 4) can only make the
decision *stricter*, never looser.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .evaluator import EvaluationReport
from .policy import Decision, PolicyEngine


@dataclass
class GuardianDecision:
    action: str  # ALLOW | BLOCK | MODIFY | RETRY | ESCALATE
    risk_level: str
    risk_score: float
    reasons: list[str]
    subject: str = "workflow"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class Guardian:
    def __init__(self, policy: PolicyEngine):
        self.policy = policy

    def review_tool_call(self, agent: str, tool: str, args: dict[str, Any],
                         resource: str | None = None) -> GuardianDecision:
        res = self.policy.check_tool(agent, tool, resource)
        if res.decision is Decision.DENY:
            return GuardianDecision("BLOCK", "high", 1.0, [res.reason], subject=f"{agent}.{tool}")
        if res.decision is Decision.ESCALATE:
            return GuardianDecision("ESCALATE", "high", 0.9, [res.reason], subject=f"{agent}.{tool}")
        amount = args.get("investment") or args.get("amount")
        if isinstance(amount, (int, float)) and tool.startswith(("commit", "approve")):
            fin = self.policy.check_financial_commitment(float(amount))
            if fin.decision is Decision.ESCALATE:
                return GuardianDecision("ESCALATE", "high", 0.9, [fin.reason], subject=f"{agent}.{tool}")
        return GuardianDecision("ALLOW", "low", 0.1, [res.reason], subject=f"{agent}.{tool}")

    def review_recommendation(self, state: dict[str, Any], report: EvaluationReport) -> GuardianDecision:
        t = self.policy.thresholds
        reasons: list[str] = []
        score = 0.0

        rec = state.get("recommendation", {})
        cost = float(rec.get("cost_usd", 0))
        if cost > t.get("financial_commitment_usd", float("inf")):
            reasons.append(f"financial commitment ${cost:,.0f} exceeds policy threshold")
            score = max(score, 0.9)
        # A client-facing recommendation is always at least high-tier per policy.
        if self.policy.risk_tier("client_facing_recommendation") == "high":
            reasons.append("client-facing recommendation is a high-risk action")
            score = max(score, 0.75)
        top_risks = [r for r in state.get("risks", []) if r.get("risk_score", 0) >= 0.5
                     or r.get("requires_human_review")]
        if top_risks:
            reasons.append(f"{len(top_risks)} risk(s) flagged for human review")
            score = max(score, 0.6 + 0.05 * len(top_risks))
        if report.scores["groundedness"] < t.get("min_groundedness", 0.75):
            reasons.append("groundedness below minimum")
            score = max(score, 0.85)
        if report.scores["constraint_satisfaction"] < t.get("min_constraint_satisfaction", 0.9):
            reasons.append("constraint satisfaction below minimum")
            score = max(score, 0.85)

        score = min(score, 1.0)
        thresh = t.get("approval_risk_score", 0.7)
        level = "high" if score >= thresh else "medium" if score >= 0.4 else "low"
        if level == "high":
            return GuardianDecision("ESCALATE", level, score, reasons or ["high risk"])
        return GuardianDecision("ALLOW", level, score, reasons or ["within autonomous limits"])
