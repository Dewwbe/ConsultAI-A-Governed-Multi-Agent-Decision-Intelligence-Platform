from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request

from app.schemas.api import (
    ApprovalRequest,
    EngagementDetail,
    EngagementList,
    EngagementRequest,
    EvidenceOut,
    Health,
    ReplayOut,
    Status,
    TablesOut,
    TraceOut,
)

router = APIRouter()

_NOT_FOUND = {404: {"description": "engagement not found"}}


def _svc(request: Request):
    return request.app.state.service


@router.post("/engagements", response_model=EngagementDetail, operation_id="createEngagement")
def create_engagement(body: EngagementRequest, request: Request):
    return _svc(request).start(**body.model_dump())


@router.get("/engagements", response_model=EngagementList, operation_id="listEngagements")
def list_engagements(request: Request, status: Status | None = None,
                     limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    return _svc(request).list(status=status, limit=limit, offset=offset)


@router.get("/engagements/{workflow_id}", response_model=EngagementDetail, responses=_NOT_FOUND,
            operation_id="getEngagement")
def get_engagement(workflow_id: str, request: Request):
    try:
        return _svc(request).get(workflow_id)
    except KeyError:
        raise HTTPException(404, "engagement not found")


@router.post("/engagements/{workflow_id}/approval", response_model=EngagementDetail,
             responses={**_NOT_FOUND, 409: {"description": "engagement is not awaiting approval"}},
             operation_id="submitApproval")
def approve(workflow_id: str, body: ApprovalRequest, request: Request):
    svc = _svc(request)
    try:
        current = svc.get(workflow_id)
    except KeyError:
        raise HTTPException(404, "engagement not found")
    if current["status"] != "awaiting_approval":
        raise HTTPException(409, f"engagement is {current['status']}, not awaiting approval")
    return svc.approve(workflow_id, body.decision, body.changes, body.reason)


@router.get("/engagements/{workflow_id}/evidence", response_model=EvidenceOut, responses=_NOT_FOUND,
            operation_id="getEvidence")
def evidence(workflow_id: str, request: Request):
    try:
        return _svc(request).evidence(workflow_id)
    except KeyError:
        raise HTTPException(404, "engagement not found")


@router.get("/engagements/{workflow_id}/tables", response_model=TablesOut, responses=_NOT_FOUND,
            operation_id="getTables")
def tables(workflow_id: str, request: Request):
    try:
        return _svc(request).tables(workflow_id)
    except KeyError:
        raise HTTPException(404, "engagement not found")


@router.post("/engagements/{workflow_id}/retrievals/{retrieval_id}/replay", response_model=ReplayOut,
             responses={404: {"description": "engagement or retrieval not found"}},
             operation_id="replayRetrieval")
def replay_retrieval(workflow_id: str, retrieval_id: str, request: Request):
    try:
        return _svc(request).replay_retrieval(workflow_id, retrieval_id)
    except KeyError:
        raise HTTPException(404, "engagement or retrieval not found")


@router.get("/control-center/{workflow_id}/trace", response_model=TraceOut, responses=_NOT_FOUND,
            operation_id="getTrace")
def trace(workflow_id: str, request: Request):
    try:
        return _svc(request).trace(workflow_id)
    except KeyError:
        raise HTTPException(404, "engagement not found")


@router.get("/health", response_model=Health, operation_id="getHealth")
def health(request: Request):
    return {"status": "ok", "llm_provider": _svc(request).settings.llm_provider}
