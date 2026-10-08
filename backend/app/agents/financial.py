from __future__ import annotations

from typing import Any

from app.control_plane.executor import ToolArgsInvalid, ToolBlocked
from app.control_plane.llm import SchemaEscalation
from app.prompts import get_prompt
from app.schemas.json_schema import INT, NUM, STR, arr, obj

from .base import BaseAgent, InsufficientData

DISCOUNT_RATE = 0.10
MAX_YEARS = 10

CASE_SCHEMA = obj(cases=arr(obj(id=STR, label=STR, investment=NUM, uplift_pct=NUM, launch_months=NUM,
                                years=INT, benefit_assumption=STR)))


class FinancialAgent(BaseAgent):
    """The model proposes investment cases and the revenue uplift it believes each achieves; every
    dollar figure that follows (baseline, margin, growth, benefit, ROI, NPV...) is computed by a
    registered tool from warehouse data, so each number traces to a tool call."""
    name = "financial_agent"

    def _baseline(self, view: dict[str, Any]) -> dict[str, Any]:
        by_col: dict[str, dict[str, float]] = {}
        for a in view.get("analysis_results", []):
            if a.get("purpose") in {"baseline_revenue", "baseline_cost"}:
                col = "revenue" if a["purpose"] == "baseline_revenue" else "cost"
                by_col[col] = {str(r["year"]): float(r[col]) for r in a["rows"]}
        years = sorted(set(by_col.get("revenue", {})) & set(by_col.get("cost", {})))
        if not years:
            raise InsufficientData("no revenue/cost baseline from the data warehouse")
        y = years[-1]
        revenue, cost = by_col["revenue"][y], by_col["cost"][y]
        margin = self.ctx.tools.call(self.name, "calculate_margin", {"revenue": revenue, "cost": cost})["margin"]
        growth = None
        if len(years) >= 2:
            growth = self.ctx.tools.call(self.name, "calculate_growth", {
                "previous": by_col["revenue"][years[-2]], "current": revenue})["growth"]
        return {"year": y, "revenue": revenue, "cost": cost, "margin": margin, "revenue_growth": growth,
                "source": "finance.revenue, finance.costs"}

    def execute(self, view: dict[str, Any]) -> dict[str, Any]:
        spec = view["engagement_spec"]
        base = self._baseline(view)
        if base["margin"] <= 0:
            raise InsufficientData(
                f"baseline margin {base['margin']:.1%} is not positive: no benefit can be derived")

        def uplift_for(target_benefit: float) -> float:  # stub only: reproduce the demo benefits
            return target_benefit / (base["revenue"] * base["margin"])

        stub = {"cases": [
            {"id": "A", "label": "Full expansion", "investment": 8_000_000, "uplift_pct": uplift_for(2_400_000),
             "launch_months": 18, "years": 5, "benefit_assumption": "Stub placeholder"},
            {"id": "B", "label": "Pilot", "investment": 2_000_000, "uplift_pct": uplift_for(700_000),
             "launch_months": 9, "years": 5, "benefit_assumption": "Stub placeholder"},
            {"id": "C", "label": "Partnership", "investment": 3_000_000, "uplift_pct": uplift_for(900_000),
             "launch_months": 12, "years": 5, "benefit_assumption": "Stub placeholder"},
        ]}
        question_rows = [r for a in view.get("analysis_results", []) if a.get("purpose") == "question"
                         for r in a["rows"][:20]]
        cases = self.ctx.llm.structured(
            agent=self.name, task="financial", prompt=get_prompt("financial_cases"),
            schema=CASE_SCHEMA, context={"stub_output": stub}, risk_level="medium",
            variables={"decision_question": spec["decision_question"],
                       "constraints": spec.get("constraints", []), "baseline": base,
                       "other_data": question_rows},
            data_classification=view.get("data_classification", "confidential")).content["cases"]

        models = []
        for c in cases:
            if (c["investment"] <= 0 or not 0 < c["uplift_pct"] <= 0.5 or not 1 <= c["years"] <= MAX_YEARS
                    or c["launch_months"] <= 0):
                self._reject(c, "out of range")
                continue
            try:
                models.append(self._model(c, base))
            except (ToolArgsInvalid, ToolBlocked, ValueError) as exc:
                self._reject(c, str(exc)[:200])
        if not models:
            raise SchemaEscalation("financial_cases: no valid investment case was proposed")
        return {"financial_models": models}

    def _reject(self, case: dict[str, Any], why: str) -> None:
        self.ctx.log["failures"].append({
            "type": "invalid_case", "case": case.get("id"), "reason": why, "investment": case.get("investment"),
            "uplift_pct": case.get("uplift_pct"), "years": case.get("years")})

    def _model(self, c: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
        def t(tool: str, args: dict[str, Any]) -> Any:
            return self.ctx.tools.call(self.name, tool, args)

        derived = t("derive_annual_benefit", {"baseline_revenue": base["revenue"],
                                              "uplift_pct": c["uplift_pct"], "margin": base["margin"]})
        benefit = derived["annual_benefit"]
        inv = {"investment": c["investment"], "annual_benefit": benefit}
        roi = t("calculate_roi", {**inv, "years": c["years"]})
        pay = t("calculate_payback", inv)
        npv = t("calculate_npv", {"rate": DISCOUNT_RATE,
                                  "cashflows": [-c["investment"]] + [benefit] * c["years"]})
        scen = t("scenario_analysis", {**inv, "years": c["years"]})
        sens = t("sensitivity_analysis", {**inv, "years": c["years"]})
        return {"id": c["id"], "label": c["label"], "investment": c["investment"], "annual_benefit": benefit,
                "years": c["years"], "launch_months": c["launch_months"], "uplift_pct": c["uplift_pct"],
                "benefit_assumption": c["benefit_assumption"], **roi, **pay, **npv,
                "scenarios": scen, "sensitivity": sens,
                "assumptions": {"discount_rate": DISCOUNT_RATE, "benefit_flat": True,
                                "baseline_year": base["year"], "baseline_revenue": base["revenue"],
                                "baseline_margin": base["margin"]}}
