from app.control_plane.degradation import ACTIONS, DegradationController, DegradationState

TH = {"min_groundedness": 0.75, "min_tool_call_accuracy": 0.9}


def run(g=0.95, t=1.0):
    return {"scores": {"groundedness": g, "tool_call_accuracy": t}}


def rows(n, **kw):
    return [run(**kw) for _ in range(n)]


def ctl(**kw):
    return DegradationController(TH, **kw)


def step(controller, rows_, state=None):
    return controller.evaluate(rows_, state or DegradationState())


def test_healthy_runs_keep_the_system_normal_and_return_the_same_object():
    state = DegradationState()
    out = step(ctl(), rows(5), state)
    assert out.level == "normal" and not out.actions.require_review
    assert out.metrics == {"groundedness": 0.95, "tool_call_accuracy": 1.0} and out.runs_considered == 5


def test_too_little_evidence_changes_nothing_either_way():
    c = ctl(min_runs=3)
    assert step(c, rows(2, g=0.1)).level == "normal"
    bad = step(c, rows(5, g=0.5))
    assert bad.level != "normal"
    assert c.evaluate(rows(2), bad) is bad  # and it does not recover on two good runs


def test_one_metric_below_its_minimum_makes_the_system_cautious():
    out = step(ctl(), rows(5, g=0.70))  # groundedness 0.70 < 0.75, but not far below
    assert out.level == "cautious"
    assert out.actions == ACTIONS["cautious"]
    assert out.actions.tier_boost == 1 and out.actions.retrieval_k_multiplier == 2 and out.actions.require_review
    assert any("groundedness 0.70 is below the policy minimum 0.75" in r for r in out.reasons)


def test_tool_correctness_alone_also_triggers_it():
    out = step(ctl(), rows(5, t=0.8))
    assert out.level == "cautious" and any("tool call accuracy" in r for r in out.reasons)


def test_two_metrics_below_minimum_is_restricted():
    out = step(ctl(), rows(5, g=0.7, t=0.8))
    assert out.level == "restricted" and out.actions.retrieval_k_multiplier == 3 and out.actions.require_review


def test_one_metric_far_below_its_minimum_is_restricted():
    assert step(ctl(), rows(5, g=0.4)).level == "restricted"  # 0.40 is more than 0.15 under 0.75


def test_only_the_recent_window_counts_so_old_failures_age_out():
    history = rows(10, g=0.2) + rows(10, g=0.95)
    assert step(ctl(window=10), history).level == "normal"
    assert step(ctl(window=20), history).level != "normal"


def test_it_gets_worse_immediately_but_recovers_one_level_at_a_time():
    c = ctl(window=5)
    restricted = step(c, rows(5, g=0.4, t=0.5))
    assert restricted.level == "restricted"
    stage1 = c.evaluate(rows(5), restricted)                      # fully healthy now
    assert stage1.level == "cautious"                             # one step, not straight to normal
    stage2 = c.evaluate(rows(5), stage1)
    assert stage2.level == "normal" and stage2.reasons == ("metrics have recovered above the policy minimums",)


def test_hysteresis_a_marginal_recovery_does_not_lower_the_level():
    c = ctl(window=5, recovery_margin=0.03)
    cautious = step(c, rows(5, g=0.70))
    just_above = c.evaluate(rows(5, g=0.76), cautious)  # above 0.75 but not by the margin
    assert just_above.level == "cautious"
    assert c.evaluate(rows(5, g=0.79), cautious).level == "normal"


def test_it_does_not_flap_around_the_threshold():
    c = ctl(window=4, min_runs=3)
    state = DegradationState()
    levels = []
    for _ in range(8):  # the same noisy window, seen again and again, right at the minimum
        state = c.evaluate([run(g=g) for g in (0.74, 0.76, 0.74, 0.76)], state)
        levels.append(state.level)
    assert len(set(levels)) == 1  # one level throughout, never alternating


def test_a_level_keeps_its_start_time_while_it_persists():
    c = ctl()
    first = step(c, rows(5, g=0.7))
    again = c.evaluate(rows(6, g=0.7), first)
    assert again.level == "cautious" and again.since == first.since and again.runs_considered == 6


def test_runs_without_scores_are_ignored_and_missing_metrics_do_not_break_it():
    out = step(ctl(), [{"scores": {}}, {"scores": {"groundedness": 0.95}}, {}, run(), run(), run()])
    assert out.level == "normal"
    only_g = step(ctl(), [{"scores": {"groundedness": 0.5}}] * 4)
    assert only_g.level == "restricted" and "tool_call_accuracy" not in only_g.metrics


def test_no_threshold_for_a_metric_means_it_is_not_enforced():
    assert DegradationController({}, min_runs=1).evaluate(rows(5, g=0.0, t=0.0), DegradationState()).level == "normal"


def test_state_serialises_with_its_actions_for_the_api():
    d = step(ctl(), rows(5, g=0.7)).to_dict()
    assert d["level"] == "cautious" and d["actions"] == {"tier_boost": 1, "retrieval_k_multiplier": 2, "require_review": True}
    assert isinstance(d["reasons"], list) and d["runs_considered"] == 5


# ---- wiring ------------------------------------------------------------------------------------------------------------
import datetime as dt

from app.config import Settings, get_settings
from app.control_plane.policy import PolicyEngine
from app.control_plane.router import ModelRouter
from app.security.auth import Principal
from app.workflow.service import EngagementService

POLICY = PolicyEngine.from_file(get_settings().policy_file)
REQ = {"business_problem": "Should we expand into the UAE market?", "industry": "Retail", "constraints": ["Budget under $10M"]}
PARTNER = Principal("p", "Pat", ("Partner",))


