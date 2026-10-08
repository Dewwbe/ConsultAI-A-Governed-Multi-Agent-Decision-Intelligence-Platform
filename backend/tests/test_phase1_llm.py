from types import SimpleNamespace

import pytest

from app.config import get_settings
from app.control_plane.budget import Budget
from app.control_plane.llm import (
    AzureOpenAIProvider,
    LLMGateway,
    LLMUnavailable,
    ProviderResponse,
    SchemaEscalation,
    StubProvider,
)
from app.control_plane.policy import PolicyEngine
from app.control_plane.reliability import PermanentError, TransientError
from app.control_plane.router import ModelRouter
from app.observability.tracing import TraceStore
from app.prompts import PromptNotFound, available, get_prompt
from app.schemas.json_schema import STR, arr, is_strict_ready, obj

SCHEMA = obj(answer=STR, items=arr(STR))
GOOD = {"answer": "x", "items": []}


class ScriptedProvider:
    """Plays back responses/exceptions in order and records the model key of each call."""
    name = "azure_openai"

    def __init__(self, *script):
        self.script, self.models, self.tasks = list(script), [], []

    def complete_json(self, *, task, system, prompt, schema, context, model):
        self.models.append(model)
        self.tasks.append(task)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return ProviderResponse(step, str(step), 100, 50)


def gateway(provider, **kw):
    policy = PolicyEngine.from_file(get_settings().policy_file)
    log = {"failures": []}
    sleeps = []
    gw = LLMGateway(ModelRouter(policy), provider, Budget(), TraceStore("wf"), log,
                    sleep=sleeps.append, **kw)
    return gw, log, sleeps


def call(gw, **kw):
    return gw.structured(agent="a", task="extraction", prompt="hi", schema=SCHEMA, context={}, **kw)


# ---- prompt registry -------------------------------------------------------------------------
def test_registry_has_all_agent_prompts_and_renders():
    names = available()
    for n in ["discovery", "research", "sql_generation", "financial_cases", "risk_assessment",
              "solution_rationale", "schema_repair"]:
        assert 1 in names[n]
    p = get_prompt("discovery")
    system, user = p.render(business_problem="UAE?", industry="Retail", objectives=[], constraints=[])
    assert "UAE?" in user and p.id == "discovery@v1" and system


def test_registry_errors():
    with pytest.raises(PromptNotFound):
        get_prompt("nope")
    with pytest.raises(PromptNotFound):
        get_prompt("discovery", version=9)
    with pytest.raises(KeyError):  # a forgotten variable must never reach the model as "$x"
        get_prompt("discovery").render(business_problem="x")


# ---- malformed-output path -------------------------------------------------------------------
def test_valid_first_try():
    gw, log, _ = gateway(ScriptedProvider(GOOD))
    assert call(gw).stage == "initial" and log["failures"] == []


def test_repair_path_uses_small_model_and_records_failure():
    prov = ScriptedProvider({"answer": 1}, GOOD)
    gw, log, _ = gateway(prov)
    res = call(gw, risk_level="high")
    assert res.stage == "repair" and prov.tasks == ["extraction", "schema_repair"]
    assert prov.models[1] == "MODEL_SMALL"
    assert [f["stage"] for f in log["failures"]] == ["initial"]


def test_fallback_runs_next_stronger_tier():
    prov = ScriptedProvider({"bad": 1}, {"bad": 2}, GOOD)
    gw, _log, _ = gateway(prov)
    res = call(gw)  # extraction is a `small` task -> fallback is `medium`
    assert res.stage == "fallback" and prov.models == ["MODEL_SMALL", "MODEL_SMALL", "MODEL_MEDIUM"]


def test_non_json_output_is_repaired():
    prov = ScriptedProvider(None, GOOD)
    gw, log, _ = gateway(prov)
    assert call(gw).stage == "repair"
    assert "not valid JSON" in log["failures"][0]["errors"][0]


def test_escalates_after_repair_and_fallback_fail():
    gw, log, _ = gateway(ScriptedProvider({"x": 1}, {"x": 2}, {"x": 3}))
    with pytest.raises(SchemaEscalation):
        call(gw)
    assert log["failures"][-1]["type"] == "schema_escalation"


