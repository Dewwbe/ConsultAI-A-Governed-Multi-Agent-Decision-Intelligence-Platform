"""Single choke point for tool execution: guardian -> schema -> budget -> trace -> run."""
from __future__ import annotations

from typing import Any

from app.observability.payload import cap_payload
from app.observability.tracing import TraceStore

from .budget import Budget
from .guardian import Guardian
from .reliability import CircuitBreaker, call_with_retry
from .timeouts import ToolTimeoutError, run_with_timeouts
from .tool_registry import ToolRegistry


class ToolBlocked(Exception):
    def __init__(self, decision: dict[str, Any]):
        super().__init__("; ".join(decision["reasons"]))
        self.decision = decision


class ToolArgsInvalid(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, guardian: Guardian, budget: Budget,
                 trace: TraceStore, state_log: dict[str, list]):
        self.registry, self.guardian, self.budget, self.trace = registry, guardian, budget, trace
        self.log = state_log  # shared lists: guardian_decisions, failures
        self._breakers: dict[str, CircuitBreaker] = {}

    def call(self, agent: str, tool: str, args: dict[str, Any], resource: str | None = None) -> Any:
        """guardian -> schema -> budget -> run, with one span for every attempt, including refused ones,
        so the Control Center can show what was asked, what the Guardian decided and why it failed."""
        contract = self.registry.get(tool)
        with self.trace.span(f"tool:{tool}", "tool", **{
                "gen_ai.agent.name": agent, "gen_ai.tool.name": tool,
                "consultai.tool_arguments": cap_payload(args), "consultai.risk_level": contract.risk_level,
                "consultai.timeout_ms": contract.timeout_ms, "consultai.cost_usd": 0.0}) as span:
            decision = self.guardian.review_tool_call(agent, tool, args, resource)
            self.log["guardian_decisions"].append(decision.to_dict())
            span.attributes["consultai.guardian"] = decision.to_dict()
            if decision.action != "ALLOW":
                span.attributes["consultai.outcome"] = "blocked"
                raise ToolBlocked(decision.to_dict())

            errors = contract.validate(args)
            if errors:
                span.attributes.update({"consultai.outcome": "invalid_arguments", "consultai.schema_errors": errors})
                self.log["failures"].append({"type": "invalid_schema", "tool": tool, "errors": errors})
                raise ToolArgsInvalid(errors)

            self.budget.record(tool_calls=1, cost_usd=contract.cost_usd)
            span.attributes["consultai.cost_usd"] = contract.cost_usd
            breaker = self._breakers.setdefault(tool, CircuitBreaker())
            attempts = 0

            # a tool may not outlive the workflow: its limits are capped by the time left before the deadline
            self.budget.check()
            limits = contract.timeouts().capped(self.budget.remaining_sec())
            span.attributes["consultai.timeouts_ms"] = {"connect": limits.connect_ms, "read": limits.read_ms,
                                                        "total": limits.total_ms}

            def run() -> Any:
                nonlocal attempts
                attempts += 1
                return run_with_timeouts(contract.fn, args, limits)

            try:
                result = call_with_retry(run, max_attempts=1 + contract.max_retries, breaker=breaker)
            except ToolTimeoutError:
                span.attributes["consultai.outcome"] = "timeout"
                self.log["failures"].append({"type": "tool_timeout", "tool": tool, "limit_ms": limits.total_ms,
                                             "attempts": attempts})
                raise
            finally:
                span.attributes["consultai.attempts"] = attempts
            span.attributes["consultai.outcome"] = "ok"
            span.attributes["consultai.tool_result"] = cap_payload(result)
            return result
