"""Strict tool contracts: schema, permissions, timeouts, risk, audit."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from jsonschema import Draft202012Validator

from app.knowledge.risk_taxonomy import risk_lookup
from app.tools import financial

from .timeouts import ToolTimeouts


@dataclass
class ToolContract:
    name: str
    description: str
    input_schema: dict[str, Any]
    fn: Callable[..., Any]
    risk_level: str = "low"
    timeout_ms: int = 3000                 # the total limit
    connect_timeout_ms: int | None = None  # defaults to a fraction of the total (see timeouts())
    read_timeout_ms: int | None = None
    max_retries: int = 1
    cost_usd: float = 0.0
    requires_approval: bool = False
    audit: bool = True
    _validator: Draft202012Validator = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._validator = Draft202012Validator(self.input_schema)

    def timeouts(self) -> ToolTimeouts:
        total = self.timeout_ms
        connect = self.connect_timeout_ms if self.connect_timeout_ms is not None else max(1, total // 3)
        read = self.read_timeout_ms if self.read_timeout_ms is not None else total
        return ToolTimeouts(min(connect, total), min(read, total), total)

    def validate(self, args: dict[str, Any]) -> list[str]:
        return [e.message for e in self._validator.iter_errors(args)]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolContract] = {}

    def register(self, tool: ToolContract) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolContract:
        if name not in self._tools:
            raise KeyError(f"unknown tool '{name}'")
        return self._tools[name]

    def names(self) -> list[str]:
        return sorted(self._tools)


def _num(**extra: Any) -> dict[str, Any]:
    return {"type": "number", **extra}


def default_registry() -> ToolRegistry:
    r = ToolRegistry()
    r.register(ToolContract(
        "calculate_roi", "Return on investment over N years",
        {"type": "object", "required": ["investment", "annual_benefit", "years"],
         "properties": {"investment": _num(exclusiveMinimum=0), "annual_benefit": _num(),
                        "years": {"type": "integer", "minimum": 1}},
         "additionalProperties": False},
        financial.calculate_roi, risk_level="medium"))
    r.register(ToolContract(
        "calculate_npv", "Net present value of cashflows",
        {"type": "object", "required": ["rate", "cashflows"],
         "properties": {"rate": _num(), "cashflows": {"type": "array", "items": _num(), "minItems": 2}},
         "additionalProperties": False},
        financial.calculate_npv, risk_level="medium"))
    r.register(ToolContract(
        "calculate_payback", "Simple payback period",
        {"type": "object", "required": ["investment", "annual_benefit"],
         "properties": {"investment": _num(), "annual_benefit": _num()},
         "additionalProperties": False},
        financial.calculate_payback, risk_level="medium"))
    r.register(ToolContract(
        "scenario_analysis", "ROI under conservative/base/optimistic scenarios",
        {"type": "object", "required": ["investment", "annual_benefit", "years"],
         "properties": {"investment": _num(), "annual_benefit": _num(),
                        "years": {"type": "integer", "minimum": 1}, "scenarios": {"type": "object"}},
         "additionalProperties": False},
        financial.scenario_analysis, risk_level="medium"))
    r.register(ToolContract(
        "sensitivity_analysis", "ROI sensitivity to benefit changes",
        {"type": "object", "required": ["investment", "annual_benefit", "years"],
         "properties": {"investment": _num(), "annual_benefit": _num(),
                        "years": {"type": "integer", "minimum": 1}, "deltas": {"type": "array"}},
         "additionalProperties": False},
        financial.sensitivity_analysis, risk_level="medium"))
    r.register(ToolContract(
        "calculate_margin", "Operating margin = (revenue - cost) / revenue",
        {"type": "object", "required": ["revenue", "cost"],
         "properties": {"revenue": _num(), "cost": _num()}, "additionalProperties": False},
        financial.calculate_margin))
    r.register(ToolContract(
        "calculate_growth", "Period-on-period growth rate",
        {"type": "object", "required": ["previous", "current"],
         "properties": {"previous": _num(), "current": _num()}, "additionalProperties": False},
        financial.calculate_growth))
    r.register(ToolContract(
        "derive_annual_benefit", "Annual benefit = baseline revenue x uplift x margin",
        {"type": "object", "required": ["baseline_revenue", "uplift_pct", "margin"],
         "properties": {"baseline_revenue": _num(exclusiveMinimum=0),
                        "uplift_pct": _num(exclusiveMinimum=0, maximum=0.5),
                        "margin": _num(exclusiveMinimum=0, maximum=1)},
         "additionalProperties": False},
        financial.derive_annual_benefit, risk_level="medium"))
    r.register(ToolContract(
        "risk_lookup", "Risk taxonomy guidance and historical analogues",
        {"type": "object", "properties": {"query": {"type": "string"}, "category": {"type": "string"}},
         "additionalProperties": False},
        risk_lookup))
    return r
