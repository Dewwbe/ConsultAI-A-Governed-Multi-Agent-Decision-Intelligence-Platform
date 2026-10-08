import pytest

from app.control_plane.evaluator import evaluate
from app.control_plane.llm import ProviderResponse
from app.knowledge.risk_taxonomy import (
    CATEGORIES,
    TAXONOMY,
    calibrate,
    risk_lookup,
    similar_history,
)
from app.tools.constraints import parse_constraints, violations
from app.tools.financial import derive_annual_benefit
from app.workflow.service import EngagementService

REQ = {"business_problem": "Should we expand into the UAE market?", "industry": "Retail",
       "objectives": ["Increase revenue"], "constraints": ["Budget under $10M", "Launch within 18 months"]}


def run(provider=None, **overrides):
    svc = EngagementService()
    if provider:
        svc._provider = lambda: provider
    out = svc.start(**{**REQ, **overrides})
    return svc, out


class Scripted:
    """Stub behaviour, except `override(task, stub_output)` can rewrite a task's output."""
    name = "azure_openai"

    def __init__(self, override):
        self.override = override

    def complete_json(self, *, task, system, prompt, schema, context, model):
        out = self.override(task, context.get("stub_output", {}))
        return ProviderResponse(out, "", 10, 10)


# ---- constraint parsing ----------------------------------------------------------------------
@pytest.mark.parametrize("text,inv,months", [
    ("Budget under $10M", 10e6, None),
    ("Spend no more than $2.5 million", 2.5e6, None),
    ("Investment cap of 500K", 500e3, None),
    ("Budget: $1,200,000", 1.2e6, None),
    ("Launch within 18 months", None, 18),
    ("Go live in under 2 years", None, 24),
    ("Must be done within 26 weeks", None, 6.0),
])
def test_parse_constraints(text, inv, months):
    p = parse_constraints([text])
    assert p.max_investment == inv
    assert p.max_months == pytest.approx(months) if months else p.max_months is None
    assert p.unparsed == []


def test_unparseable_constraints_are_reported_and_tightest_wins():
    p = parse_constraints(["Budget under $10M", "Spend at most $4M", "Must use local staff"])
    assert p.max_investment == 4e6 and p.unparsed == ["Must use local staff"]
    assert violations({"cost_usd": 5e6, "launch_months": 20}, parse_constraints(
        ["Budget under $4M", "Launch within 18 months"])) == [
        "investment $5,000,000 exceeds ceiling $4,000,000", "launch in 20 months exceeds limit of 18 months"]
    assert violations({"cost_usd": 1}, p) == []


# ---- risk taxonomy ----------------------------------------------------------------------------
def test_taxonomy_covers_every_category_with_valid_bands():
    assert set(CATEGORIES) == set(TAXONOMY) and len(CATEGORIES) == 11
    for g in TAXONOMY.values():
        assert 0 <= g["probability"][0] < g["probability"][1] <= 1
        assert 0 <= g["impact"][0] < g["impact"][1] <= 1


def test_calibration_clamps_and_reports():
    assert calibrate("Regulatory", 0.6, 0.8) == (0.6, 0.8, None)
    p, i, note = calibrate("Cybersecurity", 0.95, 0.1)
    assert (p, i) == (0.4, 0.5) and "adjusted" in note


def test_risk_lookup_and_history():
    r = risk_lookup("expansion needs a market-entry licence and local partner")
    assert len(r["guidance"]) == 11 and {h["id"] for h in r["history"]} >= {"hist_001", "hist_003"}
    assert risk_lookup(category="Market")["guidance"][0]["category"] == "Market"
    with pytest.raises(ValueError):
        risk_lookup(category="Nonsense")
    assert similar_history("zzz") == []


def test_risk_agent_calibrates_model_ratings_and_records_precedents():
    def override(task, stub):
        if task == "risk":
            return {"risks": [
                {"risk": "Licence delay", "category": "Regulatory", "probability": 0.99, "impact": 0.2,
                 "mitigation": "Early filing"},
                {"risk": "Made up", "category": "Astrology", "probability": 0.5, "impact": 0.5,
                 "mitigation": "n/a"}]}
        return stub
    svc, out = run(Scripted(override))
    risks = out["state"]["risks"]
    assert [r["category"] for r in risks] == ["Regulatory"]                       # unknown category dropped
    assert (risks[0]["probability"], risks[0]["impact"]) == (0.8, 0.5)             # clamped to guidance
    assert "adjusted" in risks[0]["calibration"] and "hist_001" in risks[0]["precedents"]
    spans = [s["attributes"].get("gen_ai.tool.name") for s in svc.trace(out["workflow_id"])["spans"]]
    assert "risk_lookup" in spans                                                  # via the tool executor


