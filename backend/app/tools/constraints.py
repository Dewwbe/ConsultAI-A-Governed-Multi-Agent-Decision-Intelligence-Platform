"""Deterministic parsing and checking of client constraints, shared by the Solution Agent and the
evaluator so both judge options by exactly the same rules.

Understands: a spending ceiling ("Budget under $10M", "Investment cap of 500K") and a time limit
("Launch within 18 months", "Go live in under 2 years"). Anything else is returned as `unparsed`,
and callers must surface it as an unchecked assumption rather than silently ignore it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_UNITS = {"": 1.0, "k": 1e3, "thousand": 1e3, "m": 1e6, "mm": 1e6, "million": 1e6, "b": 1e9, "billion": 1e9}
_MONEY = re.compile(r"(?:\$|usd\s*)\s*(\d[\d,]*(?:\.\d+)?)\s*(thousand|million|billion|mm|k|m|b)?\b"
                    r"|\b(\d[\d,]*(?:\.\d+)?)\s*(thousand|million|billion|mm|k|m|b)\b", re.IGNORECASE)
_SPEND_WORD = re.compile(r"\b(budget|spend|spending|invest\w*|cost|capex|capital|cap|ceiling)\b", re.IGNORECASE)
_TIME = re.compile(r"\b(?:within|in|under|inside|before|by)\s+(?:the\s+next\s+)?(\d+(?:\.\d+)?)\s*"
                   r"(day|week|month|year)s?\b", re.IGNORECASE)
_MONTHS_PER = {"day": 1 / 30, "week": 12 / 52, "month": 1.0, "year": 12.0}


@dataclass
class ParsedConstraints:
    max_investment: float | None = None
    max_months: float | None = None
    unparsed: list[str] = field(default_factory=list)


def _money(text: str) -> float | None:
    m = _MONEY.search(text)
    if not m:
        return None
    number, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
    return float(number.replace(",", "")) * _UNITS[(unit or "").lower()]


def parse_constraints(constraints: list[str]) -> ParsedConstraints:
    out = ParsedConstraints()
    for c in constraints:
        amount = _money(c) if _SPEND_WORD.search(c) else None
        t = _TIME.search(c)
        matched = False
        if amount is not None:
            # several ceilings: the tightest one governs
            out.max_investment = amount if out.max_investment is None else min(out.max_investment, amount)
            matched = True
        if t and amount is None:
            months = float(t.group(1)) * _MONTHS_PER[t.group(2).lower()]
            out.max_months = months if out.max_months is None else min(out.max_months, months)
            matched = True
        if not matched:
            out.unparsed.append(c)
    return out


def violations(option: dict, parsed: ParsedConstraints) -> list[str]:
    """Human-readable reasons an option breaks a parsed constraint (empty = satisfies all)."""
    out = []
    if parsed.max_investment is not None and option.get("cost_usd", 0) > parsed.max_investment:
        out.append(f"investment ${option['cost_usd']:,.0f} exceeds ceiling ${parsed.max_investment:,.0f}")
    months = option.get("launch_months")
    if parsed.max_months is not None and months is not None and months > parsed.max_months:
        out.append(f"launch in {months:g} months exceeds limit of {parsed.max_months:g} months")
    return out
