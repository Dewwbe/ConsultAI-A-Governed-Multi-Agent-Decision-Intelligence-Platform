from __future__ import annotations

from typing import Any

from app.prompts import get_prompt
from app.schemas.json_schema import STR, arr, enum, obj

from .base import BaseAgent

SCHEMA = obj(
    business_objective=STR, decision_question=STR, success_metrics=arr(STR), constraints=arr(STR),
    required_analysis=arr(STR), required_data=arr(STR),
    required_agents=arr(enum("research", "data", "financial", "risk", "solution")),
)


class DiscoveryAgent(BaseAgent):
    """Turns a vague question into a structured engagement specification."""
    name = "discovery_agent"

    def execute(self, view: dict[str, Any]) -> dict[str, Any]:
        problem = view["business_problem"]
        stub = {
            "business_objective": (view.get("objectives") or ["Increase revenue"])[0],
            "decision_question": problem,
            "success_metrics": ["Revenue growth", "ROI", "Payback period"],
            "constraints": view.get("constraints", []),
            "required_analysis": ["Market size", "Competition", "Customer demand",
                                  "Financial viability", "Regulatory risk"],
            "required_data": ["Market reports", "Historical revenue", "Operating costs",
                              "Competitor data"],
            "required_agents": ["research", "data", "financial", "risk", "solution"],
        }
        res = self.ctx.llm.structured(
            agent=self.name, task="extraction", prompt=get_prompt("discovery"), schema=SCHEMA,
            variables={"business_problem": problem, "industry": view.get("industry") or "unspecified",
                       "objectives": view.get("objectives", []), "constraints": view.get("constraints", [])},
            context={"stub_output": stub},
            data_classification=view.get("data_classification", "confidential"))
        spec = res.content
        # The client's stated constraints are authoritative: never let the model drop or rewrite them.
        spec["constraints"] = list(view.get("constraints", [])) or spec["constraints"]
        return {"engagement_spec": spec, "required_data": spec["required_data"],
                "questions": [f"Clarify: {a}" for a in spec["required_analysis"][:3]]}