def tiers(boost, **kw):
    router = ModelRouter(POLICY, tier_boost=boost)
    return {t: router.route(t, **kw).tier for t in ("extraction", "research_synthesis", "strategy", "schema_repair")}


def test_a_boost_moves_each_task_one_tier_up_but_never_past_reasoning_and_never_for_repairs():
    assert tiers(0) == {"extraction": "small", "research_synthesis": "medium", "strategy": "reasoning", "schema_repair": "small"}
    assert tiers(1) == {"extraction": "medium", "research_synthesis": "reasoning", "strategy": "reasoning", "schema_repair": "small"}
    assert tiers(5)["extraction"] == "reasoning"


def test_the_budget_still_wins_over_the_boost():
    assert tiers(1, remaining_budget_usd=0.001)["extraction"] == "small"  # cannot afford the stronger model


def settings_for(tmp_path=None, **over):
    url = f"sqlite:///{(tmp_path / 'd.db').as_posix()}" if tmp_path else "sqlite:///:memory:"
    return Settings(llm_provider="stub", database_url=url, **over)


def lenient_policy(tmp_path):
    from pathlib import Path
    src = Path(get_settings().policy_file).read_text(encoding="utf-8")
    text = (src.replace("client_facing_recommendation,", "")
            .replace("medium: [market_interpretation,", "medium: [client_facing_recommendation, market_interpretation,")
            .replace("financial_commitment_usd: 1000000", "financial_commitment_usd: 100000000"))
    path = tmp_path / "policy.yaml"
    path.write_text(text, encoding="utf-8")
    return str(path)


def seed(svc, n, g, t=1.0, day=1):
    for i in range(n):
        svc.db.save_run_metrics({"workflow_id": f"wf_seed_{day}_{i}", "created_at": dt.datetime.now(dt.UTC).isoformat(),
                                 "status": "completed", "scores": {"groundedness": g, "tool_call_accuracy": t}})


def test_while_cautious_a_run_retrieves_more_and_uses_stronger_models():
    svc = EngagementService(settings_for())
    from app.control_plane.degradation import DegradationState
    svc.degradation = DegradationState("cautious")
    wid = svc.start(**REQ)["workflow_id"]
    assert svc.evidence(wid)["retrievals"][0]["k"] == 4  # 2 x 2
    llm = {s["name"]: s["attributes"]["consultai.tier"] for s in svc.trace(wid)["spans"] if s["kind"] == "llm"}
    assert llm["llm:extraction"] == "medium"  # normally small


def test_while_cautious_a_run_the_guardian_would_have_allowed_still_goes_to_a_human(tmp_path):
    from app.control_plane.degradation import DegradationState
    normal = EngagementService(settings_for(policy_file=lenient_policy(tmp_path)))
    assert normal.start(**REQ)["status"] == "completed"  # baseline: this policy lets a clean run finish by itself
    svc = EngagementService(settings_for(policy_file=lenient_policy(tmp_path)))
    svc.degradation = DegradationState("cautious")
    out = svc.start(**REQ)
    assert out["status"] == "awaiting_approval"
    final = [g for g in out["guardian_decisions"] if g["subject"] == "workflow"][-1]
    assert final["action"] == "ESCALATE" and final["source"] == "combined"
    assert any("quality degradation (cautious): every run requires review" in r for r in final["reasons"])


def test_poor_quality_pushes_the_system_to_a_stricter_level_and_records_why(tmp_path):
    svc = EngagementService(settings_for(tmp_path))
    seed(svc, 12, g=0.5)
    wid = svc.start(**REQ)["workflow_id"]  # a finished run triggers the check
    assert svc.degradation.level == "restricted"
    events = svc.db.degradation_events_list()
    assert events[0]["from_level"] == "normal" and events[0]["to_level"] == "restricted"
    assert any("groundedness" in r for r in events[0]["reasons"]) and events[0]["metrics"]["groundedness"] < 0.75
    assert svc.db.run_metrics_rows()[-1]["workflow_id"] == wid


def test_the_level_survives_a_restart(tmp_path):
    first = EngagementService(settings_for(tmp_path))
    seed(first, 12, g=0.5)
    first.start(**REQ)
    assert first.degradation.level == "restricted"
    second = EngagementService(settings_for(tmp_path))  # a new process
    assert second.degradation.level == "restricted" and second.degradation.reasons


def test_the_next_run_after_degradation_is_actually_handled_more_carefully(tmp_path):
    svc = EngagementService(settings_for(tmp_path))
    seed(svc, 12, g=0.5)
    svc.start(**REQ)
    wid = svc.start(**REQ)["workflow_id"]
    assert svc.evidence(wid)["retrievals"][0]["k"] == 6  # restricted: 2 x 3
    assert next(r for r in svc.db.run_metrics_rows() if r["workflow_id"] == wid)["degradation_level"] == "restricted"


def test_it_recovers_one_level_at_a_time_as_quality_returns(tmp_path):
    svc = EngagementService(settings_for(tmp_path))
    seed(svc, 12, g=0.5)
    svc.start(**REQ)
    assert svc.degradation.level == "restricted"
    seen = []
    for batch in range(3):
        seed(svc, 10, g=0.98, day=10 + batch)   # a full window of good runs
        svc._update_degradation()
        seen.append(svc.degradation.level)
    assert seen[:2] == ["cautious", "normal"] and seen[-1] == "normal"
    assert [e["to_level"] for e in svc.db.degradation_events_list()] == ["normal", "cautious", "restricted"]  # newest first


def test_healthy_runs_never_degrade_the_system():
    svc = EngagementService(settings_for())
    for _ in range(4):
        svc.start(**REQ)
    assert svc.degradation.level == "normal" and svc.db.degradation_events_list() == []
