from __future__ import annotations

import re
from typing import Any

from app.prompts import get_prompt
from app.schemas.json_schema import STR, arr, obj

from .base import BaseAgent

SCHEMA = obj(rationale=STR, assumptions=arr(STR))


def _budget(constraints: list[str]) -> float | None:
    for c in constraints:
        m = re.search(r"(\d+(?:\.\d+)?)\s*M", c)
        if m and re.search(r"budget", c, re.IGNORECASE):
            return float(m.group(1)) * 1_000_000
    return None


def _risk_label(score: float) -> str:
    return "High" if score >= 0.5 else "Medium" if score >= 0.25 else "Low"


class SolutionAgent(BaseAgent):
    """Generates alternatives and picks the best *defensible* option under the client's
    constraints. Selection is deterministic; the LLM only writes the rationale."""
    name = "solution_agent"

    def execute(self, view: dict[str, Any]) -> dict[str, Any]:
        spec = view["engagement_spec"]
        budget = _budget(spec.get("constraints", []))
        top_risk = max((r["risk_score"] for r in view.get("risks", [])), default=0.0)
        # Larger commitments inherit the portfolio's top risk; smaller ones are scaled down.
        max_inv = max((m["investment"] for m in view["financial_models"]), default=1)
        options = []
        for m in view["financial_models"]:
            risk_score = round(top_risk * (0.5 + 0.5 * m["investment"] / max_inv), 3)
            options.append({"id": m["id"], "name": m["label"], "cost_usd": m["investment"],
                            "roi": m["roi"], "npv": m["npv"], "payback_years": m["payback_years"],
                            "risk_score": risk_score, "risk": _risk_label(risk_score),
                            "within_budget": budget is None or m["investment"] <= budget})
        feasible = [o for o in options if o["within_budget"]]
        # defensible = feasible, then lowest risk bucket, then highest risk-adjusted ROI
        pool = feasible or options
        best = max(pool, key=lambda o: (-o["risk_score"] * 2 + o["roi"]))
        default_assumptions = ["Flat annual benefit", "10% discount rate"]
        out = self.ctx.llm.structured(
            agent=self.name, task="strategy", prompt=get_prompt("solution_rationale"),
            schema=SCHEMA, risk_level="high",
            variables={"decision_question": spec["decision_question"],
                       "constraints": spec.get("constraints", []), "recommended": best,
                       "options": [{k: o[k] for k in ("id", "name", "cost_usd", "roi", "risk")}
                                   for o in options],
                       "risks": sorted(view.get("risks", []), key=lambda r: -r["risk_score"])[:3]},
            context={"stub_output": {
                "rationale": (f"Option {best['id']} ({best['name']}) offers the best risk-adjusted "
                              f"return within the stated constraints."),
                "assumptions": default_assumptions}},
            data_classification=view.get("data_classification", "confidential")).content
        recommendation = {**best, "rationale": out["rationale"], "alternatives_considered": len(options),
                          "assumptions": out["assumptions"] or default_assumptions}
        return {"options": options, "recommendation": recommendation}
