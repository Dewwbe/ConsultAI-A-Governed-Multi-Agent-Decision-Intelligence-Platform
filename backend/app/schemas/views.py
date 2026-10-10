"""Least-privilege state views: each agent sees only what it needs."""
from __future__ import annotations

from typing import Any

from .state import EngagementState

_BASE = ("engagement_id", "workflow_id", "conversation_id", "preferences", "data_classification")

VIEWS: dict[str, tuple[str, ...]] = {
    "discovery_agent": _BASE + ("business_problem", "industry", "objectives", "constraints"),
    "research_agent": _BASE + ("engagement_spec",),
    "data_agent": _BASE + ("engagement_spec", "datasets"),
    "financial_agent": _BASE + ("engagement_spec", "analysis_results"),
    "risk_agent": _BASE + ("engagement_spec", "research_results", "financial_models", "analysis_results"),
    "solution_agent": _BASE + ("engagement_spec", "research_results", "analysis_results",
                               "financial_models", "risks", "guardian_feedback"),
    "report_agent": _BASE + ("engagement_spec", "recommendation", "options", "risks", "evaluation_scores",
                             "approval_status", "approval_feedback"),
}


def view_for(agent: str, state: EngagementState) -> dict[str, Any]:
    keys = VIEWS[agent]
    return {k: state[k] for k in keys if k in state}
