import time

import pytest

from app.config import Settings, get_settings
from app.control_plane.budget import Budget
from app.control_plane.limits import LimiterRegistry
from app.control_plane.llm import LLMGateway, LLMUnavailable, ProviderResponse
from app.control_plane.policy import PolicyEngine
from app.control_plane.providers import BreakerRegistry, FallbackLog
from app.control_plane.reliability import PermanentError, TransientError
from app.control_plane.router import ModelRouter, NoProviderAvailable
from app.observability.tracing import TraceStore
from app.workflow.service import EngagementService

SCHEMA = {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}, "additionalProperties": False}
POLICY = PolicyEngine.from_file(get_settings().policy_file)
REQ = {"business_problem": "Should we expand into the UAE market?", "industry": "Retail", "constraints": ["Budget under $10M"]}


class Fake:
    """A provider that fails on demand and records exactly what it was sent."""

    def __init__(self, name, error=None, content=None):
        self.name, self.error, self.content = name, error, content or {"a": "ok"}
        self.calls, self.seen = 0, []

    def complete_json(self, *, task, system, prompt, schema, context, model):
        self.calls += 1
        self.seen.append((system, prompt))
        if self.error:
            raise self.error
        return ProviderResponse(self.content, "{}", 10, 10)


def gateway(*providers, breakers=None, limiters=None, **kw):
    pool = {p.name: p for p in providers}
    log = {"failures": []}
    trace = TraceStore("wf")
    gw = LLMGateway(ModelRouter(POLICY, providers=list(pool)), pool, Budget(), trace, log,
                    breaker=breakers or BreakerRegistry(failure_threshold=2, reset_after_sec=0.3),
                    limiter=limiters, fallbacks=FallbackLog(), pii_mode=POLICY.pii_mode, sleep=lambda s: None, **kw)
    return gw, log, trace


def ask(gw, classification="public", prompt="hello"):
    return gw.structured(agent="research_agent", task="extraction", prompt=prompt, schema=SCHEMA, context={},
                         data_classification=classification)


# ---- failover respects the data classification ------------------------------------------------------------------
def test_public_data_falls_back_to_the_next_permitted_provider():
    azure, openai = Fake("azure_openai", PermanentError("deployment gone")), Fake("openai")
    gw, log, trace = gateway(azure, openai)
    out = ask(gw, "public")
    assert out.provider == "openai" and azure.calls == 1 and openai.calls == 1
    ev = gw.fallbacks.recent()[0]
    assert (ev["from_provider"], ev["to_provider"], ev["data_classification"]) == ("azure_openai", "openai", "public")
    assert "deployment gone" in ev["reason"]
    assert [s.attributes["gen_ai.system"] for s in trace.spans if s.kind == "llm"] == ["azure_openai", "openai"]
    assert log["fallbacks"][0]["to_provider"] == "openai"


def test_confidential_data_never_goes_to_a_provider_policy_does_not_allow_for_it():
    azure, openai = Fake("azure_openai", PermanentError("down")), Fake("openai")
    gw, log, _ = gateway(azure, openai)
    with pytest.raises(LLMUnavailable, match="unavailable"):
        ask(gw, "confidential")
    assert openai.calls == 0, "confidential data reached a provider that is not permitted for it"
    assert gw.fallbacks.recent()[-1]["to_provider"] is None  # nothing permitted remained: escalate
    assert [f["type"] for f in log["failures"]][-2:] == ["llm_unavailable", "no_provider"]


def test_internal_data_may_use_openai_but_not_gemini():
    azure, openai, gemini = Fake("azure_openai", TransientError("503")), Fake("openai", PermanentError("auth")), Fake("gemini")
    gw, _, _ = gateway(azure, openai, gemini, breakers=BreakerRegistry(failure_threshold=10))
    with pytest.raises(LLMUnavailable):
        ask(gw, "internal")
    assert (azure.calls, openai.calls, gemini.calls) == (3, 1, 0)  # azure retried; openai tried once; gemini never
    ok, _, _ = gateway(Fake("azure_openai", PermanentError("x")), Fake("openai"), Fake("gemini"))
    assert ask(ok, "internal").provider == "openai"


