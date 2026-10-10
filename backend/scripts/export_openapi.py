"""Write the API's OpenAPI schema to a file (used to generate the frontend's TypeScript client).

    python backend/scripts/export_openapi.py frontend/openapi.json

Runs against throw-away settings (stub provider, in-memory database) so it never needs credentials
or leaves files behind.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
OUTPUT = Path(sys.argv[1]).resolve() if len(sys.argv) == 2 else None  # resolve before chdir
os.environ["CONSULTAI_IGNORE_DOTENV"] = "1"  # never reach a live service from backend/.env
os.environ["LLM_PROVIDER"] = "stub"
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
os.environ["AUTH_MODE"] = "dev"
os.environ["ENVIRONMENT"] = "dev"
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

from app.main import app


def main() -> int:
    if OUTPUT is None:
        print("usage: export_openapi.py <output.json>", file=sys.stderr)
        return 2
    OUTPUT.write_text(json.dumps(app.openapi(), indent=1) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
