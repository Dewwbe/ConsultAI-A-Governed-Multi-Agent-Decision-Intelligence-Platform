import datetime as dt
import json
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

from app.config import Settings
from app.control_plane.reliability import PermanentError
from app.main import app
from app.persistence.db import Database
from app.security.auth import (
    AuthError,
    DevAuthenticator,
    EntraAuthenticator,
    Principal,
    build_authenticator,
)
from app.workflow.graph import RUNTIMES
from app.workflow.service import Conflict, EngagementService, Forbidden, Invalid

REQ = {"business_problem": "Should we expand into the UAE market?", "industry": "Retail",
       "objectives": ["Increase revenue"], "constraints": ["Budget under $10M"]}
PARTNER = Principal("oid-partner", "Pat Partner", ("Partner",))
ANALYST = Principal("oid-analyst", "Ann Analyst", ("Analyst",))
H_PARTNER = {"X-Dev-User": "pat", "X-Dev-Roles": "Partner"}
H_ANALYST = {"X-Dev-User": "ann", "X-Dev-Roles": "Analyst"}


def file_settings(tmp_path):
    return Settings(database_url=f"sqlite:///{(tmp_path / 'c.db').as_posix()}", llm_provider="stub")


# ---- persistence: a paused run survives a restart --------------------------------------------
def test_paused_run_survives_restart_and_resumes_after_authorised_approval(tmp_path):
    settings = file_settings(tmp_path)
    first = EngagementService(settings)
    out = first.start(**REQ)
    wid = out["workflow_id"]
    assert out["status"] == "awaiting_approval"
    cost, spans = out["budget"]["cost_usd"], first.trace(wid)["span_count"]

    RUNTIMES.pop(wid)                       # the old process is gone: nothing in memory
    second = EngagementService(settings)    # a new process, same database files
    again = second.get(wid)
    assert again["status"] == "awaiting_approval" and again["pending_node"] == ["approval"]
    assert again["budget"]["cost_usd"] == cost and second.trace(wid)["span_count"] == spans
    assert again["state"]["recommendation"]["id"] and len(again["guardian_decisions"]) >= 1
    assert second.list()["total"] == 1 and second.evidence(wid)["retrievals"]

    with pytest.raises(Forbidden):          # unauthorised attempts are rejected...
        second.approve(wid, "approve", approver=ANALYST)
    assert second.get(wid)["status"] == "awaiting_approval"
    done = second.approve(wid, "approve", reason="ok", approver=PARTNER)   # ...and the partner resumes it
    assert done["status"] == "completed" and "Engagement Report" in done["state"]["report"]["markdown"]
    assert done["budget"]["cost_usd"] >= cost


def test_decisions_and_audit_survive_restart_too(tmp_path):
    settings = file_settings(tmp_path)
    svc = EngagementService(settings)
    wid = svc.start(**REQ)["workflow_id"]
    svc.approve(wid, "reject", reason="too risky", approver=PARTNER)
    RUNTIMES.pop(wid)
    later = EngagementService(settings)
    hist = later.approvals(wid)
    assert [(h["decision"], h["approver_id"], h["reason"]) for h in hist] == [
        ("reject", "oid-partner", "too risky")]
    assert later.get(wid)["status"] == "rejected"


def test_runs_interrupted_by_a_crash_are_marked_failed(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'x.db').as_posix()}")
    db.add_engagement("wf_dead", user_id="u", business_problem="p", industry="", data_classification="public")
    assert db.mark_interrupted() == 1
    row = db.get_engagement("wf_dead")
    assert row["status"] == "failed" and "restart" in row["error"]


