"""Evaluation engine. Quality is outcome + evidence + safety, never task completion alone.

Phase 4 replaces the heuristic scorers with LLM-judge / MLflow / Foundry evaluators;
the interface (EvaluationReport) stays stable.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


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


def _parse_budget(constraints: list[str]) -> float | None:
    for c in constraints:
        m = re.search(r"(\d+(?:\.\d+)?)\s*M", c)
        if m and re.search(r"budget", c, re.IGNORECASE):
            return float(m.group(1)) * 1_000_000
    return None


def evaluate(state: dict[str, Any]) -> EvaluationReport:
    issues: list[str] = []
    research = state.get("research_results", [])
    cited = [r for r in research if r.get("source")]
    groundedness = (len(cited) / len(research)) if research else 0.0
    if groundedness < 1.0:
        issues.append("some research claims have no source")
    avg_conf = (sum(r.get("confidence", 0) for r in research) / len(research)) if research else 0.0

    options = state.get("options", [])
    budget = _parse_budget(state.get("constraints", []))
    if options and budget is not None:
        ok = [o for o in options if o.get("cost_usd", 0) <= budget]
        constraint = len(ok) / len(options)
        rec = state.get("recommendation", {})
        if rec.get("cost_usd", 0) > budget:
            constraint = 0.0
            issues.append("recommendation violates budget constraint")
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