def test_providers_are_tried_in_the_order_they_were_registered():
    gw, _, _ = gateway(Fake("azure_openai", PermanentError("x")), Fake("gemini"), Fake("openai"))
    assert ask(gw, "public").provider == "gemini"


def test_no_provider_permitted_at_all_is_an_escalation_not_a_crash():
    gw, _, _ = gateway(Fake("gemini"))  # only a provider that policy forbids for confidential data is configured
    with pytest.raises(NoProviderAvailable, match="no provider is permitted"):
        ask(gw, "confidential")


def test_a_transient_failure_that_retries_successfully_does_not_fail_over():
    class RecoversOnSecond(Fake):
        def complete_json(self, **kw):
            self.calls += 1
            if self.calls == 1:
                raise TransientError("429", retry_after=0.0)
            return ProviderResponse({"a": "ok"}, "{}", 10, 10)

    azure, openai = RecoversOnSecond("azure_openai"), Fake("openai")
    gw, _, _ = gateway(azure, openai)
    assert ask(gw, "public").provider == "azure_openai" and openai.calls == 0 and not gw.fallbacks.recent()


def test_a_provider_over_its_rate_limit_for_too_long_is_skipped_for_public_data():
    limiters = LimiterRegistry({"azure_openai": {"requests_per_minute": 1, "queue_timeout_sec": 0.2}})
    azure, openai = Fake("azure_openai"), Fake("openai")
    gw, _, _ = gateway(azure, openai, limiters=limiters)
    assert ask(gw, "public").provider == "azure_openai"   # the one allowed request this minute
    assert ask(gw, "public").provider == "openai"         # azure is now over its limit: use the other
    assert openai.calls == 1 and "rate limit" in gw.fallbacks.recent()[-1]["reason"]


# ---- circuit breakers, one per provider -------------------------------------------------------------------------------
def test_a_failing_provider_trips_its_own_breaker_and_is_then_skipped_without_being_called():
    breakers = BreakerRegistry(failure_threshold=2, reset_after_sec=60)
    azure, openai = Fake("azure_openai", PermanentError("down")), Fake("openai")
    gw, _, _ = gateway(azure, openai, breakers=breakers)
    ask(gw, "public")
    ask(gw, "public")
    assert breakers.get("azure_openai").state == "open" and breakers.get("openai").state == "closed"
    before = azure.calls
    ask(gw, "public")
    assert azure.calls == before, "an open circuit must not hit the failing provider"
    snap = {s["provider"]: s for s in breakers.snapshot(["azure_openai", "openai"])}
    assert snap["azure_openai"]["state"] == "open" and snap["azure_openai"]["trips"] == 1
    assert snap["azure_openai"]["last_error"] and "down" in snap["azure_openai"]["last_error"]
    assert snap["azure_openai"]["retry_in_sec"] > 0 and snap["openai"]["state"] == "closed"


def test_the_breaker_lets_a_trial_through_after_the_reset_time_and_closes_on_success():
    breakers = BreakerRegistry(failure_threshold=1, reset_after_sec=0.2)

    class Heals(Fake):
        def complete_json(self, **kw):
            self.calls += 1
            if self.calls == 1:
                raise PermanentError("down")
            return ProviderResponse({"a": "ok"}, "{}", 10, 10)

    azure, openai = Heals("azure_openai"), Fake("openai")
    gw, _, _ = gateway(azure, openai, breakers=breakers)
    assert ask(gw, "public").provider == "openai" and breakers.get("azure_openai").state == "open"
    time.sleep(0.25)
    assert breakers.get("azure_openai").state == "half_open"
    assert ask(gw, "public").provider == "azure_openai"           # the trial call goes to the recovered provider
    assert breakers.get("azure_openai").state == "closed"


def test_the_snapshot_lists_requested_providers_even_before_any_call():
    snap = BreakerRegistry().snapshot(["azure_openai"])
    assert snap == [{"provider": "azure_openai", "state": "closed", "consecutive_failures": 0, "failure_threshold": 5,
                     "trips": 0, "retry_in_sec": None, "last_error": None, "last_error_at": None}]