# ---- financials trace to tools ------------------------------------------------------------------
def test_derive_annual_benefit_guards():
    assert derive_annual_benefit(1e6, 0.1, 0.3)["annual_benefit"] == pytest.approx(30_000)
    for args in [(0, 0.1, 0.3), (1e6, 0, 0.3), (1e6, 0.9, 0.3), (1e6, 0.1, -0.2)]:
        with pytest.raises(ValueError):
            derive_annual_benefit(*args)


def test_every_financial_figure_traces_to_a_tool_call():
    svc, out = run()
    tools = [s["attributes"] for s in svc.trace(out["workflow_id"])["spans"] if s["kind"] == "tool"]
    names = [t["gen_ai.tool.name"] for t in tools]
    for needed in ["calculate_margin", "calculate_growth", "derive_annual_benefit", "calculate_roi",
                   "calculate_npv", "calculate_payback", "risk_lookup", "run_sql_readonly"]:
        assert needed in names, needed
    derived = [t["consultai.tool_arguments"] for t in tools if t["gen_ai.tool.name"] == "derive_annual_benefit"]
    fm = {m["id"]: m for m in out["state"]["financial_models"]}
    for m in fm.values():
        a = m["assumptions"]
        assert m["annual_benefit"] == pytest.approx(a["baseline_revenue"] * m["uplift_pct"] * a["baseline_margin"])
    assert len(derived) == len(fm) and derived[0]["baseline_revenue"] == fm["A"]["assumptions"]["baseline_revenue"]
    purposes = [a["purpose"] for a in out["state"]["analysis_results"]]
    assert purposes == ["question", "baseline_revenue", "baseline_cost"]


def test_model_cannot_inject_dollar_benefits_or_out_of_range_uplift():
    def override(task, stub):
        if task == "financial":
            bad = {**stub["cases"][0], "id": "X", "uplift_pct": 0.9}            # >50% uplift: rejected
            return {"cases": [bad, stub["cases"][1]]}
        return stub
    _, out = run(Scripted(override))
    assert [m["id"] for m in out["state"]["financial_models"]] == ["B"]
    from app.workflow.graph import RUNTIMES
    assert any(f["type"] == "invalid_case" and f["case"] == "X" for f in RUNTIMES[out["workflow_id"]].log["failures"])


def test_missing_baseline_halts_instead_of_guessing():
    class NoData:
        def query(self, sql):
            return []

        def describe(self, tables):
            return {}

    import app.agents.data_analyst as da
    original = da.SqliteDataSource
    da.SqliteDataSource = NoData
    try:
        _, out = run()
    finally:
        da.SqliteDataSource = original
    assert out["status"] == "escalated" and "baseline" in out["halted_reason"]
    assert "recommendation" not in out["state"]


# ---- constraint-aware options and assumptions ------------------------------------------------------
def test_options_respect_budget_and_timeline_constraints():
    _, out = run(constraints=["Budget under $2.5M", "Launch within 10 months"])
    opts = {o["id"]: o for o in out["state"]["options"]}
    assert opts["A"]["within_budget"] is False and opts["B"]["within_constraints"] is True
    assert opts["C"]["within_timeline"] is False                      # 12 months > 10
    assert "launch in 12 months" in " ".join(opts["C"]["constraint_violations"])
    rec = out["state"]["recommendation"]
    assert rec["id"] == "B" and rec["cost_usd"] <= 2_500_000 and rec["launch_months"] <= 10
    assert out["state"]["evaluation_scores"]["constraint_satisfaction"] == pytest.approx(1 / 3)


def test_infeasible_constraints_are_flagged_and_escalated_not_hidden():
    _, out = run(constraints=["Budget under $1M"])
    rec = out["state"]["recommendation"]
    assert rec["within_constraints"] is False
    assert any("NO option satisfies" in a for a in rec["assumptions"])
    assert out["state"]["evaluation_scores"]["constraint_satisfaction"] == 0.0
    assert out["status"] == "awaiting_approval"                      # human must decide


def test_assumptions_are_explicit_and_include_unchecked_constraints():
    _, out = run(constraints=["Budget under $10M", "Must hire local staff"])
    a = out["state"]["recommendation"]["assumptions"]
    assert any(x.startswith("Benefits are flat") for x in a)
    assert any("operating margin, from the data warehouse" in x for x in a)
    assert any("revenue uplift" in x for x in a)
    assert "Constraint not machine-checked (confirm manually): Must hire local staff" in a


def test_evaluator_uses_same_rules_for_timeline():
    state = {"constraints": ["Launch within 12 months"],
             "options": [{"cost_usd": 1, "launch_months": 9}, {"cost_usd": 1, "launch_months": 18}],
             "recommendation": {"cost_usd": 1, "launch_months": 18}}
    rep = evaluate(state)
    assert rep.scores["constraint_satisfaction"] == 0.0
    assert any("violates constraints" in i for i in rep.issues)
