import pytest

from app.config import get_settings
from app.control_plane.budget import Budget, BudgetExceeded
from app.control_plane.policy import Decision, PolicyEngine
from app.control_plane.reliability import (
    CircuitBreaker,
    CircuitOpen,
    PermanentError,
    TransientError,
    call_with_retry,
)
from app.control_plane.router import ModelRouter
from app.control_plane.tool_registry import default_registry
from app.tools import financial
from app.tools.sql_validator import SQLValidationError, validate_readonly_sql


@pytest.fixture
def policy():
    return PolicyEngine.from_file(get_settings().policy_file)


def test_policy_allow_deny_escalate(policy):
    assert policy.check_tool("financial_agent", "calculate_roi").decision is Decision.ALLOW
    assert policy.check_tool("research_agent", "send_client_email").decision is Decision.DENY
    assert policy.check_tool("financial_agent", "approve_budget").decision is Decision.ESCALATE
    assert policy.check_tool("ghost_agent", "x").decision is Decision.DENY
    assert policy.check_tool("data_agent", "run_sql_readonly", "hr.salaries").decision is Decision.DENY


def test_policy_cache_and_version_invalidation(policy):
    policy.check_tool("financial_agent", "calculate_roi")
    policy.check_tool("financial_agent", "calculate_roi")
    assert policy.cache_hits == 1
    new = dict(policy._policy, version="next")
    policy.reload(new)
    policy.check_tool("financial_agent", "calculate_roi")
    assert policy.cache_misses == 2


def test_financial_threshold_escalates(policy):
    assert policy.check_financial_commitment(3_000_000).decision is Decision.ESCALATE
    assert policy.check_financial_commitment(500_000).decision is Decision.ALLOW


def test_unknown_action_is_high_risk(policy):
    assert policy.risk_tier("something_new") == "high"
    assert policy.risk_tier("summarization") == "low"


def test_financial_math():
    assert financial.calculate_roi(5_000_000, 1_500_000, 5)["roi"] == pytest.approx(0.5)
    assert financial.calculate_npv(0.1, [-100, 110])["npv"] == pytest.approx(0.0, abs=1e-9)
    assert financial.calculate_payback(2_000_000, 500_000)["payback_years"] == 4
    with pytest.raises(ValueError):
        financial.calculate_roi(0, 1, 1)


def test_tool_contract_validation():
    c = default_registry().get("calculate_roi")
    assert c.validate({"investment": 1, "annual_benefit": 1, "years": 1}) == []
    assert c.validate({"investment": 1})  # missing fields
    assert c.validate({"investment": 1, "annual_benefit": 1, "years": 1, "extra": 1})


def test_sql_validator():
    allowed = ["finance.revenue"]
    assert validate_readonly_sql("SELECT * FROM finance.revenue", allowed) == ["finance.revenue"]
    for bad in ["DROP TABLE finance.revenue", "SELECT 1; DELETE FROM finance.revenue",
                "SELECT * FROM hr.salaries", "UPDATE finance.revenue SET revenue=0"]:
        with pytest.raises(SQLValidationError):
            validate_readonly_sql(bad, allowed)


def test_budget_exceeded():
    b = Budget(max_tool_calls=2)
    b.record(tool_calls=2)
    with pytest.raises(BudgetExceeded):
        b.record(tool_calls=1)


def test_retry_transient_then_success():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise TransientError("429", retry_after=0)
        return "ok"
    assert call_with_retry(flaky, max_attempts=3, sleep=lambda s: None) == "ok"


def test_permanent_error_not_retried():
    calls = {"n": 0}

    def bad():
        calls["n"] += 1
        raise PermanentError("nope")
    with pytest.raises(PermanentError):
        call_with_retry(bad, max_attempts=3, sleep=lambda s: None)
    assert calls["n"] == 1


def test_circuit_breaker_opens():
    cb = CircuitBreaker(failure_threshold=2, reset_after_sec=999)

    def bad():
        raise TransientError("x")
    for _ in range(2):
        with pytest.raises(TransientError):
            call_with_retry(bad, max_attempts=1, breaker=cb, sleep=lambda s: None)
    with pytest.raises(CircuitOpen):
        call_with_retry(bad, max_attempts=1, breaker=cb, sleep=lambda s: None)


def test_router_respects_data_classification(policy):
    r = ModelRouter(policy)
    assert r.route("strategy", data_classification="confidential").provider == "azure_openai"
    with pytest.raises(RuntimeError):  # primary unavailable and no other provider is allowed
        r.route("strategy", data_classification="confidential", unavailable={"azure_openai"})
    assert r.route("strategy", data_classification="public", unavailable={"azure_openai"}).provider == "openai"


def test_router_downgrades_when_budget_low(policy):
    r = ModelRouter(policy)
    assert r.route("strategy", est_tokens=100_000, remaining_budget_usd=0.01).tier == "small"
