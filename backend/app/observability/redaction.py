"""Decide what of a trace a given user may see.

A span carries *structure* (names, timings, statuses, token counts, ids, the Guardian's decision) and
*payload* (tool arguments and results, SQL, the retrieval query and retrieved passages). Structure is
safe to show any signed-in user. Payload can hold client data, so:

* public / internal engagements: everyone signed in sees payloads;
* confidential engagements: only the engagement's owner and users with a privileged role
  (default Partner, Admin) do; everyone else gets the structure with payloads replaced.

Whatever the role, secrets and personal identifiers are scrubbed from every span (see security/pii.py).
"""
from __future__ import annotations

import copy
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.security.auth import Principal
from app.security.pii import scrub

PAYLOAD_KEYS = (
    "consultai.tool_arguments",
    "consultai.tool_result",
    "consultai.sql",
    "consultai.query",
    "consultai.retrieval",
)
REDACTED = "[redacted: needs the owner, Partner or Admin role]"
_OPEN_CLASSIFICATIONS = {"public", "internal"}


@dataclass(frozen=True)
class Redaction:
    payloads_redacted: bool
    pii_scrubbed: int
    reason: str | None


def can_see_payloads(principal: Principal, *, owner_id: str, classification: str, privileged_roles: Iterable[str]) -> bool:
    if classification in _OPEN_CLASSIFICATIONS:
        return True
    return principal.user_id == owner_id or any(principal.has_role(r) for r in privileged_roles)


def _redact_retrieval(value: Any) -> Any:
    """Keep what a reviewer needs to reason about the search (ids, sources, scores, model) but drop text and query."""
    if not isinstance(value, dict):
        return REDACTED
    keep = {k: value[k] for k in ("retrieval_id", "index", "embedding_model", "reranker", "index_version", "k") if k in value}
    keep["documents"] = [{k: d[k] for k in ("doc_id", "chunk_id", "source", "score") if k in d}
                         for d in value.get("documents", []) if isinstance(d, dict)]
    keep["redacted"] = True
    return keep


def redact_trace(trace: dict[str, Any], *, show_payloads: bool, reason: str | None = None) -> tuple[dict[str, Any], Redaction]:
    out = copy.deepcopy(trace)
    scrubbed = 0
    redacted = False
    for span in out.get("spans", []):
        attrs = span.get("attributes", {})
        if not show_payloads:
            for key in PAYLOAD_KEYS:
                if key in attrs:
                    attrs[key] = _redact_retrieval(attrs[key]) if key == "consultai.retrieval" else REDACTED
                    redacted = True
        result = scrub(attrs)
        span["attributes"] = result.value
        scrubbed += result.total
        if span.get("error"):
            err = scrub(span["error"])
            span["error"] = err.value
            scrubbed += err.total
    return out, Redaction(redacted, scrubbed, reason if redacted else None)