# ---- approval authorisation, validation, audit ---------------------------------------------------
def test_unauthorised_and_invalid_approvals_are_rejected_and_audited():
    svc = EngagementService()
    wid = svc.start(**REQ)["workflow_id"]
    with pytest.raises(Forbidden):
        svc.approve(wid, "approve", approver=ANALYST)
    for bad, kwargs in [("modify w/o reason", dict(decision="modify", changes={"rationale": "x"}, reason="")),
                        ("reject w/o reason", dict(decision="reject", reason=" ")),
                        ("modify w/o changes", dict(decision="modify", reason="r")),
                        ("number edit", dict(decision="modify", changes={"cost_usd": 1}, reason="r")),
                        ("wrong type", dict(decision="modify", changes={"assumptions": "x"}, reason="r")),
                        ("changes on approve", dict(decision="approve", changes={"rationale": "x"})),
                        ("unknown decision", dict(decision="yolo"))]:
        with pytest.raises(Invalid):
            svc.approve(wid, approver=PARTNER, **kwargs)
        assert svc.get(wid)["status"] == "awaiting_approval", bad
    svc.approve(wid, "approve", approver=PARTNER)
    with pytest.raises(Conflict):
        svc.approve(wid, "approve", approver=PARTNER)
    with pytest.raises(KeyError):
        svc.approve("wf_nope", "approve", approver=PARTNER)
    audit = svc.db.audit_for(wid)
    outcomes = [(a["actor_id"], a["outcome"]) for a in audit if a["action"] == "approval"]
    assert outcomes[0] == ("oid-analyst", "denied") and outcomes[-2:] == [
        ("oid-partner", "allowed"), ("oid-partner", "conflict")] or ("oid-partner", "allowed") in outcomes
    assert sum(1 for _, o in outcomes if o == "invalid") == 7
    assert svc.db.audit_for(wid)[0]["action"] == "create_engagement"


def test_modify_applies_only_whitelisted_fields_and_is_recorded():
    svc = EngagementService()
    wid = svc.start(**REQ)["workflow_id"]
    out = svc.approve(wid, "modify", {"rationale": "Be careful", "assumptions": ["A1"]},
                      "tighten wording", approver=PARTNER)
    rec = out["state"]["recommendation"]
    assert rec["rationale"] == "Be careful" and rec["assumptions"] == ["A1"] and out["status"] == "completed"
    h = svc.approvals(wid)[0]
    assert h["decision"] == "modify" and h["changes"]["rationale"] == "Be careful"
    assert h["approver_name"] == "Pat Partner" and h["resulting_status"] == "completed"


def test_human_decisions_are_recorded_as_an_evaluation_dataset():
    svc = EngagementService()
    wid = svc.start(**REQ)["workflow_id"]
    svc.approve(wid, "reject", reason="assumptions too optimistic", approver=PARTNER)
    rec = svc.db.decision_records()[-1]
    assert rec["workflow_id"] == wid and rec["decision"] == "reject" and rec["approver_id"] == "oid-partner"
    assert rec["recommendation"]["id"] and rec["evaluation_scores"]["groundedness"] and rec["guardian"]["action"]


# ---- authentication -------------------------------------------------------------------------------
TENANT, CLIENT = "tenant-1", "client-1"
_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_PRIV = _KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                           serialization.NoEncryption())


def token(**over):
    now = dt.datetime.now(dt.UTC)
    claims = {"iss": f"https://login.microsoftonline.com/{TENANT}/v2.0", "aud": CLIENT, "tid": TENANT,
              "exp": now + dt.timedelta(minutes=5), "iat": now, "oid": "oid-1", "name": "Pat",
              "roles": ["Partner"], **over}
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, over.pop("_key", _PRIV), algorithm="RS256", headers={"kid": "k1"})


def entra():
    jwks = SimpleNamespace(get_signing_key_from_jwt=lambda t: SimpleNamespace(key=_KEY.public_key()))
    return EntraAuthenticator(TENANT, [CLIENT], jwks_client=jwks)


def bearer(t):
    return {"authorization": f"Bearer {t}"}


def test_entra_accepts_a_valid_token_and_reads_roles():
    p = entra().authenticate(bearer(token()))
    assert (p.user_id, p.name, p.roles) == ("oid-1", "Pat", ("Partner",)) and p.has_role("Partner")
    v1 = token(iss=f"https://sts.windows.net/{TENANT}/")          # v1-format issuer is accepted too
    assert entra().authenticate(bearer(v1)).user_id == "oid-1"


