"""Per-run metrics, computed once when a run pauses or ends and stored for aggregation.

"Successful" is deliberately stricter than "completed": success = outcome + evidence + safety, so a
run that finished by producing an ungrounded or constraint-breaking recommendation does not count.
That is what makes `cost_per_successful_task` an honest number rather than a vanity one.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

APPROVED = {"approved", "modified", "not_required"}


def _intervals_union(spans: list[dict[str, Any]]) -> float:
    """Seconds of active work: the union of top-level span intervals, so parallel steps and the
    time spent waiting for a human are not double counted or counted at all."""
    spans = sorted(((s["start"], s["start"] + s["latency_ms"] / 1000) for s in spans), key=lambda x: x[0])
    total, cur_start, cur_end = 0.0, None, None
    for start, end in spans:
        if cur_end is None or start > cur_end:
            if cur_end is not None and cur_start is not None:
                total += cur_end - cur_start
            cur_start, cur_end = start, end
        else:
            cur_end = max(cur_end, end)
    if cur_end is not None and cur_start is not None:
        total += cur_end - cur_start
    return total


def breakdown(spans: list[dict[str, Any]]) -> dict[str, Any]:
    """Cost and tokens by agent and by model tier, from the LLM spans."""
    by_agent: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    by_model: dict[str, dict[str, Any]] = {}
    for s in spans:
        if s["kind"] != "llm":
            continue
        a = s["attributes"]
        agent = a.get("gen_ai.agent.name", "unknown")
        row = by_agent[agent]
        row["calls"] += 1
        row["input_tokens"] += a.get("gen_ai.usage.input_tokens", 0)
        row["output_tokens"] += a.get("gen_ai.usage.output_tokens", 0)
        row["cost_usd"] += a.get("consultai.cost_usd", 0.0)
        key = a.get("gen_ai.request.model", "unknown")
        m = by_model.setdefault(key, {"model": key, "tier": a.get("consultai.tier", ""), "calls": 0,
                                      "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
        m["calls"] += 1
        m["input_tokens"] += a.get("gen_ai.usage.input_tokens", 0)
        m["output_tokens"] += a.get("gen_ai.usage.output_tokens", 0)
        m["cost_usd"] += a.get("consultai.cost_usd", 0.0)
    return {
        "by_agent": [{"agent": k, **{f: (int(v[f]) if f != "cost_usd" else round(v[f], 6)) for f in
                                      ("calls", "input_tokens", "output_tokens", "cost_usd")}}
                     for k, v in sorted(by_agent.items())],
        "by_model": [{**m, "cost_usd": round(m["cost_usd"], 6)} for m in sorted(by_model.values(), key=lambda x: x["model"])],
    }


def is_successful(status: str, state: dict[str, Any], scores: dict[str, float], thresholds: dict[str, float],
                  blocked: int) -> bool:
    """Outcome (finished, approved or not needed, constraints met) AND evidence (grounded) AND safety (nothing blocked)."""
    if status != "completed" or state.get("approval_status") not in APPROVED:
        return False
    return (
        scores.get("constraint_satisfaction", 0.0) >= thresholds.get("min_constraint_satisfaction", 0.9)
        and scores.get("groundedness", 0.0) >= thresholds.get("min_groundedness", 0.75)
        and scores.get("contradiction_free", 1.0) >= thresholds.get("min_contradiction_free", 0.75)
        and scores.get("judge_coverage", 1.0) >= 1.0
        and blocked == 0
    )


def compute_run_metrics(*, row: dict[str, Any], status: str, state: dict[str, Any], trace: dict[str, Any],
                        engagement_metrics: dict[str, Any], guardian_decisions: list[dict[str, Any]],
                        failures: list[dict[str, Any]], thresholds: dict[str, float]) -> dict[str, Any]:
    spans = trace["spans"]
    scores = {k: float(v) for k, v in (state.get("evaluation_scores") or {}).items() if isinstance(v, (int, float))}
    blocked = sum(1 for d in guardian_decisions if d.get("action") == "BLOCK")
    top_level = [s for s in spans if s["kind"] in {"agent", "evaluator", "guardian"}]
    llm = [s for s in spans if s["kind"] == "llm"]
    stages = [s["attributes"].get("consultai.stage") for s in llm]
    bd = breakdown(spans)
    return {
        "workflow_id": row["workflow_id"],
        "created_at": row["created_at"],
        "user_id": row["user_id"],
        "status": status,
        "data_classification": row["data_classification"],
        "risk_level": state.get("risk_level"),
        "duration_sec": round(_intervals_union(top_level), 3),
        "cost_usd": round(trace["cost_usd"], 6),
        "input_tokens": trace["input_tokens"],
        "output_tokens": trace["output_tokens"],
        "tool_calls": trace["tool_calls"],
        "tool_errors": trace["tool_errors"],
        "llm_calls": stages.count("initial"),
        "llm_repairs": stages.count("repair"),
        "llm_fallbacks": stages.count("fallback"),
        "schema_escalations": engagement_metrics.get("schema_escalations", 0),
        "invalid_schema_rate": engagement_metrics.get("invalid_schema_rate", 0.0),
        "guardian_decisions": len(guardian_decisions),
        "blocked_actions": blocked,
        "escalations": sum(1 for d in guardian_decisions if d.get("action") == "ESCALATE"),
        "retries": state.get("retry_count", 0),
        "escalated": status == "escalated",
        "scores": scores,
        "cost_by_agent": bd["by_agent"],
        "cost_by_model": bd["by_model"],
        "successful": is_successful(status, state, scores, thresholds, blocked),
        "approval_decision": None,
        "decision_seconds": None,
        "failures": len(failures),
    }
