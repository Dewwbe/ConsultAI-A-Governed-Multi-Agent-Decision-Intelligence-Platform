from __future__ import annotations

from typing import Any

from app.knowledge.risk_taxonomy import CATEGORIES, calibrate, similar_history
from app.prompts import get_prompt
from app.schemas.json_schema import NUM, STR, arr, obj

from .base import BaseAgent

SCHEMA = obj(risks=arr(obj(risk=STR, category=STR, probability=NUM, impact=NUM, mitigation=STR)))


class RiskAgent(BaseAgent):
    """The model proposes risks against the taxonomy guidance and historical analogues (fetched with
    the `risk_lookup` tool); ratings outside a category's band are calibrated, and scoring is
    computed deterministically."""
    name = "risk_agent"

    def execute(self, view: dict[str, Any]) -> dict[str, Any]:
        evidence_ids = [r["source"] for r in view.get("research_results", [])][:2]
        stub = {"risks": [
            {"risk": "Regulatory approval delay", "category": "Regulatory", "probability": 0.65,
             "impact": 0.8, "mitigation": "Engage local counsel early; stage licensing"},
            {"risk": "Demand shortfall vs plan", "category": "Market", "probability": 0.4,
             "impact": 0.6, "mitigation": "Pilot first; stage-gate further investment"},
            {"risk": "Partner execution risk", "category": "Third-party", "probability": 0.3,
             "impact": 0.5, "mitigation": "Performance-linked contract terms"},
        ]}
        spec = view["engagement_spec"]
        query = " ".join([spec["decision_question"], *spec.get("constraints", [])])
        reference = self.ctx.tools.call(self.name, "risk_lookup", {"query": query})
        raw = self.ctx.llm.structured(
            agent=self.name, task="risk", prompt=get_prompt("risk_assessment"),
            schema=SCHEMA, context={"stub_output": stub}, risk_level="medium",
            variables={"categories": ", ".join(CATEGORIES),
                       "guidance": [{"category": g["category"], "description": g["description"],
                                     "probability_band": g["probability"], "impact_band": g["impact"]}
                                    for g in reference["guidance"]],
                       "history": [{k: h[k] for k in ("id", "category", "risk", "probability", "impact",
                                                       "outcome")} for h in reference["history"]],
                       "decision_question": spec["decision_question"],
                       "research": [r["claim"] for r in view.get("research_results", [])],
                       "financials": [{k: m[k] for k in ("id", "label", "investment", "roi", "npv")}
                                      for m in view.get("financial_models", [])]},
            data_classification=view.get("data_classification", "confidential")).content["risks"]
        risks = []
        for r in raw:
            if r["category"] not in CATEGORIES:
                self.ctx.log["failures"].append({"type": "unknown_risk_category", "value": r["category"]})
                continue
            if not (0 <= r["probability"] <= 1 and 0 <= r["impact"] <= 1):
                self.ctx.log["failures"].append({"type": "risk_out_of_range", "risk": r["risk"]})
                continue
            prob, impact, note = calibrate(r["category"], r["probability"], r["impact"])
            if note:
                self.ctx.log["failures"].append({"type": "risk_calibrated", "risk": r["risk"], "note": note})
            score = round(prob * impact, 4)  # deterministic scoring
            risks.append({**r, "probability": prob, "impact": impact, "risk_score": score,
                          "evidence": evidence_ids, "requires_human_review": score >= 0.5,
                          **({"calibration": note} if note else {}),
                          "precedents": [h["id"] for h in similar_history(
                              f"{r['risk']} {query}", r["category"])]})
        return {"risks": risks}
