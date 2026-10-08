"""LLM-judge evaluation, bounded by deterministic evidence.

The judge scores groundedness, task adherence and spots contradictions. LLM judges are noisy, so
they are never the only signal:

* groundedness  = min(share of claims whose quote was verified in the source, judge score), so the
  judge can lower the score but never raise it above what the evidence supports;
* contradictions found by code (recommendation figures that differ from the financial tool
  outputs, a recommendation that breaks a stated constraint) are added to the judge's;
* tool-call accuracy is computed from the trace, not asked of a model.

If the judge is unavailable the report says so (`judge_coverage` = 0) and the Guardian escalates
rather than trusting an unchecked recommendation. The `EvaluationReport` interface is unchanged.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.prompts import get_prompt
from app.schemas.json_schema import NUM, STR, arr, enum, obj
from app.tools.constraints import parse_constraints, violations

from .evaluator import EvaluationReport
from .llm import LLMGateway, LLMUnavailable, SchemaEscalation

JUDGE_SCHEMA = obj(
    groundedness=NUM, task_adherence=NUM,
    contradictions=arr(obj(description=STR, severity=enum("low", "medium", "high"))),
    reasoning=STR)
SEVERITY_PENALTY = {"low": 0.05, "medium": 0.25, "high": 0.5}
TOLERANCE = 1e-6


@dataclass
class Contradiction:
    description: str
    severity: str
    source: str = "judge"   # judge | deterministic


@dataclass
class JudgeResult:
    groundedness: float
    task_adherence: float
    contradictions: list[Contradiction] = field(default_factory=list)
    reasoning: str = ""


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


# -- deterministic checks -------------------------------------------------------------------------
def verified_ratio(research: list[dict[str, Any]]) -> float:
    return sum(1 for r in research if r.get("verified")) / len(research) if research else 0.0


def numeric_contradictions(state: dict[str, Any]) -> list[Contradiction]:
    """The recommendation must repeat the tool-computed figures of the option it names."""
    out: list[Contradiction] = []
    rec = state.get("recommendation") or {}
    models = {m["id"]: m for m in state.get("financial_models", [])}
    m = models.get(rec.get("id"))
    if rec and m is None:
        out.append(Contradiction(f"recommended option {rec.get('id')!r} has no financial model", "high",
                                 "deterministic"))
    if m:
        for rec_key, model_key in (("cost_usd", "investment"), ("roi", "roi"), ("npv", "npv")):
            if rec_key in rec and abs(rec[rec_key] - m[model_key]) > TOLERANCE * max(1.0, abs(m[model_key])):
                out.append(Contradiction(
                    f"recommendation {rec_key}={rec[rec_key]:,.4g} differs from the tool-computed "
                    f"{model_key}={m[model_key]:,.4g}", "high", "deterministic"))
    parsed = parse_constraints(state.get("constraints", []))
    bad = violations(rec, parsed) if rec else []
    if bad:
        out.append(Contradiction("recommendation breaks a stated constraint: " + "; ".join(bad), "high",
                                 "deterministic"))
    return out


def tool_call_accuracy(spans: list[dict[str, Any]], failures: list[dict[str, Any]]) -> float:
    tools = [s for s in spans if s["kind"] == "tool"]
    if not tools:
        return 1.0
    errors = sum(1 for s in tools if s["status"] == "error")
    bad_args = sum(1 for f in failures if f.get("type") == "invalid_schema" and "tool" in f)
    return _clamp(1 - (errors + bad_args) / (len(tools) + bad_args))


# -- the judge call ---------------------------------------------------------------------------------
def _stub_judgement(state: dict[str, Any]) -> dict[str, Any]:
    """What the offline stub 'judge' answers: the deterministic findings, so tests are meaningful."""
    rec = state.get("recommendation") or {}
    parsed = parse_constraints(state.get("constraints", []))
    return {"groundedness": verified_ratio(state.get("research_results", [])),
            "task_adherence": 0.4 if violations(rec, parsed) else 1.0,
            "contradictions": [], "reasoning": "offline stub judge"}


def run_judge(llm: LLMGateway, state: dict[str, Any]) -> JudgeResult:
    rec = state.get("recommendation") or {}
    res = llm.structured(
        agent="evaluator", task="guardian_eval", prompt=get_prompt("judge_evaluation"), schema=JUDGE_SCHEMA,
        risk_level="high",
        variables={
            "decision_question": (state.get("engagement_spec") or {}).get("decision_question", ""),
            "constraints": state.get("constraints", []),
            "claims": [{"claim": r["claim"], "quote": r.get("quote", ""), "source": r["source"]}
                       for r in state.get("research_results", [])],
            "financials": [{k: m[k] for k in ("id", "label", "investment", "annual_benefit", "roi", "npv")}
                           for m in state.get("financial_models", [])],
            "risks": [{k: r[k] for k in ("risk", "category", "probability", "impact")}
                      for r in state.get("risks", [])],
            "recommendation": {k: rec.get(k) for k in ("id", "name", "cost_usd", "roi", "npv", "rationale",
                                                       "assumptions", "constraint_violations")}},
        context={"stub_output": _stub_judgement(state)},
        data_classification=state.get("data_classification", "confidential"))
    c = res.content
    return JudgeResult(_clamp(c["groundedness"]), _clamp(c["task_adherence"]),
                       [Contradiction(x["description"], x["severity"]) for x in c["contradictions"]],
                       c["reasoning"])


def judge_evaluate(llm: LLMGateway, state: dict[str, Any], base: EvaluationReport,
                   spans: list[dict[str, Any]], failures: list[dict[str, Any]]) -> EvaluationReport:
    """Extend the heuristic report with judge scores and deterministic reliability checks."""
    research = state.get("research_results", [])
    cite = verified_ratio(research)
    contradictions = numeric_contradictions(state)
    scores = dict(base.scores)
    issues = list(base.issues)
    try:
        j = run_judge(llm, state)
    except (LLMUnavailable, SchemaEscalation) as exc:
        j = None
        issues.append(f"LLM judge unavailable ({type(exc).__name__}); relying on deterministic checks only")
    if j:
        contradictions += j.contradictions
        scores["groundedness"] = min(cite, j.groundedness)
        scores["task_adherence"] = j.task_adherence
    else:
        scores["groundedness"] = cite
        scores["task_adherence"] = 0.0  # unknown is not "fine"
    scores["citation_validity"] = cite
    scores["contradiction_free"] = max(0.0, 1.0 - sum(SEVERITY_PENALTY[c.severity] for c in contradictions))
    scores["tool_call_accuracy"] = tool_call_accuracy(spans, failures)
    scores["judge_coverage"] = 1.0 if j else 0.0
    issues += [f"contradiction ({c.severity}, {c.source}): {c.description}" for c in contradictions]
    if j and j.groundedness < cite:
        issues.append(f"judge rates groundedness {j.groundedness:.2f} below verified-citation share {cite:.2f}")
    return EvaluationReport(scores=scores, penalties=base.penalties, issues=issues)
