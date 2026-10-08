"""Typed shapes of the engagement state. They are what the OpenAPI schema (and therefore the
generated TypeScript client) exposes, so keep them in step with what the agents produce."""
from __future__ import annotations

from typing import Any, NotRequired

from typing_extensions import TypedDict


class EngagementSpec(TypedDict):
    business_objective: str
    decision_question: str
    success_metrics: list[str]
    constraints: list[str]
    required_analysis: list[str]
    required_data: list[str]
    required_agents: list[str]


class Evidence(TypedDict):
    claim: str
    source: str
    publication_date: str
    retrieved_at: str
    evidence: str          # the retrieved passage the claim rests on
    confidence: float
    relevance: float
    doc_id: NotRequired[str]
    chunk_id: NotRequired[str]
    quote: NotRequired[str]        # verbatim span of `evidence` that supports the claim
    verified: NotRequired[bool]    # quote was found in the cited chunk


class AnalysisResult(TypedDict):
    query: str
    rows: list[dict[str, Any]]


class SensitivityPoint(TypedDict):
    benefit_delta: float
    roi: float


class FinancialAssumptions(TypedDict):
    discount_rate: float
    benefit_flat: bool


class FinancialModel(TypedDict):
    id: str
    label: str
    investment: float
    annual_benefit: float
    years: int
    roi: float
    total_benefit: float
    net_gain: float
    payback_years: float | None
    reason: NotRequired[str]
    npv: float
    rate: float
    periods: int
    scenarios: dict[str, float]
    sensitivity: list[SensitivityPoint]
    assumptions: FinancialAssumptions


class Risk(TypedDict):
    risk: str
    category: str
    probability: float
    impact: float
    mitigation: str
    risk_score: float
    evidence: list[str]
    requires_human_review: bool


class Option(TypedDict):
    id: str
    name: str
    cost_usd: float
    roi: float
    npv: float
    payback_years: float | None
    risk_score: float
    risk: str
    within_budget: bool


class Recommendation(Option):
    rationale: str
    alternatives_considered: int
    assumptions: list[str]


class GuardianDecision(TypedDict):
    action: str
    risk_level: str
    risk_score: float
    reasons: list[str]
    subject: str


class ApprovalFeedback(TypedDict):
    decision: str
    changes: dict[str, Any]
    reason: str


class Report(TypedDict):
    markdown: str


class TableColumns(TypedDict, total=False):
    description: str
    columns: dict[str, str]
    owner: str
    sensitivity: str
