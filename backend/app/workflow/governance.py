"""Read-only views of how the control plane is configured and how healthy it is: the policy in force and its
history, the tool registry, provider and circuit-breaker health, budgets, and quality-degradation events.
Nothing here changes anything; it exists so an administrator can answer "what rules govern this, and are
they holding?" without reading code.
"""
from __future__ import annotations

import time
from typing import Any

from app.control_plane.router import PRICE_PER_1K
from app.workflow.graph import RUNTIMES

NEAR_LIMIT = 0.8
CLASSIFICATIONS = ("confidential", "internal", "public")


def policy_view(svc: Any) -> dict[str, Any]:
    raw = svc.policy.as_dict()
    agents = [{"name": name, "allowed_tools": spec.get("allowed_tools", []), "blocked_tools": spec.get("blocked_tools", []),
               "requires_approval": spec.get("requires_approval", []), "allowed_tables": spec.get("allowed_tables", [])}
              for name, spec in raw.get("agents", {}).items()]
    return {
        "version": svc.policy.version, "sha256": svc.policy.sha256, "agents": agents,
        "thresholds": {k: float(v) for k, v in raw.get("thresholds", {}).items()},
        "risk_tiers": raw.get("risk_tiers", {}),
        "data_classification": {k: v.get("allowed_providers", []) for k, v in raw.get("data_classification", {}).items()},
        "pii": raw.get("pii", {}), "rbac": raw.get("rbac", {}), "limits": raw.get("limits", {}),
        "degradation": raw.get("degradation", {}), "timeouts_sec": raw.get("timeouts_sec", {}),
    }


def tools_view(svc: Any) -> list[dict[str, Any]]:
    agents = svc.policy.as_dict().get("agents", {})
    out = []
    for name in svc.registry.names():
        c = svc.registry.get(name)
        t = c.timeouts()
        out.append({
            "name": name, "description": c.description, "input_schema": c.input_schema, "risk_level": c.risk_level,
            "timeouts": {"connect_ms": t.connect_ms, "read_ms": t.read_ms, "total_ms": t.total_ms},
            "max_retries": c.max_retries, "cost_usd": c.cost_usd, "audit": c.audit,
            "requires_approval": c.requires_approval or any(name in a.get("requires_approval", []) for a in agents.values()),
            "allowed_agents": sorted(a for a, s in agents.items() if name in s.get("allowed_tools", [])),
            "blocked_agents": sorted(a for a, s in agents.items() if name in s.get("blocked_tools", []))})
    return out


def providers_view(svc: Any) -> dict[str, Any]:
    policy = svc.policy.as_dict()
    primary = svc._provider().name
    configured = [primary, *[n for n in svc.extra_providers if n != primary]]
    known = list(dict.fromkeys([*configured, *(p for v in policy.get("data_classification", {}).values()
                                              for p in v.get("allowed_providers", []))]))
    breakers = {b["provider"]: b for b in svc.breakers.snapshot(known)}
    limits = {n: svc.limiters.for_provider(n).snapshot() for n in configured}
    s = svc.settings
    deployments = {"small": s.model_small, "medium": s.model_medium, "reasoning": s.model_reasoning}
    return {
        "providers": [{
            "name": n, "configured": n in configured, "primary": n == primary,
            "allowed_classifications": [c for c in CLASSIFICATIONS if svc.policy.provider_allowed(c, n)],
            "breaker": breakers[n], "limits": limits.get(n)} for n in known],
        "routing": [{"tier": t, "deployment": deployments[t] or "(stub or not set)", "price_per_1k_usd": PRICE_PER_1K[t]}
                    for t in ("small", "medium", "reasoning")],
        "fallbacks": svc.fallbacks.recent(50)[::-1],
        "scheduler": svc.scheduler.snapshot(),
    }


def _use(workflow_id: str, status: str, tokens: float, cost: float, tools: float, duration: float, s: Any) -> dict[str, Any]:
    ratios = {"tokens": tokens / s.max_tokens, "cost_usd": cost / s.max_cost_usd, "tool_calls": tools / s.max_tool_calls,
              "duration_sec": duration / s.max_duration_sec}
    worst = max(ratios, key=lambda k: ratios[k])
    return {"workflow_id": workflow_id, "status": status, "tokens": int(tokens), "cost_usd": round(cost, 6),
            "tool_calls": int(tools), "duration_sec": round(duration, 1), "utilization": round(ratios[worst], 4),
            "tightest": worst, "near_limit": ratios[worst] >= NEAR_LIMIT}


def budgets_view(svc: Any) -> dict[str, Any]:
    s = svc.settings
    running = []
    rows, _ = svc.db.list_engagements("running", 100, 0)
    for r in rows:
        ctx = RUNTIMES.get(r["workflow_id"])
        if ctx:
            b = ctx.budget
            running.append(_use(r["workflow_id"], "running", b.tokens, b.cost_usd, b.tool_calls,
                                time.monotonic() - b.started, s))
    recent = [_use(m["workflow_id"], m["status"], m["input_tokens"] + m["output_tokens"], m["cost_usd"], m["tool_calls"],
                   m["duration_sec"], s) for m in svc.db.run_metrics_rows()[-20:][::-1]]
    return {"defaults": {"max_tokens": s.max_tokens, "max_cost_usd": s.max_cost_usd,
                         "max_duration_sec": s.max_duration_sec, "max_tool_calls": s.max_tool_calls},
            "running": running, "recent": recent, "near_limit_count": sum(1 for u in [*running, *recent] if u["near_limit"])}


def degradation_view(svc: Any) -> dict[str, Any]:
    return {"state": svc.degradation.to_dict(), "events": svc.db.degradation_events_list(50)}
