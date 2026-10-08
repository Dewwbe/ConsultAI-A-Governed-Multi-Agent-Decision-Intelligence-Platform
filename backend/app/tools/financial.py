"""Deterministic financial tools. The LLM chooses which to call; Python computes."""
from __future__ import annotations

from collections.abc import Sequence


def calculate_roi(investment: float, annual_benefit: float, years: int) -> dict:
    if investment <= 0 or years <= 0:
        raise ValueError("investment and years must be positive")
    total_benefit = annual_benefit * years
    roi = (total_benefit - investment) / investment
    return {"roi": roi, "total_benefit": total_benefit, "net_gain": total_benefit - investment}


def calculate_npv(rate: float, cashflows: Sequence[float]) -> dict:
    """cashflows[0] occurs at t=0 (typically negative)."""
    if rate <= -1:
        raise ValueError("rate must be > -1")
    npv = sum(cf / (1 + rate) ** t for t, cf in enumerate(cashflows))
    return {"npv": npv, "rate": rate, "periods": len(cashflows)}


def calculate_payback(investment: float, annual_benefit: float) -> dict:
    if annual_benefit <= 0:
        return {"payback_years": None, "reason": "no positive annual benefit"}
    return {"payback_years": investment / annual_benefit}


def calculate_margin(revenue: float, cost: float) -> dict:
    if revenue == 0:
        raise ValueError("revenue must be non-zero")
    return {"margin": (revenue - cost) / revenue}


def calculate_growth(previous: float, current: float) -> dict:
    if previous == 0:
        raise ValueError("previous must be non-zero")
    return {"growth": (current - previous) / previous}


def scenario_analysis(investment: float, annual_benefit: float, years: int,
                      scenarios: dict[str, float] | None = None) -> dict:
    """Benefit multipliers per scenario; defaults to conservative/base/optimistic."""
    scenarios = scenarios or {"conservative": 0.7, "base": 1.0, "optimistic": 1.2}
    return {name: calculate_roi(investment, annual_benefit * m, years)["roi"]
            for name, m in scenarios.items()}


def sensitivity_analysis(investment: float, annual_benefit: float, years: int,
                         deltas: Sequence[float] = (-0.2, -0.1, 0.0, 0.1, 0.2)) -> list[dict]:
    return [{"benefit_delta": d,
             "roi": calculate_roi(investment, annual_benefit * (1 + d), years)["roi"]}
            for d in deltas]