def test_cost_and_tokens_accumulate_across_attempts():
    gw, _, _ = gateway(ScriptedProvider({"x": 1}, GOOD))
    call(gw)
    assert gw.budget.tokens == 300 and gw.budget.cost_usd > 0


# ---- retry / 429 -----------------------------------------------------------------------------
def test_429_retry_after_is_honoured():
    gw, _, sleeps = gateway(ScriptedProvider(TransientError("429", retry_after=7.0), GOOD))
    assert call(gw).stage == "initial" and sleeps == [7.0]


def test_permanent_and_exhausted_errors_become_llm_unavailable():
    gw, log, _ = gateway(ScriptedProvider(PermanentError("bad request")))
    with pytest.raises(LLMUnavailable):
        call(gw)
    gw, log, _ = gateway(ScriptedProvider(*[TransientError("503")] * 3))
    with pytest.raises(LLMUnavailable):
        call(gw)
    assert log["failures"][0]["type"] == "llm_unavailable"


# ---- Azure provider (fake SDK client; no network) --------------------------------------------
class RateLimitError(Exception):  # the SDK class name is what the provider keys on
    status_code = 429

    def __init__(self, headers):
        super().__init__("slow down")
        self.response = SimpleNamespace(headers=headers)


def fake_client(result):
    calls = []

    def create(**kw):
        calls.append(kw)
        if isinstance(result, Exception):
            raise result
        return result

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), calls


def completion(text, refusal=None):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text, refusal=refusal))],
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7))


def azure(client):
    return AzureOpenAIProvider(client=client, deployments={"MODEL_SMALL": "gpt-small"})


def run(provider, schema=SCHEMA):
    return provider.complete_json(task="t", system="s", prompt="p", schema=schema, context={},
                                  model="MODEL_SMALL")


def test_azure_uses_strict_structured_outputs_and_reports_usage():
    client, calls = fake_client(completion('{"answer":"a","items":[]}'))
    out = run(azure(client))
    assert out.content == {"answer": "a", "items": []} and (out.input_tokens, out.output_tokens) == (11, 7)
    assert calls[0]["model"] == "gpt-small"
    assert calls[0]["response_format"]["json_schema"]["strict"] is True


def test_azure_falls_back_to_json_mode_for_loose_schema():
    client, calls = fake_client(completion("{}"))
    loose = {"type": "object", "required": ["a"], "properties": {"a": {"type": "string", "minLength": 1}}}
    assert not is_strict_ready(loose)
    run(azure(client), loose)
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert "JSON schema" in calls[0]["messages"][0]["content"]


def test_azure_429_maps_to_transient_with_retry_after():
    for headers, expected in [({"retry-after": "12"}, 12.0), ({"retry-after-ms": "1500"}, 1.5),
                              ({}, None)]:
        client, _ = fake_client(RateLimitError(headers))
        with pytest.raises(TransientError) as ei:
            run(azure(client))
        assert ei.value.retry_after == expected


def test_azure_error_classification_and_bad_output():
    client, _ = fake_client(ValueError("boom"))
    with pytest.raises(PermanentError):
        run(azure(client))
    client, _ = fake_client(completion('{"truncated'))
    assert run(azure(client)).content is None
    client, _ = fake_client(completion("", refusal="no"))
    with pytest.raises(PermanentError):
        run(azure(client))
    with pytest.raises(PermanentError, match="deployment"):
        AzureOpenAIProvider(client=SimpleNamespace(), deployments={}).complete_json(
            task="t", system="", prompt="", schema=SCHEMA, context={}, model="MODEL_SMALL")


def test_stub_provider_unchanged():
    assert run(StubProvider()).content == {}


def test_endpoint_is_reduced_to_base_url():
    from app.control_plane.llm import base_endpoint
    assert base_endpoint("https://x.services.ai.azure.com/openai/v1/responses") == "https://x.services.ai.azure.com"
    assert base_endpoint(" https://x.openai.azure.com/ ") == "https://x.openai.azure.com"
