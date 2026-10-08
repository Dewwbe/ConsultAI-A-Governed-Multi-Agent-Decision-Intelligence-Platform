from __future__ import annotations

from typing import Any

from app.control_plane.llm import SchemaEscalation
from app.prompts import get_prompt
from app.schemas.json_schema import INT, NUM, STR, arr, obj

from .base import BaseAgent

CASE_SCHEMA = obj(cases=arr(obj(id=STR, label=STR, investment=NUM, annual_benefit=NUM, years=INT)))


class FinancialAgent(BaseAgent):
    """LLM chooses which cases/calculations; deterministic tools compute every number."""
    name = "financial_agent"

    def execute(self, view: dict[str, Any]) -> dict[str, Any]:
        stub = {"cases": [
            {"id": "A", "label": "Full expansion", "investment": 8_000_000, "annual_benefit": 2_400_000, "years": 5},
            {"id": "B", "label": "Pilot", "investment": 2_000_000, "annual_benefit": 700_000, "years": 5},
            {"id": "C", "label": "Partnership", "investment": 3_000_000, "annual_benefit": 900_000, "years": 5},
        ]}
        cases = self.ctx.llm.structured(
            agent=self.name, task="financial", prompt=get_prompt("financial_cases"),
            schema=CASE_SCHEMA, context={"stub_output": stub}, risk_level="medium",
            variables={"decision_question": view["engagement_spec"]["decision_question"],
                       "constraints": view["engagement_spec"].get("constraints", []),
                       "analysis_results": view.get("analysis_results", [])},
            data_classification=view.get("data_classification", "confidential")).content["cases"]

        models = []
        for c in cases:
            if c["investment"] <= 0 or c["annual_benefit"] < 0 or not 1 <= c["years"] <= 10:
                self.ctx.log["failures"].append({"type": "invalid_case", "case": c.get("id")})
                continue
            base = {"investment": c["investment"], "annual_benefit": c["annual_benefit"]}
            roi = self.ctx.tools.call(self.name, "calculate_roi", {**base, "years": c["years"]})
            pay = self.ctx.tools.call(self.name, "calculate_payback", base)
            npv = self.ctx.tools.call(self.name, "calculate_npv", {
                "rate": 0.10, "cashflows": [-c["investment"]] + [c["annual_benefit"]] * c["years"]})
            scen = self.ctx.tools.call(self.name, "scenario_analysis", {**base, "years": c["years"]})
            sens = self.ctx.tools.call(self.name, "sensitivity_analysis", {**base, "years": c["years"]})
            models.append({**c, **roi, **pay, **npv, "scenarios": scen, "sensitivity": sens,
                           "assumptions": {"discount_rate": 0.10, "benefit_flat": True}})
        if not models:
            raise SchemaEscalation("financial_cases: no valid investment case was proposed")
        return {"financial_models": models}
