"""Fill an empty database with a few engagements in different states, so a public demo is not an empty page.

Used when DEMO_SEED=true. It runs only if there are no engagements yet, and it goes through the same service methods
as the API, so the data is what a real run produces (on whichever model provider is configured).
"""
from __future__ import annotations

import logging
import threading
from typing import Any

from app.security.auth import Principal

log = logging.getLogger("consultai.demo")
PARTNER = Principal("demo-partner", "Demo Partner", ("Partner",))
UAE = {"business_problem": "Should we expand into the UAE market?", "industry": "Retail",
       "objectives": ["Increase revenue"], "constraints": ["Budget under $10M", "Launch within 18 months"]}
SEED: list[tuple[dict[str, Any], str | None, str]] = [
    (UAE, "approve", "Numbers and sources check out; proceed with the phased entry."),
    ({**UAE, "business_problem": "Should we open a second distribution centre?", "industry": "Logistics"}, "reject",
     "The payback period is too long for this year's budget."),
    ({**UAE, "business_problem": "Should we acquire a regional competitor?"}, "modify",
     "Lower the growth assumption until the diligence results are in."),
    (UAE, None, ""),
    ({**UAE, "business_problem": "Should we enter the Saudi market next year?"}, None, ""),
]


def seed_demo(service: Any) -> int:
    """Create the demo engagements unless the database already has some. Returns how many were created."""
    _, total = service.db.list_engagements(None, 1, 0)
    if total:
        return 0
    made = 0
    for body, decision, reason in SEED:
        try:
            run = service.start(**body, user_id=PARTNER.user_id)
            made += 1
            if decision:
                changes = {"rationale": "Growth assumption lowered pending diligence."} if decision == "modify" else {}
                service.approve(run["workflow_id"], decision, changes, reason, approver=PARTNER)
        except Exception:
            log.exception("demo seed: could not create %r", body["business_problem"])
    log.info("demo seed: created %d engagements", made)
    return made


def seed_in_background(service: Any) -> threading.Thread:
    thread = threading.Thread(target=seed_demo, args=(service,), name="demo-seed", daemon=True)
    thread.start()
    return thread
