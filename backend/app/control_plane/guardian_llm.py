"""Guardian layer 2: an LLM reviewer that may only make the deterministic decision STRICTER.

Strictness order: ALLOW < MODIFY < ESCALATE < BLOCK. The reviewer's answer is merged into the
rule-engine decision by taking the stricter action and the higher risk level, never the looser,
so a confused or manipulated reviewer cannot approve something the rules escalated.

RETRY is a routing step rather than a strictness level: it sends the recommendation back to the
Solution Agent once (policy: max_guardian_retries) before anything reaches a human; if retries are
exhausted the reviewer's RETRY counts as ESCALATE.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.prompts import get_prompt
from app.schemas.json_schema import STR, arr, enum, obj

from .evaluator import EvaluationReport
from .guardian import GuardianDecision
from .llm import LLMGateway, LLMUnavailable, SchemaEscalation

REVIEW_SCHEMA = obj(
    action=enum("ALLOW", "MODIFY", "RETRY", "ESCALATE", "BLOCK"),
    risk_level=enum("low", "medium", "high"),
    reasons=arr(STR), feedback=STR, caveats=arr(STR))

STRICTNESS = {"ALLOW": 0, "MODIFY": 1, "ESCALATE": 2, "BLOCK": 3}
LEVEL = {"low": 0, "medium": 1, "high": 2}
LEVEL_SCORE = {"low": 0.1, "medium": 0.5, "high": 0.8}
MAX_CAVEATS = 3


def stricter_action(a: str, b: str) -> str:
    return a if STRICTNESS[a] >= STRICTNESS[b] else b


def merge(base: GuardianDecision, review: dict[str, Any], retries_left: int) -> GuardianDecision:
    """Combine without ever loosening `base`. Pure function: easy to test exhaustively."""
    action = review["action"]
    if action == "RETRY":
        if retries_left > 0:
            return replace(base, action="RETRY", source="combined", feedback=review["feedback"][:1000],
                           reasons=[*base.reasons, *(f"reviewer: {r}" for r in review["reasons"])])
        action = "ESCALATE"  # nothing left to try: a human decides
    final = stricter_action(base.action, action)
    level = base.risk_level if LEVEL[base.risk_level] >= LEVEL[review["risk_level"]] else review["risk_level"]
    if final == "ESCALATE" and LEVEL[level] < LEVEL["high"] and base.action != "ESCALATE":
        level = "high"  # an escalation is by definition a high-risk outcome
    reasons = [*base.reasons, *(f"reviewer: {r}" for r in review["reasons"])]
    mods = dict(base.modifications)
    if final == "MODIFY" and review["caveats"]:
        mods = {"caveats": [c.strip() for c in review["caveats"] if c.strip()][:MAX_CAVEATS]}
    changed = (final, level) != (base.action, base.risk_level) or bool(review["reasons"])
    return replace(base, action=final, risk_level=level, reasons=reasons,
                   risk_score=max(base.risk_score, LEVEL_SCORE[level] if final != "ALLOW" else 0.0),
                   modifications=mods if final == "MODIFY" else {},
                   source="combined" if changed else base.source)


def llm_review(llm: LLMGateway, state: dict[str, Any], report: EvaluationReport,
               base: GuardianDecision) -> dict[str, Any] | None:
    """Ask the reviewer. Returns None if it is unavailable: the deterministic decision then
    stands (it is already the stricter-or-equal baseline), and the failure is logged by the gateway."""
    rec = state.get("recommendation") or {}
    try:
        res = llm.structured(
            agent="guardian", task="guardian_eval", prompt=get_prompt("guardian_review"), schema=REVIEW_SCHEMA,
            risk_level="high",
            variables={
                "decision_question": (state.get("engagement_spec") or {}).get("decision_question", ""),
                "constraints": state.get("constraints", []),
                "recommendation": {k: rec.get(k) for k in ("id", "name", "cost_usd", "roi", "npv", "rationale",
                                                           "assumptions", "constraint_violations")},
                "options": [{k: o.get(k) for k in ("id", "name", "cost_usd", "roi", "risk")}
                            for o in state.get("options", [])],
                "risks": sorted(state.get("risks", []), key=lambda r: -r["risk_score"])[:3],
                "scores": report.scores, "issues": report.issues,
                "base": {"action": base.action, "risk_level": base.risk_level, "reasons": base.reasons}},
            # offline stub: deliberately the loosest possible answer, to prove it cannot loosen anything
            context={"stub_output": {"action": "ALLOW", "risk_level": "low", "reasons": [], "feedback": "",
                                     "caveats": []}},
            data_classification=state.get("data_classification", "confidential"))
    except (LLMUnavailable, SchemaEscalation):
        return None
    return res.content
