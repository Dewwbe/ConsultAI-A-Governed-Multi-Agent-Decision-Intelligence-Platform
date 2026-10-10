"""Compare the evaluation scores with what partners actually decided.

    python backend/scripts/calibrate_judge.py                      # reads the configured database
    python backend/scripts/calibrate_judge.py decisions.jsonl      # or an export from export_decisions.py
    python backend/scripts/calibrate_judge.py --modify-as-approved --json

Prints, per score, how well it separates approved runs from the rest and what the policy's threshold does. It only
reports; changing a threshold is a policy edit (and a new policy version) that a person makes.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.config import get_settings
from app.control_plane.calibration import calibrate
from app.control_plane.policy import PolicyEngine
from app.persistence.db import Database


def load(source: str | None) -> list[dict]:
    if source:
        return [json.loads(line) for line in Path(source).read_text(encoding="utf-8").splitlines() if line.strip()]
    os.chdir(BACKEND)
    return Database(get_settings().database_url).decision_records()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", nargs="?", help="a JSON-lines file from export_decisions.py (default: the database)")
    ap.add_argument("--modify-as-approved", action="store_true", help="count 'modify' as an acceptance")
    ap.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = ap.parse_args()

    policy = PolicyEngine.from_file(get_settings().policy_file)
    report = calibrate(load(args.source), policy.thresholds, args.modify_as_approved)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
        return 0
    print(f"{report.decisions} decisions: {report.approved} approved, {report.not_approved} not approved")
    fmt = lambda v: "n/a" if v is None else f"{v:.2f}"
    for m in report.metrics:
        print(f"\n{m.metric}\n  AUC {fmt(m.auc)}   mean approved {fmt(m.mean_approved)} vs other {fmt(m.mean_not_approved)}"
              f"   best cut-off {fmt(m.best_threshold)} (balanced accuracy {fmt(m.best_balanced_accuracy)})")
        if m.policy_threshold is not None:
            print(f"  policy minimum {fmt(m.policy_threshold)}: lets through {fmt(m.false_accept_rate)} of rejected, "
                  f"blocks {fmt(m.false_block_rate)} of approved")
        print(f"  -> {m.verdict}")
    for note in report.notes:
        print(f"\nnote: {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
