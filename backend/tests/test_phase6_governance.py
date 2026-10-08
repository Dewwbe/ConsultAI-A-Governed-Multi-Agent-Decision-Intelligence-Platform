import sqlite3
import threading
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import router
from app.config import Settings, get_settings
from app.control_plane.reliability import PermanentError
from app.persistence.db import Database
from app.security.auth import DevAuthenticator
from app.workflow.service import EngagementService

REQ = {"business_problem": "Should we expand into the UAE market?", "industry": "Retail", "constraints": ["Budget under $10M"]}
ADMIN = {"X-Dev-User": "ada", "X-Dev-Roles": "Admin"}
AUDITOR = {"X-Dev-User": "aud", "X-Dev-Roles": "Auditor"}
PARTNER = {"X-Dev-User": "pat", "X-Dev-Roles": "Partner"}
ANALYST = {"X-Dev-User": "ann", "X-Dev-Roles": "Analyst"}
ENDPOINTS = ["/governance/policy", "/governance/policy/versions", "/governance/tools", "/governance/providers",
             "/governance/budgets", "/governance/degradation"]


def make(settings=None):
    svc = EngagementService(settings or Settings(llm_provider="stub", database_url="sqlite:///:memory:"))
    app = FastAPI()
    app.include_router(router)
    app.state.service, app.state.authenticator = svc, DevAuthenticator()
    return svc, TestClient(app)


# ---- who may look ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("path", ENDPOINTS)
def test_governance_views_are_for_admins_and_auditors_only(path):
    _, c = make()
    for who in (ADMIN, AUDITOR):
        assert c.get(path, headers=who).status_code == 200, (path, who)
    for who in (ANALYST, PARTNER, {"X-Dev-User": "nobody"}):
        r = c.get(path, headers=who)
        assert r.status_code == 403 and "governance:view" in r.json()["detail"], (path, who)


def test_the_views_are_read_only():
    _, c = make()
    for path in ENDPOINTS:
        assert c.post(path, headers=ADMIN, json={}).status_code == 405
        assert c.delete(path, headers=ADMIN).status_code == 405


# ---- policy -------------------------------------------------------------------------------------------------------------------
def test_the_policy_view_shows_what_agents_may_do_and_which_providers_see_which_data():
    svc, c = make()
    p = c.get("/governance/policy", headers=ADMIN).json()
    assert p["version"] == svc.policy.version and len(p["sha256"]) == 64
    research = next(a for a in p["agents"] if a["name"] == "research_agent")
    assert "send_client_email" in research["blocked_tools"] and "search_knowledge_base" in research["allowed_tools"]
    assert next(a for a in p["agents"] if a["name"] == "data_agent")["allowed_tables"]
    assert p["data_classification"]["confidential"] == ["azure_openai"]
    assert set(p["data_classification"]["public"]) >= {"azure_openai", "openai"}
    assert p["thresholds"]["min_groundedness"] == 0.75 and p["pii"]["confidential"] == "redact"
    assert p["rbac"]["engagement:approve"] == ["Partner"] and "providers" in p["limits"] and p["degradation"]["window"] == 10


def policy_variant(tmp_path, *, version=None, extra=""):
    text = Path(get_settings().policy_file).read_text(encoding="utf-8")
    if version:
        text = text.replace(f'version: "{get_settings() and _version(text)}"', f'version: "{version}"', 1)
    path = tmp_path / f"policy-{version or 'same'}{len(extra)}.yaml"
    path.write_text(text + extra, encoding="utf-8")
    return str(path)


def _version(text):
    return next(line.split('"')[1] for line in text.splitlines() if line.startswith("version:"))


def test_every_policy_the_service_has_run_with_is_recorded_and_can_be_read_back(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'g.db').as_posix()}")
    st = lambda **kw: Settings(llm_provider="stub", database_url=f"sqlite:///{(tmp_path / 'g.db').as_posix()}", **kw)
    first = EngagementService(st(), db=db)
    assert [h["version"] for h in db.policy_history()] == [first.policy.version]
    EngagementService(st(), db=db)  # restarting with the same file records nothing new
    assert len(db.policy_history()) == 1

    bumped = policy_variant(tmp_path, version="2099.1.1")
    second = EngagementService(st(policy_file=bumped), db=db)
    versions = db.policy_history()
    assert [h["version"] for h in versions] == ["2099.1.1", first.policy.version] and not any(h["drift"] for h in versions)

    _, c = make()
    c.app.state.service = second
    api = c.get("/governance/policy/versions", headers=ADMIN).json()
    assert [v["version"] for v in api] == ["2099.1.1", first.policy.version]
    one = c.get("/governance/policy/versions/2099.1.1", headers=ADMIN).json()
    assert 'version: "2099.1.1"' in one["content"] and one["sha256"] == second.policy.sha256
    assert c.get(f"/governance/policy/versions/{first.policy.sha256}", headers=ADMIN).json()["version"] == first.policy.version
    assert c.get("/governance/policy/versions/nope", headers=ADMIN).status_code == 404


