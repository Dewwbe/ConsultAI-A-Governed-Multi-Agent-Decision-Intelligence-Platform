"""Strict tool contracts: schema, permissions, timeouts, risk, audit."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from jsonschema import Draft202012Validator

from app.tools import financial


@dataclass
class ToolContract:
    name: str
    description: str
    input_schema: dict[str, Any]
    fn: Callable[..., Any]
    risk_level: str = "low"
    timeout_ms: int = 3000
    max_retries: int = 1
    cost_usd: float = 0.0
    requires_approval: bool = False
    audit: bool = True
    _validator: Draft202012Validator = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._validator = Draft202012Validator(self.input_schema)

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
    return r
