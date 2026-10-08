import itertools
from pathlib import Path

import pytest

from app.config import Settings
from app.control_plane.guardian import GuardianDecision
from app.control_plane.guardian_llm import LEVEL, STRICTNESS, merge
from app.control_plane.judge import numeric_contradictions, tool_call_accuracy, verified_ratio
from app.control_plane.llm import ProviderResponse
from app.control_plane.reliability import PermanentError
from app.security.auth import Principal
from app.workflow.graph import RUNTIMES
from app.workflow.service import EngagementService

REQ = {"business_problem": "Should we expand into the UAE market?", "industry": "Retail",
       "objectives": ["Increase revenue"], "constraints": ["Budget under $10M", "Launch within 18 months"]}
PARTNER = Principal("p1", "Pat", ("Partner",))


class Scripted:
    """Offline stub, except `override(kind, stub, prompt)` may rewrite the judge ("judge") or the
    Guardian reviewer ("reviewer") output, or raise. Records every prompt it was sent."""
    name = "azure_openai"

    def __init__(self, judge=None, reviewer=None):
        self.judge, self.reviewer, self.prompts, self.reviews = judge, reviewer, [], 0

    def complete_json(self, *, task, system, prompt, schema, context, model):
        stub = context.get("stub_output", {})
        props = schema.get("properties", {})
        self.prompts.append((task, prompt))
        if "caveats" in props and self.reviewer:
            self.reviews += 1
            return ProviderResponse(self.reviewer(self.reviews, stub), "", 10, 10)
        if "task_adherence" in props and self.judge:
            return ProviderResponse(self.judge(stub), "", 10, 10)
        return ProviderResponse(stub, "", 10, 10)


def run(provider=None, settings=None, **over):
    svc = EngagementService(settings) if settings else EngagementService()
    if provider:
        svc._provider = lambda: provider
    return svc, svc.start(**{**REQ, **over})


def review(action="ALLOW", level="low", reasons=(), feedback="", caveats=()):
    return {"action": action, "risk_level": level, "reasons": list(reasons), "feedback": feedback,
            "caveats": list(caveats)}


# ---- judge scores -------------------------------------------------------------------------------
def test_stub_run_has_full_judged_scores():
    _, out = run()
    sc = out["state"]["evaluation_scores"]
    for k in ("groundedness", "citation_validity", "task_adherence", "contradiction_free",
              "tool_call_accuracy", "judge_coverage", "constraint_satisfaction", "quality"):
        assert k in sc, k
    assert (sc["task_adherence"], sc["contradiction_free"], sc["judge_coverage"]) == (1.0, 1.0, 1.0)
    assert sc["groundedness"] == 1.0 and sc["tool_call_accuracy"] == 1.0 and sc["quality"] > 0.9


def test_judge_can_lower_groundedness_but_never_raise_it():
    _, low = run(Scripted(judge=lambda s: {**s, "groundedness": 0.3}))
    assert low["state"]["evaluation_scores"]["groundedness"] == 0.3
    assert any("groundedness below minimum" in r for g in low["guardian_decisions"] for r in g["reasons"])
    assert low["state"]["evaluation_scores"]["citation_validity"] == 1.0   # evidence share is separate
    claims = [{"verified": True}, {"verified": False}]
    assert verified_ratio(claims) == 0.5 and verified_ratio([]) == 0.0
    _, high = run(Scripted(judge=lambda s: {**s, "groundedness": 1.0}))
    assert high["state"]["evaluation_scores"]["groundedness"] == 1.0       # bounded by verified share (1.0 here)


def test_judge_contradictions_are_scored_and_surfaced():
    contra = [{"description": "rationale cites a 40% margin not in the data", "severity": "medium"}]
    _, out = run(Scripted(judge=lambda s: {**s, "contradictions": contra}))
    sc = out["state"]["evaluation_scores"]
    assert sc["contradiction_free"] == pytest.approx(0.75)
    assert any("40% margin" in f["issue"] for f in out["state"]["failures"] if f["type"] == "eval_issue")


def test_unavailable_judge_escalates_instead_of_trusting_the_recommendation():
    def judge(stub):
        raise PermanentError("judge deployment missing")
    _, out = run(Scripted(judge=judge))
    sc = out["state"]["evaluation_scores"]
    assert sc["judge_coverage"] == 0.0 and sc["task_adherence"] == 0.0
    assert out["status"] == "awaiting_approval"
    assert any("LLM judge unavailable" in r for g in out["guardian_decisions"] for r in g["reasons"])


