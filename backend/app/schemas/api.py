"""Public API models. These are the contract the generated TypeScript client is built from,
so change them deliberately (see tests/test_api_contract.py)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .models import Evidence, GuardianDecision, TableColumns
from .state import EngagementState

Status = Literal["awaiting_approval", "completed", "rejected", "escalated"]
Classification = Literal["confidential", "internal", "public"]


class EngagementRequest(BaseModel):
    business_problem: str = Field(min_length=5, max_length=4000)
    industry: str = Field(default="", max_length=200)
    objectives: list[str] = Field(default_factory=list, max_length=20)
    constraints: list[str] = Field(default_factory=list, max_length=20)
    data_classification: Classification = "confidential"


class ApprovalRequest(BaseModel):
    decision: Literal["approve", "modify", "reject"]
    changes: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class BudgetUsage(BaseModel):
    tokens: int
    cost_usd: float
    tool_calls: int


class EngagementDetail(BaseModel):
    workflow_id: str
    status: Status
    pending_node: list[str]
    halted_reason: str | None = None
    state: EngagementState
    guardian_decisions: list[GuardianDecision]
    metrics: dict[str, float | int | None]
    budget: BudgetUsage


class EngagementSummary(BaseModel):
    workflow_id: str
    status: Status
    business_problem: str
    industry: str
    created_at: str
    risk_level: str | None = None
    recommendation: str | None = None
    cost_usd: float


class EngagementList(BaseModel):
    items: list[EngagementSummary]
    total: int
    limit: int
    offset: int


class SpanOut(BaseModel):
    span_id: str
    parent_id: str | None
    name: str
    kind: str
    attributes: dict[str, Any]
    start: float
    latency_ms: float
    status: str
    error: str | None


class TraceOut(BaseModel):
    trace_id: str
    workflow_id: str
    span_count: int
    input_tokens: int
    output_tokens: int
    cost_usd: float
    tool_calls: int
    tool_errors: int
    spans: list[SpanOut]


class Health(BaseModel):
    status: Literal["ok"]
    llm_provider: str


class RetrievalRecordOut(BaseModel):
    retrieval_id: str
    query: str
    index: str
    document_ids: list[str]
    chunk_ids: list[str]
    scores: list[float]
    content_hashes: list[str]
    retrieved_at: str
    filters: dict[str, Any]
    embedding_model: str
    reranker: str
    index_version: str
    k: int


class SourceSummary(BaseModel):
    source: str
    doc_ids: list[str]
    claims: int


class RejectedClaim(BaseModel):
    reason: Literal["unsupported_claim", "unverified_citation"]
    doc_ref: str
    chunk_id: str | None = None


class EvidenceOut(BaseModel):
    workflow_id: str
    claims: list[Evidence]
    sources: list[SourceSummary]
    retrievals: list[RetrievalRecordOut]
    rejected_claims: list[RejectedClaim]


class QueryRun(BaseModel):
    query: str
    row_count: int


class TablesOut(BaseModel):
    workflow_id: str
    datasets: list[str]
    table_context: dict[str, TableColumns]
    queries: list[QueryRun]


class ReplayOut(BaseModel):
    retrieval_id: str
    reproduced: bool
    error: str | None = None
    evidence: list[Evidence]
