"""Engagement state shared by the LangGraph workflow.

Agents never receive the whole state; see ``views.py`` for the per-agent slices.
"""
from __future__ import annotations

from enum import Enum
from typing import Any

from typing_extensions import TypedDict  # pydantic needs this variant on Python < 3.12

from . import models as m


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ApprovalStatus(str, Enum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    MODIFIED = "modified"
    REJECTED = "rejected"


class EngagementState(TypedDict, total=False):
    # Identity
    conversation_id: str
    workflow_id: str
    engagement_id: str
    # User
    user_id: str
    preferences: dict[str, Any]
    data_classification: str
    # Objective
    business_problem: str
    industry: str
    objectives: list[str]
    constraints: list[str]
    # Discovery
    engagement_spec: m.EngagementSpec
    questions: list[str]
    required_data: list[str]
    # Research
    research_results: list[m.Evidence]
    citations: list[str]
    # Data
    datasets: list[str]
    table_context: dict[str, m.TableColumns]
    analysis_results: list[m.AnalysisResult]
    # Financial
    financial_models: list[m.FinancialModel]
    # Risk
    risks: list[m.Risk]
    # Strategy
    options: list[m.Option]
    recommendation: m.Recommendation
    # Evaluation
    evaluation_scores: dict[str, float]
    # Governance
    risk_level: str
    approval_required: bool
    approval_status: str
    approval_feedback: m.ApprovalFeedback
    guardian_decisions: list[m.GuardianDecision]
    # Reliability
    retry_count: int
    failures: list[dict[str, Any]]
    # Economics
    token_usage: dict[str, int]
    cost: float
    tool_calls: int
    # Workflow
    halted: str  # reason an agent escalated; downstream agents skip and a human reviews
    current_step: str
    deadline: str
    report: m.Report
