from __future__ import annotations

from typing import Any

from app.prompts import get_prompt
from app.schemas.json_schema import NUM, STR, arr, obj

from .base import BaseAgent

CATEGORIES = ["Financial", "Operational", "Market", "Regulatory", "Cybersecurity", "Technology",
              "Reputational", "People", "Implementation", "Third-party", "Data/privacy"]

SCHEMA = obj(risks=arr(obj(risk=STR, category=STR, probability=NUM, impact=NUM, mitigation=STR)))


class RiskAgent(BaseAgent):
    """LLM proposes risks with probability/impact; scoring is computed deterministically."""
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
        raw = self.ctx.llm.structured(
            agent=self.name, task="risk", prompt=get_prompt("risk_assessment"),
            schema=SCHEMA, context={"stub_output": stub}, risk_level="medium",
            variables={"categories": ", ".join(CATEGORIES),
                       "decision_question": view["engagement_spec"]["decision_question"],
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
            score = round(r["probability"] * r["impact"], 4)  # deterministic scoring
            risks.append({**r, "risk_score": score, "evidence": evidence_ids,
                          "requires_human_review": score >= 0.5})
        return {"risks": risks}