def test_numeric_contradictions_are_found_by_code_not_by_the_model():
    state = {"financial_models": [{"id": "B", "investment": 2e6, "roi": 0.5, "npv": 1e5}],
             "recommendation": {"id": "B", "cost_usd": 2e6, "roi": 0.9, "npv": 1e5}, "constraints": []}
    c = numeric_contradictions(state)
    assert len(c) == 1 and c[0].source == "deterministic" and "roi" in c[0].description
    assert numeric_contradictions({**state, "recommendation": {**state["recommendation"], "roi": 0.5}}) == []
    ghost = numeric_contradictions({**state, "recommendation": {"id": "Z"}})
    assert ghost and "no financial model" in ghost[0].description
    broke = numeric_contradictions({"financial_models": [], "constraints": ["Budget under $1M"],
                                    "recommendation": {"cost_usd": 5e6}})
    assert any("stated constraint" in x.description for x in broke)


def test_tool_call_accuracy_from_trace():
    spans = [{"kind": "tool", "status": "ok"}, {"kind": "tool", "status": "error"}, {"kind": "llm", "status": "ok"}]
    assert tool_call_accuracy(spans, []) == 0.5
    assert tool_call_accuracy([{"kind": "llm", "status": "ok"}], []) == 1.0
    assert tool_call_accuracy([{"kind": "tool", "status": "ok"}], [{"type": "invalid_schema", "tool": "x"}]) == 0.5


# ---- Guardian layer 2: stricter only ----------------------------------------------------------------
def base_decision(action, level="low"):
    return GuardianDecision(action, level, {"low": 0.1, "medium": 0.5, "high": 0.8}[level], ["rule"])


def test_merge_never_loosens_and_is_monotonic():
    for base_action, base_level, r_action, r_level in itertools.product(
            ["ALLOW", "MODIFY", "ESCALATE"], ["low", "medium", "high"],
            ["ALLOW", "MODIFY", "RETRY", "ESCALATE", "BLOCK"], ["low", "medium", "high"]):
        base = base_decision(base_action, base_level)
        for retries in (0, 1):
            out = merge(base, review(r_action, r_level, ["r"], "fix it", ["caveat"]), retries)
            if out.action == "RETRY":
                assert retries > 0 and base.action != "ESCALATE" or retries > 0
                continue
            assert STRICTNESS[out.action] >= STRICTNESS[base.action]
            assert LEVEL[out.risk_level] >= LEVEL[base.risk_level]
            assert out.risk_score >= base.risk_score
            assert out.reasons[:len(base.reasons)] == base.reasons
    assert merge(base_decision("ESCALATE", "high"), review("ALLOW"), 1).action == "ESCALATE"
    assert merge(base_decision("ESCALATE", "high"), review("ALLOW", "low"), 1).risk_level == "high"


def test_merge_outcomes():
    allow = base_decision("ALLOW")
    assert merge(allow, review(), 1).source == "deterministic"                      # nothing to add
    mod = merge(allow, review("MODIFY", "medium", ["thin evidence"], caveats=["a", "b", "c", "d", " "]), 1)
    assert mod.action == "MODIFY" and mod.modifications["caveats"] == ["a", "b", "c"] and mod.source == "combined"
    assert "reviewer: thin evidence" in mod.reasons
    esc = merge(allow, review("ESCALATE", "low", ["unclear"]), 1)
    assert (esc.action, esc.risk_level) == ("ESCALATE", "high")                    # escalation implies high
    retry = merge(allow, review("RETRY", reasons=["bad rationale"], feedback="fix the rationale"), 1)
    assert retry.action == "RETRY" and retry.feedback == "fix the rationale"
    assert merge(allow, review("RETRY", feedback="x"), 0).action == "ESCALATE"      # none left: a human decides
    assert merge(allow, review("BLOCK", "high", ["fabricated"]), 1).action == "BLOCK"


def test_reviewer_cannot_downgrade_a_rule_based_escalation_end_to_end():
    p = Scripted(reviewer=lambda n, s: review("ALLOW", "low"))
    _, out = run(p)
    assert out["status"] == "awaiting_approval" and out["state"]["risk_level"] == "high"
    assert p.reviews == 1 and out["guardian_decisions"][-1]["action"] == "ESCALATE"


def test_reviewer_block_halts_the_run():
    _, out = run(Scripted(reviewer=lambda n, s: review("BLOCK", "high", ["evidence looks fabricated"])))
    assert out["status"] == "escalated" and "guardian blocked" in out["halted_reason"]
    assert "report" not in out["state"]


