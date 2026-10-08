"""Aggregate stored per-run metrics into the views the Control Center needs.

Pure functions over plain rows, so they are easy to test with hand-made data. Metrics are grouped as
the plan names them: intent, tool, safety, business, economics.
"""
from __future__ import annotations

import datetime as dt
import statistics
from collections import defaultdict
from typing import Any

SCORE_METRICS = ("groundedness", "citation_validity", "task_adherence", "contradiction_free",
                 "tool_call_accuracy", "constraint_satisfaction", "completeness", "quality")
TIMESERIES_METRICS = ("runs", "cost_usd", "tokens", "duration_sec", "success_rate", "escalation_rate", *SCORE_METRICS)


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return round(ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo), 4)


def _score(row: dict[str, Any], name: str) -> float | None:
    v = row["scores"].get(name)
    return float(v) if isinstance(v, (int, float)) else None


def _scores(rows: list[dict[str, Any]], name: str) -> list[float]:
    return [v for r in rows if (v := _score(r, name)) is not None]


def _rate(num: float, den: float) -> float | None:
    return round(num / den, 4) if den else None


def summarize(rows: list[dict[str, Any]], thresholds: dict[str, float]) -> dict[str, Any]:
    n = len(rows)
    decided = [r for r in rows if r["approval_decision"]]
    successful = [r for r in rows if r["successful"]]
    tool_calls = sum(r["tool_calls"] for r in rows)
    llm_calls = sum(r["llm_calls"] for r in rows)
    total_cost = sum(r["cost_usd"] for r in rows)
    by_status: dict[str, int] = defaultdict(int)
    for r in rows:
        by_status[r["status"]] += 1

    by_agent: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    by_model: dict[str, dict[str, Any]] = {}
    for r in rows:
        for a in r["cost_by_agent"]:
            for f in ("calls", "input_tokens", "output_tokens", "cost_usd"):
                by_agent[a["agent"]][f] += a[f]
        for m in r["cost_by_model"]:
            cur = by_model.setdefault(m["model"], {"model": m["model"], "tier": m["tier"], "calls": 0,
                                                   "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
            for f in ("calls", "input_tokens", "output_tokens", "cost_usd"):
                cur[f] += m[f]

    summary = {
        "runs": n,
        "by_status": dict(by_status),
        "intent": {
            "task_adherence": _avg(_scores(rows, "task_adherence")),
            "constraint_satisfaction": _avg(_scores(rows, "constraint_satisfaction")),
            "completeness": _avg(_scores(rows, "completeness")),
        },
        "tool": {
            "tool_calls": tool_calls,
            "tool_call_success_rate": _rate(tool_calls - sum(r["tool_errors"] for r in rows), tool_calls),
            "tool_call_accuracy": _avg(_scores(rows, "tool_call_accuracy")),
            "invalid_schema_rate": _avg([r["invalid_schema_rate"] for r in rows]),
            "llm_repair_rate": _rate(sum(r["llm_repairs"] for r in rows), llm_calls),
            "llm_fallback_rate": _rate(sum(r["llm_fallbacks"] for r in rows), llm_calls),
            "schema_escalations": sum(r["schema_escalations"] for r in rows),
        },
        "safety": {
            "groundedness": _avg(_scores(rows, "groundedness")),
            "contradiction_free": _avg(_scores(rows, "contradiction_free")),
            "escalation_rate": _rate(sum(1 for r in rows if r["escalated"] or r["escalations"]), n),
            "unauthorized_action_rate": _rate(sum(r["blocked_actions"] for r in rows),
                                              sum(r["guardian_decisions"] for r in rows)),
            "runs_halted": by_status.get("escalated", 0),
        },
        "business": {
            "decided": len(decided),
            "approval_rate": _rate(sum(1 for r in decided if r["approval_decision"] == "approve"), len(decided)),
            "modification_rate": _rate(sum(1 for r in decided if r["approval_decision"] == "modify"), len(decided)),
            "rejection_rate": _rate(sum(1 for r in decided if r["approval_decision"] == "reject"), len(decided)),
            "awaiting_approval": by_status.get("awaiting_approval", 0),
            "median_decision_seconds": (round(statistics.median([r["decision_seconds"] for r in decided
                                                                 if r["decision_seconds"] is not None]), 2)
                                        if any(r["decision_seconds"] is not None for r in decided) else None),
        },
        "economics": {
            "total_cost_usd": round(total_cost, 6),
            "avg_cost_usd": _avg([r["cost_usd"] for r in rows]),
            "successful_runs": len(successful),
            "success_rate": _rate(len(successful), n),
            "cost_per_successful_task": round(total_cost / len(successful), 6) if successful else None,
            "avg_tokens": _avg([r["input_tokens"] + r["output_tokens"] for r in rows]),
            "p50_duration_sec": _pct([r["duration_sec"] for r in rows], 0.5),
            "p95_duration_sec": _pct([r["duration_sec"] for r in rows], 0.95),
            "cost_by_agent": [{"agent": k, "calls": int(v["calls"]), "input_tokens": int(v["input_tokens"]),
                               "output_tokens": int(v["output_tokens"]), "cost_usd": round(v["cost_usd"], 6)}
                              for k, v in sorted(by_agent.items())],
            "cost_by_model": [{**m, "cost_usd": round(m["cost_usd"], 6)} for m in sorted(by_model.values(), key=lambda x: x["model"])],
        },
    }
    summary["flags"] = quality_flags(summary, thresholds)
    return summary


def quality_flags(summary: dict[str, Any], thresholds: dict[str, float]) -> list[dict[str, Any]]:
    """Plain-language warnings when an average has slipped below policy. Empty list = healthy (or no data)."""
    checks = [
        ("groundedness", summary["safety"]["groundedness"], thresholds.get("min_groundedness", 0.75)),
        ("tool_call_accuracy", summary["tool"]["tool_call_accuracy"], thresholds.get("min_tool_call_accuracy", 0.9)),
        ("contradiction_free", summary["safety"]["contradiction_free"], thresholds.get("min_contradiction_free", 0.75)),
        ("constraint_satisfaction", summary["intent"]["constraint_satisfaction"], thresholds.get("min_constraint_satisfaction", 0.9)),
        ("task_adherence", summary["intent"]["task_adherence"], thresholds.get("min_task_adherence", 0.7)),
    ]
    return [{"metric": name, "value": value, "threshold": limit,
             "message": f"Average {name.replace('_', ' ')} {value:.2f} is below the policy minimum {limit:.2f}"}
            for name, value, limit in checks if value is not None and value < limit]


def _bucket(ts: str, bucket: str) -> str:
    d = dt.datetime.fromisoformat(ts)
    d = d.replace(minute=0, second=0, microsecond=0)
    if bucket == "day":
        d = d.replace(hour=0)
    return d.isoformat()


def timeseries(rows: list[dict[str, Any]], metric: str, bucket: str = "day") -> list[dict[str, Any]]:
    """One point per bucket. Counts and costs are summed; scores and rates are averaged."""
    if metric not in TIMESERIES_METRICS:
        raise ValueError(f"unknown metric '{metric}'; choose from {list(TIMESERIES_METRICS)}")
    if bucket not in {"hour", "day"}:
        raise ValueError("bucket must be 'hour' or 'day'")
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[_bucket(r["created_at"], bucket)].append(r)
    points = []
    for t in sorted(groups):
        g = groups[t]
        if metric == "runs":
            value: float | None = float(len(g))
        elif metric in {"cost_usd", "duration_sec"}:
            value = round(sum(r[metric] for r in g), 6)
        elif metric == "tokens":
            value = float(sum(r["input_tokens"] + r["output_tokens"] for r in g))
        elif metric == "success_rate":
            value = _rate(sum(1 for r in g if r["successful"]), len(g))
        elif metric == "escalation_rate":
            value = _rate(sum(1 for r in g if r["escalated"] or r["escalations"]), len(g))
        else:
            value = _avg(_scores(g, metric))
        points.append({"t": t, "value": value, "n": len(g)})
    return points
