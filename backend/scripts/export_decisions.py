"""Export the human-decision evaluation dataset (one JSON object per line).

    python backend/scripts/export_decisions.py > decisions.jsonl

Each record holds the recommendation, evaluation scores and Guardian decision the reviewer saw,
plus their decision, reason and edits. This is the ground truth for calibrating the LLM judge and,
later, for any fine-tuning decision.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

from app.config import get_settings
from app.persistence.db import Database


def main() -> int:
    records = Database(get_settings().database_url).decision_records()
    for r in records:
        print(json.dumps(r))
    print(f"{len(records)} decision record(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
