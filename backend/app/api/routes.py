from __future__ import annotations

import json
import time
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.control_plane.limits import QueueFull
from app.schemas.api import (
    ApprovalRecord,
    ApprovalRequest,
    BudgetsOut,
    CostBreakdownOut,
    DegradationOut,
    EngagementDetail,
    EngagementList,
    EngagementRequest,
    EvidenceOut,
    Health,
    Me,
    MetricName,
    MetricsSummary,
    PolicyContentOut,
    PolicyOut,
    PolicyVersionOut,
    ProvidersOut,
    ReplayOut,
    Status,
    TablesOut,
    TimeseriesOut,
    ToolOut,
    TraceOut,
)
from app.schemas.models import GuardianDecision
from app.security.auth import AuthError, Principal
from app.workflow import governance
from app.workflow.service import Conflict, Forbidden, Invalid

router = APIRouter()

_NOT_FOUND = {404: {"description": "engagement not found"}}
_AUTH = {401: {"description": "missing or invalid credentials"}}
TERMINAL_EVENTS = {"approval_requested", "run_completed", "run_escalated", "run_failed"}
STREAM_MAX_SEC = 600


def _svc(request: Request):
    return request.app.state.service


def principal(request: Request) -> Principal:
    try:
        return request.app.state.authenticator.authenticate(request.headers)
    except AuthError as exc:
        raise HTTPException(401, str(exc), headers={"WWW-Authenticate": "Bearer"}) from exc


def require(permission: str):
    """A dependency that signs the caller in and then checks one RBAC permission (default deny)."""
    def check(request: Request, p: Principal = Depends(principal)) -> Principal:
        rbac = _svc(request).rbac
        if not rbac.allows(p, permission):
            raise HTTPException(403, f"'{permission}' needs {rbac.describe(permission)}")
        return p
    return check


@router.get("/me", response_model=Me, responses=_AUTH, operation_id="getMe")
def me(request: Request, p: Principal = Depends(principal)):
    return {"user_id": p.user_id, "name": p.name, "roles": list(p.roles),
            "can_approve": _svc(request).rbac.allows(p, "engagement:approve"),
            "permissions": _svc(request).rbac.permissions_of(p)}


@router.post("/engagements", response_model=EngagementDetail,
             responses={**_AUTH, 429: {"description": "too many engagements in progress; see Retry-After"}},
             operation_id="createEngagement")
def create_engagement(body: EngagementRequest, request: Request, wait: bool = True,
                      p: Principal = Depends(principal)):
    """wait=false returns immediately with status `running`; follow progress via /events."""
    try:
        return _svc(request).start(**body.model_dump(), user_id=p.user_id, wait=wait)
    except QueueFull as exc:
        raise HTTPException(429, str(exc), headers={"Retry-After": str(exc.retry_after_sec)}) from exc


@router.get("/engagements", response_model=EngagementList, responses=_AUTH, operation_id="listEngagements")
def list_engagements(request: Request, status: Status | None = None,
                     limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
                     p: Principal = Depends(principal)):
    return _svc(request).list(status=status, limit=limit, offset=offset)


@router.get("/engagements/{workflow_id}", response_model=EngagementDetail,
            responses={**_NOT_FOUND, **_AUTH}, operation_id="getEngagement")
def get_engagement(workflow_id: str, request: Request, p: Principal = Depends(principal)):
    try:
        return _svc(request).get(workflow_id)
    except KeyError as exc:
        raise HTTPException(404, "engagement not found") from exc


@router.post("/engagements/{workflow_id}/approval", response_model=EngagementDetail,
             responses={**_NOT_FOUND, **_AUTH, 403: {"description": "caller lacks the approver role"},
                        409: {"description": "engagement is not awaiting approval"},
                        422: {"description": "invalid decision, reason or changes"}},
             operation_id="submitApproval")
