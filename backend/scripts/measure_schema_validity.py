"""Phase 1 exit check: run the UAE example N times and report schema validity per step.

    python -m scripts.measure_schema_validity --runs 20          # from backend/
    python backend/scripts/measure_schema_validity.py --runs 20  # from anywhere
    python -m scripts.measure_schema_validity --runs 20 --json out.json

Exit code is non-zero if any run escalated (output never became schema-valid).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

# Runnable from any folder: `python backend/scripts/measure_schema_validity.py --runs 20`.
# Run from backend/ so `.env` is found and `app` is importable.
BACKEND = Path(__file__).resolve().parents[1]
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

from app.workflow.service import EngagementService

UAE = {"business_problem": "Should we expand into the UAE market?", "industry": "Retail",
       "objectives": ["Increase revenue"], "constraints": ["Budget under $10M", "Launch within 18 months"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--json", help="write the full report to this path")
    args = ap.parse_args()

    svc = EngagementService()
    initial, stages, escalated, cost = Counter(), Counter(), 0, 0.0
    first_try_invalid: Counter = Counter()
    reasons: Counter = Counter()
    t0 = time.time()
    for i in range(1, args.runs + 1):
        out = svc.start(**UAE)
        print(f"run {i}/{args.runs}: {out['status']:18} cost ${out['budget']['cost_usd']:.4f} "
              f"elapsed {time.time() - t0:.0f}s", file=sys.stderr, flush=True)
        cost += out["budget"]["cost_usd"]
        if out["status"] == "escalated":
            escalated += 1
            reasons[out["halted_reason"]] += 1
        for s in svc.trace(out["workflow_id"])["spans"]:
            if s["kind"] == "llm":
                a = s["attributes"]
                stages[a["consultai.stage"]] += 1
                if a["consultai.stage"] == "initial":
                    initial[a["gen_ai.agent.name"]] += 1
        for f in svc_failures(out["workflow_id"]):
            if f.get("type") == "invalid_schema" and f.get("stage") == "initial":
                first_try_invalid[f["task"]] += 1

    total_initial = sum(initial.values())
    report = {
        "provider": svc.settings.llm_provider, "runs": args.runs, "escalated_runs": escalated, "escalation_reasons": dict(reasons),
        "structured_calls": total_initial,
        "invalid_schema_rate": round(sum(first_try_invalid.values()) / max(1, total_initial), 4),
        "invalid_by_task": dict(first_try_invalid), "attempts_by_stage": dict(stages),
        "avg_cost_usd": round(cost / args.runs, 4),
    }
    print(json.dumps(report, indent=2))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
    return 1 if escalated else 0


def svc_failures(wid: str) -> list[dict]:
    from app.workflow.graph import RUNTIMES
    return RUNTIMES[wid].log["failures"]


if __name__ == "__main__":
    raise SystemExit(main())
