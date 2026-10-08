"""Bound the size of payloads stored on spans, so one large query result cannot bloat a trace."""
from __future__ import annotations

import json
from typing import Any

MAX_PAYLOAD_CHARS = 8_000


def cap_payload(value: Any, max_chars: int = MAX_PAYLOAD_CHARS) -> Any:
    """Return `value` unchanged if its JSON form fits, else a marked preview. Never raises."""
    try:
        text = json.dumps(value, default=str)
    except (TypeError, ValueError):
        text = repr(value)
    if len(text) <= max_chars:
        try:
            return json.loads(text)  # a plain-JSON copy: spans are persisted and sent over the API
        except ValueError:
            return text
    return {"_truncated": True, "original_chars": len(text), "preview": text[:max_chars]}