def approve(workflow_id: str, body: ApprovalRequest, request: Request, p: Principal = Depends(principal)):
    try:
        return _svc(request).approve(workflow_id, body.decision, body.changes, body.reason, approver=p)
    except KeyError as exc:
        raise HTTPException(404, "engagement not found") from exc
    except Forbidden as exc:
        raise HTTPException(403, str(exc)) from exc
    except Conflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except Invalid as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/engagements/{workflow_id}/approvals", response_model=list[ApprovalRecord],
            responses={**_NOT_FOUND, **_AUTH}, operation_id="listApprovals")
def approvals(workflow_id: str, request: Request, p: Principal = Depends(principal)):
    try:
        return _svc(request).approvals(workflow_id)
    except KeyError as exc:
        raise HTTPException(404, "engagement not found") from exc


@router.get("/engagements/{workflow_id}/guardian", response_model=list[GuardianDecision],
            responses={**_NOT_FOUND, **_AUTH}, operation_id="getGuardianLog")
def guardian_log(workflow_id: str, request: Request, p: Principal = Depends(principal)):
    try:
        return _svc(request).guardian(workflow_id)
    except KeyError as exc:
        raise HTTPException(404, "engagement not found") from exc


@router.get("/engagements/{workflow_id}/events", operation_id="streamEvents",
            responses={**_NOT_FOUND, **_AUTH, 200: {"description": "Server-Sent Events",
                                                    "content": {"text/event-stream": {}}}})
def stream_events(workflow_id: str, request: Request, after: int = Query(0, ge=0),
                  last_event_id: int | None = Header(None, alias="Last-Event-ID"),
                  p: Principal = Depends(principal)):
    """Live progress as Server-Sent Events: run_started, step_started/step_finished (agent,
    evaluator, guardian), then one of approval_requested | run_completed | run_escalated |
    run_failed, after which the stream closes. Resume with `?after=<id>` or Last-Event-ID, e.g.
    to pick up approval_decided and the final events after submitting an approval."""
    svc = _svc(request)
    try:
        svc.events_after(workflow_id, 0)
    except KeyError as exc:
        raise HTTPException(404, "engagement not found") from exc
    cursor = max(after, last_event_id or 0)

    def stream():
        last, started, beat = cursor, time.monotonic(), time.monotonic()
        while time.monotonic() - started < STREAM_MAX_SEC:
            evs = svc.events_after(workflow_id, last)
            for e in evs:
                last = e["id"]
                yield f"id: {e['id']}\nevent: {e['type']}\ndata: {json.dumps({'ts': e['ts'], **e['data']})}\n\n"
            if any(e["type"] in TERMINAL_EVENTS for e in evs):
                return
            if not evs and svc.db.get_engagement(workflow_id)["status"] != "running":
                return  # caught up on a paused or finished run
            if time.monotonic() - beat > 15:
                beat = time.monotonic()
                yield ": keepalive\n\n"
            time.sleep(0.2)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/engagements/{workflow_id}/evidence", response_model=EvidenceOut,
            responses={**_NOT_FOUND, **_AUTH}, operation_id="getEvidence")
def evidence(workflow_id: str, request: Request, p: Principal = Depends(principal)):
    try:
        return _svc(request).evidence(workflow_id)
    except KeyError as exc:
        raise HTTPException(404, "engagement not found") from exc


@router.get("/engagements/{workflow_id}/tables", response_model=TablesOut,
            responses={**_NOT_FOUND, **_AUTH}, operation_id="getTables")
def tables(workflow_id: str, request: Request, p: Principal = Depends(principal)):
    try:
        return _svc(request).tables(workflow_id)
    except KeyError as exc:
        raise HTTPException(404, "engagement not found") from exc


@router.post("/engagements/{workflow_id}/retrievals/{retrieval_id}/replay", response_model=ReplayOut,
             responses={404: {"description": "engagement or retrieval not found"}, **_AUTH},
             operation_id="replayRetrieval")
def replay_retrieval(workflow_id: str, retrieval_id: str, request: Request, p: Principal = Depends(principal)):
    try:
        return _svc(request).replay_retrieval(workflow_id, retrieval_id)
    except KeyError as exc:
        raise HTTPException(404, "engagement or retrieval not found") from exc


