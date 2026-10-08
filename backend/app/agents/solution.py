from __future__ import annotations

from typing import Any

from app.prompts import get_prompt
from app.schemas.json_schema import STR, arr, obj
from app.tools.constraints import ParsedConstraints, parse_constraints, violations

from .base import BaseAgent

SCHEMA = obj(rationale=STR, assumptions=arr(STR))
MAX_MODEL_ASSUMPTIONS = 4


def _risk_label(score: float) -> str:
    return "High" if score >= 0.5 else "Medium" if score >= 0.25 else "Low"


def _assumptions(best_model: dict[str, Any], best: dict[str, Any], parsed: ParsedConstraints,
                 any_feasible: bool, model_assumptions: list[str]) -> list[str]:
    """Explicit assumptions, built from tool outputs and unchecked inputs first; the model's own
    additions come last and are capped so they cannot bury the deterministic ones."""
    a = best_model["assumptions"]
    out = [(f"Benefits are flat over the {best_model['years']}-year horizon, discounted at "
            f"{a['discount_rate']:.0%}")]
    if "baseline_revenue" in a:
        out.append(f"Baseline is {a['baseline_year']} revenue of ${a['baseline_revenue']:,.0f} at a "
                   f"{a['baseline_margin']:.1%} operating margin, from the data warehouse")
    if best_model.get("uplift_pct") is not None:
        out.append(f"Annual benefit assumes a {best_model['uplift_pct']:.1%} revenue uplift: "
                   f"{best_model.get('benefit_assumption', 'no justification given')}")
    out += [f"Constraint not machine-checked (confirm manually): {c}" for c in parsed.unparsed]
    if not any_feasible:
        out.append("NO option satisfies every stated constraint; the closest is shown: "
                   + "; ".join(best["constraint_violations"]))
    seen = {x.lower() for x in out}
    for m in model_assumptions[:MAX_MODEL_ASSUMPTIONS]:
        if m.lower() not in seen:
            out.append(m)
            seen.add(m.lower())
    return out


class SolutionAgent(BaseAgent):
    """Generates alternatives and picks the best *defensible* option under the client's
    constraints. Selection is deterministic; the LLM only writes the rationale."""
    name = "solution_agent"

    def execute(self, view: dict[str, Any]) -> dict[str, Any]:
        spec = view["engagement_spec"]
        parsed = parse_constraints(spec.get("constraints", []))
        top_risk = max((r["risk_score"] for r in view.get("risks", [])), default=0.0)
        # Larger commitments inherit the portfolio's top risk; smaller ones are scaled down.
        max_inv = max((m["investment"] for m in view["financial_models"]), default=1)
        options, by_id = [], {}
        for m in view["financial_models"]:
            risk_score = round(top_risk * (0.5 + 0.5 * m["investment"] / max_inv), 3)
            opt = {"id": m["id"], "name": m["label"], "cost_usd": m["investment"],
                   "roi": m["roi"], "npv": m["npv"], "payback_years": m["payback_years"],
                   "risk_score": risk_score, "risk": _risk_label(risk_score),
                   "launch_months": m.get("launch_months")}
            opt["constraint_violations"] = violations(opt, parsed)
            opt["within_budget"] = not (parsed.max_investment is not None
                                        and m["investment"] > parsed.max_investment)
            opt["within_timeline"] = not (parsed.max_months is not None and opt["launch_months"] is not None
                                          and opt["launch_months"] > parsed.max_months)
            opt["within_constraints"] = not opt["constraint_violations"]
            options.append(opt)
            by_id[m["id"]] = m
        feasible = [o for o in options if o["within_constraints"]]
        # defensible = satisfies every constraint, then best risk-adjusted ROI. If nothing is
        # feasible the closest option is shown, flagged, and the evaluator/Guardian escalate it.
        pool = feasible or sorted(options, key=lambda o: len(o["constraint_violations"]))[:1] or options
        best = max(pool, key=lambda o: (-o["risk_score"] * 2 + o["roi"]))
        out = self.ctx.llm.structured(
            agent=self.name, task="strategy", prompt=get_prompt("solution_rationale"),
            schema=SCHEMA, risk_level="high",
            variables={"decision_question": spec["decision_question"],
                       "constraints": spec.get("constraints", []), "recommended": best,
                       "options": [{k: o[k] for k in ("id", "name", "cost_usd", "roi", "risk",
                                                      "constraint_violations")} for o in options],
                       "risks": sorted(view.get("risks", []), key=lambda r: -r["risk_score"])[:3],
                       "feedback": view.get("guardian_feedback", "")},
            context={"stub_output": {
                "rationale": (f"Option {best['id']} ({best['name']}) offers the best risk-adjusted "
                              f"return within the stated constraints."),
                "assumptions": []}},
            data_classification=view.get("data_classification", "confidential")).content
        recommendation = {**best, "rationale": out["rationale"], "alternatives_considered": len(options),
                          "assumptions": _assumptions(by_id[best["id"]], best, parsed, bool(feasible),
                                                      out["assumptions"])}
        return {"options": options, "recommendation": recommendation}
