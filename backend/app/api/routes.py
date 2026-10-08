from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.schemas.api import (
    ApprovalRecord,
    ApprovalRequest,
    EngagementDetail,
    EngagementList,
    EngagementRequest,
    EvidenceOut,
    Health,
    Me,
    ReplayOut,
    Status,
    TablesOut,
    TraceOut,
)
from app.schemas.models import GuardianDecision
from app.security.auth import AuthError, Principal
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


@router.get("/me", response_model=Me, responses=_AUTH, operation_id="getMe")
def me(request: Request, p: Principal = Depends(principal)):
    return {"user_id": p.user_id, "name": p.name, "roles": list(p.roles),
            "can_approve": p.has_role(_svc(request).settings.approver_role)}


@router.post("/engagements", response_model=EngagementDetail, responses=_AUTH, operation_id="createEngagement")
def create_engagement(body: EngagementRequest, request: Request, wait: bool = True,
                      p: Principal = Depends(principal)):
    """wait=false returns immediately with status `running`; follow progress via /events."""
    return _svc(request).start(**body.model_dump(), user_id=p.user_id, wait=wait)


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
        return _svc(request).trace(workflow_id)
    except KeyError as exc:
        raise HTTPException(404, "engagement not found") from exc


@router.get("/health", response_model=Health, operation_id="getHealth")
def health(request: Request):
    return {"status": "ok", "llm_provider": _svc(request).settings.llm_provider}
