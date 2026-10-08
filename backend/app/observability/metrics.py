"""Metric definitions from the spec (intent, tool, safety, business, economics)."""
from __future__ import annotations

from typing import Any


def cost_per_successful_task(total_cost: float, successful_tasks: int) -> float | None:
    return None if successful_tasks == 0 else total_cost / successful_tasks


def engagement_metrics(summary: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    tool_calls = summary["tool_calls"]
    failures = state.get("failures", [])
    decisions = state.get("guardian_decisions", [])
    initial = sum(1 for s in summary["spans"]
                  if s["kind"] == "llm" and s["attributes"].get("consultai.stage") == "initial")
    tasks_total = max(1, len([s for s in summary["spans"] if s["kind"] == "agent"]))
    tasks_ok = len([s for s in summary["spans"] if s["kind"] == "agent" and s["status"] == "ok"])
    return {
        "tool_call_success_rate": 1.0 if tool_calls == 0 else 1 - summary["tool_errors"] / tool_calls,
        # share of structured LLM calls whose first attempt failed schema validation
        "invalid_schema_rate": 0.0 if not initial else sum(
            1 for f in failures if f.get("type") == "invalid_schema" and f.get("stage") == "initial"
        ) / initial,
        "schema_escalations": sum(1 for f in failures if f.get("type") == "schema_escalation"),
        "escalation_rate": 0.0 if not decisions else
            sum(1 for d in decisions if d["action"] == "ESCALATE") / len(decisions),
        "unauthorized_action_rate": 0.0 if not decisions else
            sum(1 for d in decisions if d["action"] == "BLOCK") / len(decisions),
        "task_completion_rate": tasks_ok / tasks_total,
        "input_tokens": summary["input_tokens"],
        "output_tokens": summary["output_tokens"],
        "total_engagement_cost": summary["cost_usd"],
        "cost_per_task": summary["cost_usd"] / tasks_total,
        "cost_per_successful_task": cost_per_successful_task(summary["cost_usd"], tasks_ok),
    }