def test_retry_sends_feedback_to_solution_once_then_continues():
    p = Scripted(reviewer=lambda n, s: review("RETRY", "medium", ["rationale ignores the risk"],
                                              "Mention the regulatory delay risk explicitly") if n == 1
                 else review("ALLOW"))
    svc, out = run(p)
    assert out["status"] == "awaiting_approval"
    actions = [g["action"] for g in out["guardian_decisions"] if g.get("subject") == "workflow"]
    assert actions == ["RETRY", "ESCALATE"] and out["state"]["retry_count"] == 1
    solution_prompts = [pr for t, pr in p.prompts if t == "strategy"]
    assert len(solution_prompts) == 2
    assert "regulatory delay risk" not in solution_prompts[0] and "regulatory delay risk" in solution_prompts[1]
    spans = [s["name"] for s in svc.trace(out["workflow_id"])["spans"] if s["kind"] in {"agent", "guardian"}]
    assert spans.count("solution_agent") == 2 and spans.count("guardian") == 2


def test_retries_are_bounded_then_a_human_decides():
    p = Scripted(reviewer=lambda n, s: review("RETRY", "medium", ["still wrong"], "fix it"))
    _, out = run(p)
    actions = [g["action"] for g in out["guardian_decisions"] if g.get("subject") == "workflow"]
    assert actions == ["RETRY", "ESCALATE"] and out["status"] == "awaiting_approval"   # not an infinite loop
    assert out["state"]["retry_count"] == 1


def test_deterministic_defects_trigger_a_retry_before_a_human_sees_it():
    # a judge that finds a high-severity contradiction on the first look and none after the fix
    calls = {"n": 0}

    def judge(stub):
        calls["n"] += 1
        if calls["n"] == 1:
            return {**stub, "contradictions": [{"description": "rationale contradicts the ROI", "severity": "high"}]}
        return stub
    _, out = run(Scripted(judge=judge))
    decisions = [g for g in out["guardian_decisions"] if g.get("subject") == "workflow"]
    assert [g["action"] for g in decisions] == ["RETRY", "ESCALATE"]
    assert "contradict" in decisions[0]["reasons"][0] and out["state"]["evaluation_scores"]["contradiction_free"] == 1.0


# ---- MODIFY needs a base ALLOW: use a policy where the recommendation is not automatically high-risk ----
def lenient_settings(tmp_path):
    src = Path(Settings().policy_file).read_text(encoding="utf-8")
    lenient = (src.replace("client_facing_recommendation,", "")                       # no longer high-tier
               .replace("medium: [market_interpretation,", "medium: [client_facing_recommendation, market_interpretation,")
               .replace("financial_commitment_usd: 1000000", "financial_commitment_usd: 100000000"))
    assert "medium: [client_facing_recommendation" in lenient
    path = tmp_path / "policy.yaml"
    path.write_text(lenient, encoding="utf-8")
    return Settings(policy_file=str(path), llm_provider="stub")


def test_modify_adds_reviewer_caveats_and_proceeds_without_a_human(tmp_path):
    p = Scripted(reviewer=lambda n, s: review("MODIFY", "medium", ["thin local evidence"],
                                              caveats=["Validate demand with a pilot before scaling"]))
    _, out = run(p, settings=lenient_settings(tmp_path))
    assert out["status"] == "completed" and "Engagement Report" in out["state"]["report"]["markdown"]
    assert "Reviewer caveat: Validate demand with a pilot before scaling" in out["state"]["recommendation"]["assumptions"]
    last = [g for g in out["guardian_decisions"] if g.get("subject") == "workflow"][-1]
    assert last["action"] == "MODIFY" and last["source"] == "combined"


def test_allow_path_still_completes_without_approval_under_lenient_policy(tmp_path):
    _, out = run(settings=lenient_settings(tmp_path))
    assert out["status"] == "completed" and out["state"]["approval_status"] == "not_required"


def test_guardian_log_endpoint_exposes_layer_and_modifications(tmp_path):
    svc, out = run(Scripted(reviewer=lambda n, s: review("ESCALATE", "high", ["partner should look"])))
    log = svc.guardian(out["workflow_id"])
    assert log[-1]["source"] == "combined" and "reviewer: partner should look" in log[-1]["reasons"]
    RUNTIMES.pop(out["workflow_id"])
    assert svc.guardian(out["workflow_id"])[-1]["source"] == "combined"             # persisted snapshot