@pytest.mark.parametrize("headers", [
    {}, {"authorization": "Basic abc"}, {"authorization": "Bearer "}, {"authorization": "Bearer junk"},
])
def test_entra_rejects_missing_or_malformed_credentials(headers):
    with pytest.raises(AuthError):
        entra().authenticate(headers)


@pytest.mark.parametrize("over", [
    {"exp": dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)},      # expired
    {"aud": "someone-else"},                                       # wrong audience
    {"iss": "https://evil.example/v2.0"},                          # wrong issuer
    {"tid": "other-tenant"},                                       # wrong tenant
    {"oid": None, "sub": None},                                    # no subject
])
def test_entra_rejects_bad_claims(over):
    with pytest.raises(AuthError):
        entra().authenticate(bearer(token(**over)))


def test_entra_rejects_tokens_signed_by_another_key():
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = other.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                              serialization.NoEncryption())
    forged = jwt.encode({"iss": f"https://login.microsoftonline.com/{TENANT}/v2.0", "aud": CLIENT,
                         "exp": dt.datetime.now(dt.UTC) + dt.timedelta(minutes=5), "oid": "x",
                         "roles": ["Partner"]}, pem, algorithm="RS256")
    with pytest.raises(AuthError):
        entra().authenticate(bearer(forged))


def test_dev_auth_is_refused_outside_dev_environment():
    assert isinstance(build_authenticator(Settings(auth_mode="dev", environment="dev")), DevAuthenticator)
    with pytest.raises(RuntimeError, match="ENVIRONMENT=dev"):
        build_authenticator(Settings(auth_mode="dev", environment="production"))
    with pytest.raises(RuntimeError, match="ENTRA_TENANT_ID"):
        build_authenticator(Settings(auth_mode="entra", environment="production"))
    assert isinstance(build_authenticator(Settings(auth_mode="entra", entra_tenant_id="t", entra_client_id="c",
                                                   environment="production")), EntraAuthenticator)


# ---- HTTP: identity, roles, history, guardian log ---------------------------------------------------
def test_http_roles_and_history():
    c = TestClient(app)
    assert c.get("/me", headers=H_PARTNER).json() == {"user_id": "pat", "name": "pat", "roles": ["Partner"],
                                                       "can_approve": True}
    assert c.get("/me", headers=H_ANALYST).json()["can_approve"] is False
    wid = c.post("/engagements", json=REQ, headers=H_ANALYST).json()["workflow_id"]
    denied = c.post(f"/engagements/{wid}/approval", json={"decision": "approve"}, headers=H_ANALYST)
    assert denied.status_code == 403 and "Partner" in denied.json()["detail"]
    assert c.post(f"/engagements/{wid}/approval", json={"decision": "reject"}, headers=H_PARTNER).status_code == 422
    ok = c.post(f"/engagements/{wid}/approval", json={"decision": "reject", "reason": "no"}, headers=H_PARTNER)
    assert ok.status_code == 200 and ok.json()["status"] == "rejected"
    assert c.post(f"/engagements/{wid}/approval", json={"decision": "approve"}, headers=H_PARTNER).status_code == 409
    hist = c.get(f"/engagements/{wid}/approvals", headers=H_PARTNER).json()
    assert [(h["approver_id"], h["decision"]) for h in hist] == [("pat", "reject")]
    log = c.get(f"/engagements/{wid}/guardian").json()
    assert log and {"action", "risk_level", "reasons"} <= set(log[-1]) and log[-1]["action"] == "ESCALATE"
    assert c.get("/engagements/nope/approvals").status_code == 404
    assert c.get("/engagements/nope/guardian").status_code == 404