# ---- PII at the gateway ----------------------------------------------------------------------------------------------------
SECRET = "sk_live_" + "a1b2c3d4e5f6g7h8i9j0k1l2"
PROMPT = f"Contact ann@corp.com or +44 7700 900123 about the deal. key={SECRET} card 4111 1111 1111 1111"


def test_personal_identifiers_and_secrets_are_masked_before_a_confidential_prompt_leaves():
    azure = Fake("azure_openai")
    gw, _, trace = gateway(azure)
    ask(gw, "confidential", PROMPT)
    sent = azure.seen[0][1]
    for raw in ("ann@corp.com", "+44 7700 900123", SECRET, "4111 1111 1111 1111"):
        assert raw not in sent
    assert "[email]" in sent and "[phone]" in sent and "[secret]" in sent and "[card]" in sent
    span = next(s for s in trace.spans if s.kind == "llm")
    assert span.attributes["consultai.pii_redacted"]["email"] == 1 and span.attributes["consultai.pii_redacted"]["secret"] >= 1


def test_where_policy_allows_personal_identifiers_secrets_are_still_never_sent():
    azure = Fake("azure_openai")
    gw, _, _ = gateway(azure)
    ask(gw, "public", PROMPT)  # policy: public data is `allow`
    sent = azure.seen[0][1]
    assert "ann@corp.com" in sent and "+44 7700 900123" in sent      # allowed
    assert SECRET not in sent and "[secret]" in sent                  # never


def test_clean_prompts_are_untouched_and_not_flagged():
    azure = Fake("azure_openai")
    gw, _, trace = gateway(azure)
    ask(gw, "confidential", "Budget under $10M, launch in 18 months, ROI 16.3%")
    assert azure.seen[0][1] == "Budget under $10M, launch in 18 months, ROI 16.3%"
    assert "consultai.pii_redacted" not in next(s for s in trace.spans if s.kind == "llm").attributes


def test_the_malformed_output_repair_prompt_is_scrubbed_too():
    class BadThenGood(Fake):
        def complete_json(self, **kw):
            self.calls += 1
            self.seen.append((kw["system"], kw["prompt"]))
            if self.calls == 1:
                return ProviderResponse({"wrong": "leaks ann@corp.com"}, '{"wrong": "leaks ann@corp.com"}', 5, 5)
            return ProviderResponse({"a": "fixed"}, "{}", 5, 5)

    azure = BadThenGood("azure_openai")
    gw, _, _ = gateway(azure)
    assert ask(gw, "confidential").stage == "repair"
    assert "ann@corp.com" not in azure.seen[1][1] and "[email]" in azure.seen[1][1]


# ---- end to end through the service ---------------------------------------------------------------------------------------
def settings():
    return Settings(llm_provider="stub", database_url="sqlite:///:memory:")


def test_a_confidential_engagement_escalates_when_its_only_permitted_provider_is_down():
    svc = EngagementService(settings())
    svc._provider = lambda: Fake("azure_openai", PermanentError("outage"))
    other = Fake("openai")
    svc.register_provider(other)
    out = svc.start(**REQ)  # confidential by default
    assert out["status"] == "escalated" and "discovery_agent" in out["halted_reason"]
    assert other.calls == 0
    assert svc.fallbacks.recent()[-1]["to_provider"] is None
    assert svc.breakers.snapshot(["azure_openai"])[0]["last_error"]


def test_a_public_engagement_survives_a_primary_outage_by_using_a_permitted_fallback():
    class Stubby(Fake):
        """A working provider that returns the agents' stub answers."""

        def complete_json(self, *, task, system, prompt, schema, context, model):
            self.calls += 1
            out = context.get("stub_output", {})
            return ProviderResponse(out, "{}", 100, 50)

    svc = EngagementService(settings())
    svc._provider = lambda: Fake("azure_openai", PermanentError("outage"))
    backup = Stubby("openai")
    svc.register_provider(backup)
    out = svc.start(**{**REQ, "data_classification": "public"})
    assert out["status"] == "awaiting_approval" and backup.calls >= 7
    assert any(e["to_provider"] == "openai" for e in svc.fallbacks.recent())
