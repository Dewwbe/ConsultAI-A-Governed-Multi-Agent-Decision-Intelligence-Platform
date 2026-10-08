"""LLM gateway. `stub` runs offline; `azure_openai` calls Azure OpenAI with structured outputs.

Every call goes through `LLMGateway.structured`, which owns: routing, retry/backoff with
`Retry-After`, schema validation, the malformed-output path (repair -> fallback model ->
escalate), token/cost accounting, and tracing.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator

from app.observability.tracing import TraceStore
from app.prompts import PromptTemplate, get_prompt
from app.schemas.json_schema import is_strict_ready

from .budget import Budget
from .reliability import (
    CircuitBreaker,
    CircuitOpen,
    PermanentError,
    TransientError,
    call_with_retry,
)
from .router import PRICE_PER_1K, ModelRouter, Route

_NEXT_TIER = {"small": "medium", "medium": "reasoning", "reasoning": "reasoning"}


class SchemaEscalation(RuntimeError):
    """Output stayed invalid after repair and fallback: a human must look at it."""


class LLMUnavailable(RuntimeError):
    """Provider failed after retries (or the circuit is open): a human must look at it."""


@dataclass
class ProviderResponse:
    content: Any            # parsed JSON, or None when the text was not valid JSON
    raw: str
    input_tokens: int
    output_tokens: int


@dataclass
class LLMResult:
    content: dict[str, Any]
    input_tokens: int
    output_tokens: int
    cost_usd: float
    model: str
    provider: str
    stage: str = "initial"   # initial | repair | fallback


class LLMProvider(Protocol):
    name: str

    def complete_json(self, *, task: str, system: str, prompt: str, schema: dict[str, Any],
                      context: dict[str, Any], model: str) -> ProviderResponse: ...


class StubProvider:
    """Deterministic provider so the whole pipeline is testable without credentials.
    Agents supply `context['stub_output']`."""
    name = "azure_openai"  # impersonates the allowed provider for confidential data

    def complete_json(self, *, task, system, prompt, schema, context, model):
        out = context.get("stub_output", {})
        raw = json.dumps(out)
        return ProviderResponse(out, raw, (len(system) + len(prompt)) // 4 + 200, len(raw) // 4)


def _retry_after(exc: Exception) -> float | None:
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    try:
        if "retry-after-ms" in headers:
            return float(headers["retry-after-ms"]) / 1000
        if "retry-after" in headers:
            return float(headers["retry-after"])
    except (TypeError, ValueError):
        pass  # HTTP-date form: fall back to jittered backoff
    return None


def base_endpoint(url: str) -> str:
    """The SDK wants only scheme://host. Portals often show a full target URI
    (.../openai/v1/responses); keep just the base so a pasted URI still works."""
    parts = urlsplit(url.strip())
    return f"{parts.scheme}://{parts.netloc}" if parts.scheme and parts.netloc else url.strip()


class AzureOpenAIProvider:
    """Azure OpenAI chat completions with JSON-schema structured outputs.

    `deployments` maps the router's tier keys (MODEL_SMALL ...) to Azure deployment names.
    Auth is an API key if given, otherwise Microsoft Entra ID via `DefaultAzureCredential`.
    The SDK's own retries are disabled: the gateway retries so attempts are counted and
    traced, and honours `Retry-After` on 429.
    """
    name = "azure_openai"

    def __init__(self, *, endpoint: str = "", api_key: str = "", api_version: str = "2024-10-21",
                 deployments: dict[str, str] | None = None, timeout_sec: float = 30.0,
                 client: Any = None):
        self.deployments = deployments or {}
        self._client = client
        self._cfg = (endpoint, api_key, api_version, timeout_sec)

    @property
    def client(self) -> Any:
        if self._client is None:
            try:
                from openai import AzureOpenAI
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError("install the azure extra: pip install -e '.[azure]'") from exc
            endpoint, api_key, api_version, timeout = self._cfg
            if not endpoint:
                raise RuntimeError("AZURE_OPENAI_ENDPOINT is not set")
            endpoint = base_endpoint(endpoint)
            kwargs: dict[str, Any] = {"azure_endpoint": endpoint, "api_version": api_version,
                                      "timeout": timeout, "max_retries": 0}
            if api_key:
                kwargs["api_key"] = api_key
            else:
                from azure.identity import DefaultAzureCredential, get_bearer_token_provider
                kwargs["azure_ad_token_provider"] = get_bearer_token_provider(
                    DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default")
            self._client = AzureOpenAI(**kwargs)
        return self._client

    def _deployment(self, model_key: str) -> str:
        name = self.deployments.get(model_key, "")
        if not name:
            raise PermanentError(f"no Azure deployment configured for {model_key} "
                                 f"(set {model_key} in the environment)")
        return name

    def complete_json(self, *, task, system, prompt, schema, context, model):
        strict = is_strict_ready(schema)
        if strict:
            response_format = {"type": "json_schema", "json_schema": {
                "name": task[:60] or "output", "schema": schema, "strict": True}}
            sys_msg = system
        else:  # JSON mode: the schema travels in the prompt and is enforced by the gateway
            response_format = {"type": "json_object"}
            sys_msg = f"{system}\n\nJSON schema the answer must satisfy:\n{json.dumps(schema)}"
        deployment = self._deployment(model)
        try:
            resp = self.client.chat.completions.create(
                model=deployment, response_format=response_format,
                messages=[{"role": "system", "content": sys_msg}, {"role": "user", "content": prompt}])
        except Exception as exc:
            raise self._classify(exc) from exc
        choice = resp.choices[0]
        raw = choice.message.content or ""
        if getattr(choice.message, "refusal", None):
            raise PermanentError(f"model refused: {choice.message.refusal}")
        usage = resp.usage
        tin, tout = (usage.prompt_tokens, usage.completion_tokens) if usage else (0, 0)
        try:
            content = json.loads(raw)
        except json.JSONDecodeError:
            content = None  # truncated / not JSON -> gateway repair path
        return ProviderResponse(content, raw, tin, tout)

    @staticmethod
    def _classify(exc: Exception) -> Exception:
        status = getattr(exc, "status_code", None)
        cls = type(exc).__name__
        if status == 429 or cls == "RateLimitError":
            return TransientError(f"rate limited (429): {exc}", retry_after=_retry_after(exc))
        if cls in {"APITimeoutError", "APIConnectionError"} or (isinstance(status, int) and status >= 500):
            return TransientError(f"{cls}: {exc}", retry_after=_retry_after(exc))
        return PermanentError(f"{cls}: {exc}")


class LLMGateway:
    def __init__(self, router: ModelRouter, provider: LLMProvider, budget: Budget, trace: TraceStore,
                 log: dict[str, list] | None = None, breaker: CircuitBreaker | None = None,
                 sleep: Callable[[float], None] | None = None):
        self.router, self.provider, self.budget, self.trace = router, provider, budget, trace
        self.log = log if log is not None else {"failures": []}
        self.breaker = breaker
        self._sleep = sleep

    # -- one provider call: retry/backoff, validation, accounting ---------------------------
    def _attempt(self, *, agent: str, task: str, stage: str, prompt_id: str, route: Route,
                 system: str, prompt: str, schema: dict[str, Any], context: dict[str, Any]
                 ) -> tuple[LLMResult | None, list[str], Any]:
        with self.trace.span(f"llm:{task}", "llm", **{
                "gen_ai.agent.name": agent, "gen_ai.request.model": route.model_env_key,
                "gen_ai.system": route.provider, "consultai.tier": route.tier,
                "consultai.stage": stage, "consultai.prompt": prompt_id}) as span:
            kwargs = {} if self._sleep is None else {"sleep": self._sleep}
            try:
                resp: ProviderResponse = call_with_retry(
                    lambda: self.provider.complete_json(
                        task=task, system=system, prompt=prompt, schema=schema,
                        context=context, model=route.model_env_key),
                    breaker=self.breaker, **kwargs)
            except (TransientError, PermanentError, CircuitOpen, TimeoutError, ConnectionError) as exc:
                self.log["failures"].append({"type": "llm_unavailable", "task": task, "error": str(exc)})
                raise LLMUnavailable(f"{task}: {exc}") from exc
            cost = PRICE_PER_1K[route.tier] * (resp.input_tokens + resp.output_tokens) / 1000
            span.attributes.update({"gen_ai.usage.input_tokens": resp.input_tokens,
                                    "gen_ai.usage.output_tokens": resp.output_tokens,
                                    "consultai.cost_usd": cost})
            self.budget.record(tokens=resp.input_tokens + resp.output_tokens, cost_usd=cost)
            if resp.content is None:
                errors = ["output is not valid JSON"]
            else:
                errors = [f"{'/'.join(map(str, e.absolute_path)) or '$'}: {e.message}"
                          for e in Draft202012Validator(schema).iter_errors(resp.content)]
            if errors:
                span.attributes["consultai.schema_errors"] = errors[:5]
                self.log["failures"].append({"type": "invalid_schema", "task": task, "stage": stage,
                                             "errors": errors[:5]})
                return None, errors, resp.raw
            return (LLMResult(resp.content, resp.input_tokens, resp.output_tokens, cost,
                              route.model_env_key, route.provider, stage), [], resp.raw)

    def structured(self, *, agent: str, task: str, prompt: PromptTemplate | str,
                   schema: dict[str, Any], context: dict[str, Any],
                   variables: dict[str, Any] | None = None, risk_level: str = "low",
                   data_classification: str = "confidential") -> LLMResult:
        """Run a structured call. Order on malformed output: repair prompt (small model) ->
        fallback to the next-stronger model -> escalate to a human via SchemaEscalation."""
        if isinstance(prompt, str):
            system, user, prompt_id = "", prompt, "inline"
        else:
            system, user = prompt.render(**(variables or {}))
            prompt_id = prompt.id

        def route(task_name: str, tier: str | None = None) -> Route:
            return self.router.route(
                task_name, risk_level=risk_level, data_classification=data_classification,
                remaining_budget_usd=self.budget.max_cost_usd - self.budget.cost_usd,
                tier_override=tier)

        main = route(task)
        common = {"agent": agent, "task": task, "schema": schema, "context": context}
        result, errors, raw = self._attempt(**common, stage="initial", prompt_id=prompt_id,
                                            route=main, system=system, prompt=user)
        if result:
            return result

        # 1) repair: ask a small model to fix the malformed output against the schema
        rp = get_prompt("schema_repair")
        rsys, ruser = rp.render(errors="\n".join(errors), output=raw[:6000])
        result, errors, raw = self._attempt(
            **{**common, "task": "schema_repair"}, stage="repair", prompt_id=rp.id,
            route=route("schema_repair", "small"), system=rsys, prompt=ruser)
        if result:
            return result

        # 2) fallback: rerun the original prompt on the next-stronger tier
        result, errors, raw = self._attempt(**common, stage="fallback", prompt_id=prompt_id,
                                            route=route(task, _NEXT_TIER[main.tier]),
                                            system=system, prompt=user)
        if result:
            return result

        # 3) escalate
        self.log["failures"].append({"type": "schema_escalation", "task": task, "errors": errors[:5]})
        raise SchemaEscalation(f"{task}: output failed schema after repair and fallback: {errors[:3]}")