def test_entra_mode_requires_a_token_on_every_endpoint_but_health():
    svc = EngagementService()
    app2 = app.__class__()  # isolated app: do not disturb the shared one
    from app.api.routes import router
    app2.include_router(router)
    app2.state.service, app2.state.authenticator = svc, entra()
    c = TestClient(app2)
    assert c.get("/health").status_code == 200
    r = c.get("/engagements")
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
    assert c.post("/engagements", json=REQ).status_code == 401
    good = {"Authorization": f"Bearer {token()}"}
    wid = c.post("/engagements", json=REQ, headers=good).json()["workflow_id"]
    assert c.post(f"/engagements/{wid}/approval", json={"decision": "approve"}, headers=good).status_code == 200
    no_role = {"Authorization": f"Bearer {token(roles=[])}"}
    wid2 = c.post("/engagements", json=REQ, headers=good).json()["workflow_id"]
    assert c.post(f"/engagements/{wid2}/approval", json={"decision": "approve"}, headers=no_role).status_code == 403
    expired = {"Authorization": "Bearer " + token(exp=dt.datetime.now(dt.UTC) - dt.timedelta(hours=1))}
    assert c.get("/engagements", headers=expired).status_code == 401


# ---- live events ---------------------------------------------------------------------------------------
def parse_sse(text):
    events = []
    for block in text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line and not line.startswith(":"))
        if "event" in fields:
            events.append((int(fields["id"]), fields["event"], json.loads(fields["data"])))
    return events


def test_event_stream_reports_steps_then_approval_requested():
    c = TestClient(app)
    wid = c.post("/engagements", json=REQ).json()["workflow_id"]
    with c.stream("GET", f"/engagements/{wid}/events") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        events = parse_sse("".join(r.iter_text()))
    names = [(e[1], e[2].get("name")) for e in events]
    assert names[0][0] == "run_started" and events[-1][1] == "approval_requested"
    started = [n for t, n in names if t == "step_started"]
    for step in ["discovery_agent", "research_agent", "data_agent", "financial_agent", "risk_agent",
                 "solution_agent", "evaluator", "guardian"]:
        assert step in started, step
    assert started.index("discovery_agent") < started.index("financial_agent") < started.index("guardian")
    assert [e[0] for e in events] == sorted(e[0] for e in events)
    assert events[-1][2]["risk_level"] == "high"
    # resume after approval: only the later events arrive
    last = events[-1][0]
    c.post(f"/engagements/{wid}/approval", json={"decision": "approve"}, headers=H_PARTNER)
    with c.stream("GET", f"/engagements/{wid}/events", params={"after": last}) as r:
        later = parse_sse("".join(r.iter_text()))
    assert [e[1] for e in later][:1] == ["approval_decided"] and later[-1][1] == "run_completed"
    assert c.get("/engagements/nope/events").status_code == 404


def test_background_run_returns_running_then_streams_to_completion():
    c = TestClient(app)
    first = c.post("/engagements", params={"wait": "false"}, json=REQ)
    wid = first.json()["workflow_id"]
    assert first.status_code == 200 and first.json()["status"] in {"running", "awaiting_approval"}
    with c.stream("GET", f"/engagements/{wid}/events") as r:
        events = parse_sse("".join(r.iter_text()))
    assert events[-1][1] == "approval_requested"
    assert c.get(f"/engagements/{wid}").json()["status"] == "awaiting_approval"
    assert c.get("/engagements", params={"status": "running", "limit": 200}).status_code == 200


def test_a_crashing_run_becomes_failed_not_a_500():
    svc = EngagementService()

    class Boom:
        name = "azure_openai"

        def complete_json(self, **kw):
            raise PermanentError("provider rejected the request")

    from app.control_plane import llm
    svc._provider = lambda: Boom()
    out = svc.start(**REQ)
    assert out["status"] == "escalated"          # a classified provider failure escalates to a human

    def explode(*a, **k):
        raise ValueError("graph exploded")
    svc.graph.invoke = explode
    bad = svc.start(**REQ)
    assert bad["status"] == "failed" and "graph exploded" in bad["error"]
    assert svc.events_after(bad["workflow_id"])[-1]["type"] == "run_failed"
    assert llm  # imported for clarity
