"""Evaluation engine. Quality is outcome + evidence + safety, never task completion alone.

Phase 4 replaces the heuristic scorers with LLM-judge / MLflow / Foundry evaluators;
the interface (EvaluationReport) stays stable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.tools.constraints import parse_constraints, violations


@dataclass
class EvaluationReport:
    scores: dict[str, float]
    penalties: dict[str, float] = field(default_factory=dict)
    issues: list[str] = field(default_factory=list)

    @property
    def quality(self) -> float:
        outcome = (self.scores["constraint_satisfaction"] + self.scores["completeness"]) / 2
        evidence = (self.scores["groundedness"] + self.scores["citation_validity"]) / 2
        safety = self.scores["policy_compliance"]
        base = 0.4 * outcome + 0.4 * evidence + 0.2 * safety
        return max(0.0, base - sum(self.penalties.values()))


def evaluate(state: dict[str, Any]) -> EvaluationReport:
    issues: list[str] = []
    research = state.get("research_results", [])
    cited = [r for r in research if r.get("source")]
    groundedness = (len(cited) / len(research)) if research else 0.0
    if groundedness < 1.0:
        issues.append("some research claims have no source")
    avg_conf = (sum(r.get("confidence", 0) for r in research) / len(research)) if research else 0.0

    options = state.get("options", [])
    parsed = parse_constraints(state.get("constraints", []))
    if parsed.unparsed:
        issues.append("constraints not machine-checked: " + "; ".join(parsed.unparsed))
    if options and (parsed.max_investment is not None or parsed.max_months is not None):
        ok = [o for o in options if not violations(o, parsed)]
        constraint = len(ok) / len(options)
        bad = violations(state.get("recommendation", {}), parsed)
        if bad:
            constraint = 0.0
            issues.append("recommendation violates constraints: " + "; ".join(bad))
    else:
        constraint = 1.0 if options else 0.0

    expected = ["research_results", "analysis_results", "financial_models", "risks", "options"]
    completeness = sum(1 for k in expected if state.get(k)) / len(expected)
    if completeness < 1:
        issues.append("missing sections: " + ", ".join(k for k in expected if not state.get(k)))

    decisions = state.get("guardian_decisions", [])
    blocked = sum(1 for d in decisions if d["action"] == "BLOCK")
    policy = 1.0 if not decisions else 1 - blocked / len(decisions)

    penalties: dict[str, float] = {}
    if avg_conf and avg_conf < 0.5:
        penalties["low_confidence"] = 0.05
    if state.get("tool_calls", 0) > 50:
        penalties["excess_tool_calls"] = 0.05
    if blocked:
        penalties["policy_violation"] = 0.1 * blocked

    return EvaluationReport(
        scores={"groundedness": groundedness, "citation_validity": groundedness,
                "constraint_satisfaction": constraint, "completeness": completeness,
                "policy_compliance": policy, "avg_evidence_confidence": avg_conf},
        penalties=penalties, issues=issues)