def test_editing_the_policy_without_bumping_its_version_is_flagged_as_drift(tmp_path):
    db = Database("sqlite:///:memory:")
    original = EngagementService(Settings(llm_provider="stub", database_url="sqlite:///:memory:"), db=db)
    edited = policy_variant(tmp_path, extra="\n# quietly loosened something\n")
    EngagementService(Settings(llm_provider="stub", database_url="sqlite:///:memory:", policy_file=edited), db=db)
    history = db.policy_history()
    assert len(history) == 2 and all(h["version"] == original.policy.version and h["drift"] for h in history)


def test_each_engagement_records_the_policy_version_it_started_under(tmp_path):
    svc, c = make()
    wid = c.post("/engagements", json=REQ, headers=ADMIN).json()["workflow_id"]
    assert c.get(f"/engagements/{wid}", headers=ADMIN).json()["policy_version"] == svc.policy.version
    row = svc.db.get_engagement(wid)
    assert row["policy_version"] == svc.policy.version


def test_a_database_created_before_the_policy_column_existed_is_upgraded_in_place(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE engagements (workflow_id VARCHAR(64) PRIMARY KEY, created_at VARCHAR(40) NOT NULL, "
                "user_id VARCHAR(200) NOT NULL, business_problem TEXT NOT NULL, industry VARCHAR(200) NOT NULL, "
                "data_classification VARCHAR(20) NOT NULL, status VARCHAR(30) NOT NULL, halted_reason TEXT, error TEXT)")
    con.execute("INSERT INTO engagements VALUES ('wf_old','2026-01-01','u','p','','public','completed',NULL,NULL)")
    con.commit()
    con.close()
    db = Database(f"sqlite:///{path.as_posix()}")
    assert db.get_engagement("wf_old")["policy_version"] is None  # old rows simply have none
    db.add_engagement("wf_new", user_id="u", business_problem="p", industry="", data_classification="public", policy_version="9.9")
    assert db.get_engagement("wf_new")["policy_version"] == "9.9"


# ---- tools ---------------------------------------------------------------------------------------------------------------------
def test_the_tool_registry_shows_contracts_limits_and_which_agents_may_use_each_tool():
    _, c = make()
    tools = {t["name"]: t for t in c.get("/governance/tools", headers=ADMIN).json()}
    roi = tools["calculate_roi"]
    assert roi["allowed_agents"] == ["financial_agent"] and roi["risk_level"] == "medium"
    assert roi["input_schema"]["required"] == ["investment", "annual_benefit", "years"]
    assert roi["timeouts"] == {"connect_ms": 1000, "read_ms": 3000, "total_ms": 3000} and roi["max_retries"] == 1
    assert tools["risk_lookup"]["allowed_agents"] == ["risk_agent"]
    assert set(tools) >= {"calculate_npv", "calculate_margin", "derive_annual_benefit", "scenario_analysis"}
    assert all(set(t) >= {"timeouts", "cost_usd", "requires_approval", "blocked_agents"} for t in tools.values())


# ---- providers ------------------------------------------------------------------------------------------------------------------
def test_provider_health_shows_breakers_limits_and_what_data_each_may_see():
    _, c = make()
    out = c.get("/governance/providers", headers=ADMIN).json()
    by = {p["name"]: p for p in out["providers"]}
    azure = by["azure_openai"]
    assert azure["configured"] and azure["primary"] and azure["allowed_classifications"] == ["confidential", "internal", "public"]
    assert azure["breaker"]["state"] == "closed" and azure["limits"]["max_concurrent"] == 8
    assert not by["openai"]["configured"] and by["openai"]["allowed_classifications"] == ["internal", "public"]  # known to policy, not set up
    assert "gemini" in by and by["gemini"]["allowed_classifications"] == ["public"]
    assert [r["tier"] for r in out["routing"]] == ["small", "medium", "reasoning"] and out["routing"][2]["price_per_1k_usd"] > 0
    assert out["scheduler"] == {"running": 0, "queued": 0, "max_concurrent": 4, "max_queued": 20}


def test_a_failing_provider_and_the_fallbacks_it_caused_show_up():
    class Down:
        name = "azure_openai"

        def complete_json(self, **kw):
            raise PermanentError("deployment gone")

    class Backup:
        name = "openai"

        def complete_json(self, *, context, **kw):
            from app.control_plane.llm import ProviderResponse
            return ProviderResponse(context.get("stub_output", {}), "{}", 10, 10)

    svc, c = make()
    svc._provider = lambda: Down()
    svc.register_provider(Backup())
    assert c.post("/engagements", json={**REQ, "data_classification": "public"}, headers=ADMIN).json()["status"] == "awaiting_approval"
    out = c.get("/governance/providers", headers=ADMIN).json()
    by = {p["name"]: p for p in out["providers"]}
    assert by["azure_openai"]["breaker"]["state"] == "open" and by["azure_openai"]["breaker"]["trips"] == 1
    assert "deployment gone" in by["azure_openai"]["breaker"]["last_error"]
    assert by["openai"]["configured"] and by["openai"]["breaker"]["state"] == "closed"
    assert out["fallbacks"] and out["fallbacks"][0]["to_provider"] == "openai" and out["fallbacks"][0]["data_classification"] == "public"


# ---- budgets ---------------------------------------------------------------------------------------------------------------------
def test_budgets_show_the_limits_and_how_close_recent_runs_came():
    svc, c = make()
    c.post("/engagements", json=REQ, headers=ADMIN)
    svc.db.save_run_metrics({"workflow_id": "wf_hot", "created_at": "2099-01-01T00:00:00+00:00", "status": "escalated", "scores": {},
                             "cost_usd": 1.9, "input_tokens": 1000, "output_tokens": 500, "tool_calls": 10, "duration_sec": 30.0})
    out = c.get("/governance/budgets", headers=ADMIN).json()
    assert out["defaults"] == {"max_tokens": 100000, "max_cost_usd": 2.0, "max_duration_sec": 300, "max_tool_calls": 100}
    hot = next(r for r in out["recent"] if r["workflow_id"] == "wf_hot")
    assert hot["tightest"] == "cost_usd" and hot["near_limit"] is True and hot["utilization"] == pytest.approx(0.95)
    normal = next(r for r in out["recent"] if r["workflow_id"] != "wf_hot")
    assert normal["near_limit"] is False and out["near_limit_count"] == 1


def test_budgets_include_runs_in_flight():
    svc, c = make()
    release = threading.Event()
    real = svc.graph.invoke
    svc.graph.invoke = lambda payload, cfg: (release.wait(10), real(payload, cfg))[1]
    wid = svc.start(**REQ, wait=False)["workflow_id"]
    deadline = time.monotonic() + 5
    while svc.db.get_engagement(wid)["status"] != "running" and time.monotonic() < deadline:
        time.sleep(0.02)
    out = c.get("/governance/budgets", headers=ADMIN).json()
    assert [r["workflow_id"] for r in out["running"]] == [wid] and out["running"][0]["status"] == "running"
    release.set()
    svc.wait(wid, 10)


# ---- degradation ---------------------------------------------------------------------------------------------------------------------
def test_degradation_view_shows_the_current_level_what_it_changes_and_the_history():
    svc, c = make()
    healthy = c.get("/governance/degradation", headers=ADMIN).json()
    assert healthy["state"]["level"] == "normal" and healthy["events"] == []
    assert healthy["state"]["actions"] == {"tier_boost": 0, "retrieval_k_multiplier": 1, "require_review": False}
    import datetime as dt
    for i in range(12):
        svc.db.save_run_metrics({"workflow_id": f"wf_s{i}", "created_at": dt.datetime.now(dt.UTC).isoformat(), "status": "completed",
                                 "scores": {"groundedness": 0.5, "tool_call_accuracy": 1.0}})
    c.post("/engagements", json=REQ, headers=ADMIN)
    bad = c.get("/governance/degradation", headers=ADMIN).json()
    assert bad["state"]["level"] == "restricted" and bad["state"]["actions"]["require_review"] is True
    assert bad["events"][0]["to_level"] == "restricted" and bad["events"][0]["from_level"] == "normal"
    assert any("groundedness" in r for r in bad["events"][0]["reasons"])
