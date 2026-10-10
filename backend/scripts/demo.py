"""Run the whole platform offline with realistic seeded data, in one command.

    python backend/scripts/demo.py            # API on :8010, UI on :5173
    python backend/scripts/demo.py --no-ui    # API and seed data only
    python backend/scripts/demo.py --port 8020

It starts the API on the offline stub provider with a fresh database (so nothing external is touched
and nothing from earlier sessions leaks in), seeds a handful of engagements in different states, then
starts the UI. Open http://localhost:5173, pick an identity (Partner to approve, Admin to see
Governance) and submit "Should we expand into the UAE?" to watch a run happen live. Ctrl+C stops it all.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parents[1]
FRONTEND = BACKEND.parent / "frontend"
PARTNER = {"X-Dev-User": "pat", "X-Dev-Roles": "Partner"}
UAE = {"business_problem": "Should we expand into the UAE market?", "industry": "Retail",
       "objectives": ["Increase revenue"], "constraints": ["Budget under $10M", "Launch within 18 months"]}

# (question, constraints, what a partner then does) - a mix of finished and waiting work.
SEED = [
    (UAE, "approve", "Numbers and sources check out; proceed with the phased entry."),
    ({**UAE, "business_problem": "Should we open a second distribution centre?", "industry": "Logistics"}, "reject",
     "The payback period is too long for this year's budget."),
    ({**UAE, "business_problem": "Should we acquire a regional competitor?", "industry": "Retail"}, "modify",
     "Lower the growth assumption until the diligence results are in."),
    (UAE, None, ""),
    ({**UAE, "business_problem": "Should we enter the Saudi market next year?"}, None, ""),
]


def wait_for(url: str, proc: subprocess.Popen, seconds: float = 60) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise SystemExit("the API stopped while starting; see its output above")
        try:
            if httpx.get(url, timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.4)
    raise SystemExit(f"{url} did not come up in {seconds:.0f}s")


def seed(base: str) -> int:
    made = 0
    with httpx.Client(base_url=base, headers=PARTNER, timeout=60) as c:
        for body, decision, reason in SEED:
            run = c.post("/engagements", json=body)
            run.raise_for_status()
            wid = run.json()["workflow_id"]
            made += 1
            if decision is None:
                continue
            payload: dict = {"decision": decision, "reason": reason}
            if decision == "modify":
                payload["changes"] = {"rationale": "Growth assumption lowered pending diligence."}
            r = c.post(f"/engagements/{wid}/approval", json=payload)
            if r.status_code >= 400:  # a run the Guardian let through needs no decision: that is fine
                print(f"  note: {wid} could not be {decision}d ({r.json().get('detail')})")
    return made


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8010)
    ap.add_argument("--ui-port", type=int, default=5173)
    ap.add_argument("--no-ui", action="store_true")
    args = ap.parse_args()

    base = f"http://localhost:{args.port}"
    db = BACKEND / "demo.db"
    for suffix in ("", "-wal", "-shm"):
        Path(f"{db}{suffix}").unlink(missing_ok=True)
    env = {**os.environ, "CONSULTAI_IGNORE_DOTENV": "1", "LLM_PROVIDER": "stub", "AUTH_MODE": "dev", "ENVIRONMENT": "dev",
           "DATABASE_URL": f"sqlite:///{db.as_posix()}",
           "CORS_ORIGINS": f"http://localhost:{args.ui_port},http://127.0.0.1:{args.ui_port}"}
    procs: list[subprocess.Popen] = []
    try:
        print(f"Starting the API on {base} (offline stub models, fresh database) ...")
        api = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(args.port)],
                               cwd=BACKEND, env=env)
        procs.append(api)
        wait_for(f"{base}/health", api)
        print("Seeding engagements ...")
        print(f"  created {seed(base)} (approved, rejected, modified, and two waiting for a partner)")
        if args.no_ui:
            print(f"\nAPI ready: {base}/docs\nCtrl+C to stop.")
        else:
            npm = shutil.which("npm") or shutil.which("npm.cmd")
            if npm is None:
                raise SystemExit("npm was not found; install Node.js, or pass --no-ui")
            ui_env = {**os.environ, "VITE_API_BASE_URL": base, "VITE_AUTH_MODE": "dev"}
            ui = subprocess.Popen([npm, "run", "dev", "--", "--port", str(args.ui_port), "--strictPort"],
                                  cwd=FRONTEND, env=ui_env)
            procs.append(ui)
            wait_for(f"http://localhost:{args.ui_port}/", ui, 90)
            print(f"\nReady. Open http://localhost:{args.ui_port}\n"
                  "  Partner: approve, modify or reject.   Admin or Auditor: Governance.\n"
                  "Ctrl+C to stop.")
        while all(p.poll() is None for p in procs):
            time.sleep(1)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    raise SystemExit(main())