@router.get("/control-center/{workflow_id}/trace", response_model=TraceOut,
            responses={**_NOT_FOUND, **_AUTH}, operation_id="getTrace")
def trace(workflow_id: str, request: Request, p: Principal = Depends(principal)):
    try:
        return _svc(request).trace_for(workflow_id, p)
    except KeyError as exc:
        raise HTTPException(404, "engagement not found") from exc


@router.get("/metrics/summary", response_model=MetricsSummary, responses=_AUTH, operation_id="getMetricsSummary")
def metrics_summary(request: Request, since: str | None = None, until: str | None = None,
                    status: Status | None = None, p: Principal = Depends(principal)):
    """Intent, tool, safety, business and economics metrics over the runs in the window, plus quality flags."""
    return _svc(request).metrics_summary(since=since, until=until, status=status)


@router.get("/metrics/timeseries", response_model=TimeseriesOut, responses=_AUTH, operation_id="getMetricsTimeseries")
def metrics_timeseries(request: Request, metric: MetricName, bucket: Literal["hour", "day"] = "day",
                       since: str | None = None, until: str | None = None, status: Status | None = None,
                       p: Principal = Depends(principal)):
    return _svc(request).metrics_timeseries(metric, bucket, since=since, until=until, status=status)


@router.get("/engagements/{workflow_id}/cost", response_model=CostBreakdownOut,
            responses={**_NOT_FOUND, **_AUTH}, operation_id="getCostBreakdown")
def cost_breakdown(workflow_id: str, request: Request, p: Principal = Depends(principal)):
    try:
        return _svc(request).cost_breakdown(workflow_id)
    except KeyError as exc:
        raise HTTPException(404, "engagement not found") from exc


_governance = require("governance:view")
_GOV = {**_AUTH, 403: {"description": "needs the governance:view permission"}}


@router.get("/governance/policy", response_model=PolicyOut, responses=_GOV, operation_id="getPolicy")
def get_policy(request: Request, p: Principal = Depends(_governance)):
    """The policy in force: tool permissions per agent, thresholds, provider rules, PII, limits and RBAC."""
    return governance.policy_view(_svc(request))


@router.get("/governance/policy/versions", response_model=list[PolicyVersionOut], responses=_GOV,
            operation_id="listPolicyVersions")
def list_policy_versions(request: Request, p: Principal = Depends(_governance)):
    return _svc(request).db.policy_history()


@router.get("/governance/policy/versions/{key}", response_model=PolicyContentOut,
            responses={**_GOV, 404: {"description": "no such policy version"}}, operation_id="getPolicyVersion")
def get_policy_version(key: str, request: Request, p: Principal = Depends(_governance)):
    """The exact text of a past policy (by version or content hash), for comparing what changed."""
    found = _svc(request).db.policy_content(key)
    if found is None:
        raise HTTPException(404, "no such policy version")
    return {**found, "drift": False}


@router.get("/governance/tools", response_model=list[ToolOut], responses=_GOV, operation_id="listTools")
def list_tools(request: Request, p: Principal = Depends(_governance)):
    return governance.tools_view(_svc(request))


@router.get("/governance/providers", response_model=ProvidersOut, responses=_GOV, operation_id="getProviders")
def get_providers(request: Request, p: Principal = Depends(_governance)):
    """Provider health: circuit-breaker state, rate-limit use, which data each may see, and recent fallbacks."""
    return governance.providers_view(_svc(request))


@router.get("/governance/budgets", response_model=BudgetsOut, responses=_GOV, operation_id="getBudgets")
def get_budgets(request: Request, p: Principal = Depends(_governance)):
    return governance.budgets_view(_svc(request))


@router.get("/governance/degradation", response_model=DegradationOut, responses=_GOV, operation_id="getDegradation")
def get_degradation(request: Request, p: Principal = Depends(_governance)):
    """How cautious the system currently is, and the history of why it changed."""
    return governance.degradation_view(_svc(request))


@router.get("/health", response_model=Health, operation_id="getHealth")
def health(request: Request):
    return {"status": "ok", "llm_provider": _svc(request).settings.llm_provider}
