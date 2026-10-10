"""Record the frontend's mock-API fixtures from a real run of this backend.

    python backend/scripts/record_fixtures.py frontend/src/mocks/fixtures

The UI tests (and demo mode) serve these files, so they are the real contract: when an endpoint or
model changes, re-run this and `npm run api:update`, and the tests show exactly what the UI must
adapt to. Uses the offline stub provider and an in-memory database; nothing external is touched.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
OUT = Path(sys.argv[1]).resolve() if len(sys.argv) == 2 else None  # resolve before chdir
os.environ.update(CONSULTAI_IGNORE_DOTENV="1", LLM_PROVIDER="stub", DATABASE_URL="sqlite:///:memory:", AUTH_MODE="dev", ENVIRONMENT="dev")
os.chdir(BACKEND)
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient

from app.main import app

PARTNER = {"X-Dev-User": "pat", "X-Dev-Roles": "Partner"}
ADMIN = {"X-Dev-User": "ada", "X-Dev-Roles": "Admin"}
UAE = {"business_problem": "Should we expand into the UAE market?", "industry": "Retail",
       "objectives": ["Increase revenue"], "constraints": ["Budget under $10M", "Launch within 18 months"]}


def main() -> int:
    if OUT is None:
        print("usage: record_fixtures.py <output-dir>", file=sys.stderr)
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    c = TestClient(app)
    get = lambda path, **kw: c.get(path, headers=PARTNER, **kw).json()

    # A completed run, a rejected run, and one awaiting approval (the one most tests open).
    done = c.post("/engagements", json=UAE, headers=PARTNER).json()["workflow_id"]
    completed = c.post(f"/engagements/{done}/approval", json={"decision": "approve", "reason": "ok"}, headers=PARTNER).json()
    rej = c.post("/engagements", json={**UAE, "constraints": ["Budget under $1M"]}, headers=PARTNER).json()["workflow_id"]
    c.post(f"/engagements/{rej}/approval", json={"decision": "reject", "reason": "no option fits"}, headers=PARTNER)
    wid = c.post("/engagements", json=UAE, headers=PARTNER).json()["workflow_id"]

    files = {
        "detail": get(f"/engagements/{wid}"),
        "completed": completed,
        "evidence": get(f"/engagements/{wid}/evidence"),
        "tables": get(f"/engagements/{wid}/tables"),
        "trace": get(f"/control-center/{wid}/trace"),
        "guardian": get(f"/engagements/{wid}/guardian"),
        "cost": get(f"/engagements/{wid}/cost"),
        "summary": get("/metrics/summary"),
        "timeseries": get("/metrics/timeseries", params={"metric": "cost_usd"}),
        "list": get("/engagements"),
    }
    # Governance views are for Admins and Auditors only.
    for name, path in {"policy": "/governance/policy", "policy_versions": "/governance/policy/versions",
                       "tools": "/governance/tools", "providers": "/governance/providers",
                       "budgets": "/governance/budgets", "degradation": "/governance/degradation"}.items():
        files[name] = c.get(path, headers=ADMIN).json()
    first_version = files["policy_versions"][0]["version"]
    files["policy_version"] = c.get(f"/governance/policy/versions/{first_version}", headers=ADMIN).json()
    with c.stream("GET", f"/engagements/{wid}/events", headers=PARTNER) as r:
        sse = "".join(r.iter_text())
    for name, data in files.items():
        (OUT / f"{name}.json").write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
    (OUT / "events.sse.txt").write_text(sse, encoding="utf-8")
    print(f"recorded {len(files) + 1} fixtures in {OUT} (open run {wid})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
