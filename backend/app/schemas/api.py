"""Public API models. These are the contract the generated TypeScript client is built from,
so change them deliberately (see tests/test_api_contract.py)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .models import Evidence, GuardianDecision, TableColumns
from .state import EngagementState

Status = Literal["queued", "running", "awaiting_approval", "completed", "rejected", "escalated", "failed"]
Classification = Literal["confidential", "internal", "public"]


class EngagementRequest(BaseModel):
    business_problem: str = Field(min_length=5, max_length=4000)
    industry: str = Field(default="", max_length=200)
    objectives: list[str] = Field(default_factory=list, max_length=20)
    constraints: list[str] = Field(default_factory=list, max_length=20)
    data_classification: Classification = "confidential"


class ApprovalRequest(BaseModel):
    decision: Literal["approve", "modify", "reject"]
    changes: dict[str, Any] = Field(default_factory=dict, description="modify only: rationale, assumptions")
    reason: str = Field(default="", max_length=4000, description="required for modify and reject")


class BudgetUsage(BaseModel):
    tokens: int
    cost_usd: float
    tool_calls: int


class EngagementDetail(BaseModel):
    workflow_id: str
    status: Status
    pending_node: list[str]
    halted_reason: str | None = None
    error: str | None = None
    policy_version: str | None = None  # the policy that governed this run, fixed when it started
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


class RedactionOut(BaseModel):
    payloads_redacted: bool = False
    pii_scrubbed: int = 0
    reason: str | None = None


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
    redaction: RedactionOut = RedactionOut()


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


class ApprovalRecord(BaseModel):
    decided_at: str
    approver_id: str
    approver_name: str
    approver_roles: list[str]
    decision: Literal["approve", "modify", "reject"]
    reason: str
    changes: dict[str, Any]
    resulting_status: str


class Me(BaseModel):
    user_id: str
    name: str
    roles: list[str]
    can_approve: bool
    permissions: list[str]


# ---- metrics (Phase 5) -------------------------------------------------------------------------------
MetricName = Literal[
    "runs", "cost_usd", "tokens", "duration_sec", "success_rate", "escalation_rate", "groundedness",
    "citation_validity", "task_adherence", "contradiction_free", "tool_call_accuracy",
    "constraint_satisfaction", "completeness", "quality",
]


class CostByAgent(BaseModel):
    agent: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


class CostByModel(BaseModel):
    model: str
    tier: str
    calls: int
    input_tokens: int
    output_tokens: int
    cost_usd: float


class IntentMetrics(BaseModel):
    task_adherence: float | None
    constraint_satisfaction: float | None
    completeness: float | None


class ToolMetrics(BaseModel):
    tool_calls: int
    tool_call_success_rate: float | None
    tool_call_accuracy: float | None
    invalid_schema_rate: float | None
    llm_repair_rate: float | None
    llm_fallback_rate: float | None
    schema_escalations: int


class SafetyMetrics(BaseModel):
    groundedness: float | None
    contradiction_free: float | None
    escalation_rate: float | None
    unauthorized_action_rate: float | None
    runs_halted: int


class BusinessMetrics(BaseModel):
    decided: int
    approval_rate: float | None
    modification_rate: float | None
    rejection_rate: float | None
    awaiting_approval: int
    median_decision_seconds: float | None


class EconomicsMetrics(BaseModel):
    total_cost_usd: float
    avg_cost_usd: float | None
    successful_runs: int
    success_rate: float | None
    cost_per_successful_task: float | None
    avg_tokens: float | None
    p50_duration_sec: float | None
    p95_duration_sec: float | None
    cost_by_agent: list[CostByAgent]
    cost_by_model: list[CostByModel]


class QualityFlag(BaseModel):
    metric: str
    value: float
    threshold: float
    message: str


class MetricsSummary(BaseModel):
    runs: int
    by_status: dict[str, int]
    intent: IntentMetrics
    tool: ToolMetrics
    safety: SafetyMetrics
    business: BusinessMetrics
    economics: EconomicsMetrics
    flags: list[QualityFlag]
    policy_version: str
    thresholds: dict[str, float]
    since: str | None = None
    until: str | None = None


class TimeseriesPoint(BaseModel):
    t: str
    value: float | None
    n: int


class TimeseriesOut(BaseModel):
    metric: MetricName
    bucket: Literal["hour", "day"]
    points: list[TimeseriesPoint]


class BudgetLine(BaseModel):
    used: float
    limit: float


class BudgetUse(BaseModel):
    tokens: BudgetLine
    cost_usd: BudgetLine
    tool_calls: BudgetLine
    duration_sec: BudgetLine


class CostBreakdownOut(BaseModel):
    workflow_id: str
    total_cost_usd: float
    input_tokens: int
    output_tokens: int
    successful: bool
    cost_per_successful_task: float | None
    by_agent: list[CostByAgent]
    by_model: list[CostByModel]
    budget: BudgetUse


# ---- governance (Phase 6): read-only views ---------------------------------------------------------------------
class AgentPolicy(BaseModel):
    name: str
    allowed_tools: list[str]
    blocked_tools: list[str]
    requires_approval: list[str]
    allowed_tables: list[str]


class PolicyOut(BaseModel):
    version: str
    sha256: str
    agents: list[AgentPolicy]
    thresholds: dict[str, float]
    risk_tiers: dict[str, list[str]]
    data_classification: dict[str, list[str]]  # classification -> providers allowed to see it
    pii: dict[str, str]
    rbac: dict[str, list[str]]
    limits: dict[str, Any]
    degradation: dict[str, Any]
    timeouts_sec: dict[str, Any]


class PolicyVersionOut(BaseModel):
    version: str
    sha256: str
    loaded_at: str
    drift: bool  # the file text changed without its version being bumped


class PolicyContentOut(PolicyVersionOut):
    content: str


class ToolTimeoutsOut(BaseModel):
    connect_ms: int
    read_ms: int
    total_ms: int


class ToolOut(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    risk_level: str
    timeouts: ToolTimeoutsOut
    max_retries: int
    cost_usd: float
    audit: bool
    requires_approval: bool
    allowed_agents: list[str]
    blocked_agents: list[str]


class BreakerOut(BaseModel):
    provider: str
    state: Literal["closed", "open", "half_open"]
    consecutive_failures: int
    failure_threshold: int
    trips: int
    retry_in_sec: float | None
    last_error: str | None
    last_error_at: str | None


class LimiterOut(BaseModel):
    requests_available: float
    requests_capacity: float
    tokens_available: float
    tokens_capacity: float
    in_flight: int
    max_concurrent: int
    queued_calls: int
    rejected_calls: int


class ProviderOut(BaseModel):
    name: str
    configured: bool
    primary: bool
    allowed_classifications: list[str]
    breaker: BreakerOut
    limits: LimiterOut | None


class ModelRouteOut(BaseModel):
    tier: str
    deployment: str
    price_per_1k_usd: float


class FallbackOut(BaseModel):
    ts: str
    task: str
    agent: str
    from_provider: str
    to_provider: str | None
    reason: str
    data_classification: str


class SchedulerOut(BaseModel):
    running: int
    queued: int
    max_concurrent: int
    max_queued: int


class ProvidersOut(BaseModel):
    providers: list[ProviderOut]
    routing: list[ModelRouteOut]
    fallbacks: list[FallbackOut]
    scheduler: SchedulerOut


class BudgetDefaults(BaseModel):
    max_tokens: int
    max_cost_usd: float
    max_duration_sec: int
    max_tool_calls: int


class RunBudgetUse(BaseModel):
    workflow_id: str
    status: str
    tokens: int
    cost_usd: float
    tool_calls: int
    duration_sec: float
    utilization: float  # the tightest budget, as a share of its limit
    tightest: Literal["tokens", "cost_usd", "tool_calls", "duration_sec"]
    near_limit: bool


class BudgetsOut(BaseModel):
    defaults: BudgetDefaults
    running: list[RunBudgetUse]
    recent: list[RunBudgetUse]
    near_limit_count: int


class DegradationActions(BaseModel):
    tier_boost: int
    retrieval_k_multiplier: int
    require_review: bool


class DegradationStateOut(BaseModel):
    level: Literal["normal", "cautious", "restricted"]
    since: str
    reasons: list[str]
    metrics: dict[str, float]
    runs_considered: int
    actions: DegradationActions


class DegradationEventOut(BaseModel):
    ts: str
    from_level: str
    to_level: str
    reasons: list[str]
    metrics: dict[str, float]
    runs_considered: int


class DegradationOut(BaseModel):
    state: DegradationStateOut
    events: list[DegradationEventOut]
