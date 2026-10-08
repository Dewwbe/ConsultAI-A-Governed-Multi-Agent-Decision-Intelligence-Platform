"""PII and secret scrubbing.

Used in two places: traces shown in the Control Center (so a reviewer never sees a raw secret or
personal identifier, whatever their role) and the LLM gateway (so personal data is not sent to a
provider unless policy allows it).

It is pattern based and deliberately conservative about *what* it matches, to avoid mangling the
financial figures and dates this application is full of: phone numbers need a `+` or a grouped
layout, card numbers must pass the Luhn check, and only string values are scanned (numbers are left
alone). It is a safety net, not a guarantee: it cannot recognise a name.
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

_SECRET_KEYS = re.compile(r"(password|passwd|secret|api[_-]?key|token|authorization|credential|connection[_-]?string)", re.IGNORECASE)

# (label, pattern, validator). Order matters: more specific secrets first.
_PATTERNS: list[tuple[str, re.Pattern[str], Callable[[str], bool] | None]] = [
    ("secret", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}"), None),  # JWT
    ("secret", re.compile(r"\b(?:sk|pk|rk)[-_](?:live|test|proj)?[-_]?[A-Za-z0-9]{16,}\b"), None),
    ("secret", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), None),
    ("secret", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"), None),
    ("secret", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"), None),
    ("secret", re.compile(r"(?i)\b(?:password|passwd|secret|api[_-]?key|token|pwd)\s*[:=]\s*\S+"), None),
    ("secret", re.compile(r"\b[A-Za-z0-9+/_-]{40,}={0,2}(?![A-Za-z0-9])"), None),  # long opaque token
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"), None),
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b"), None),
    ("card", re.compile(r"(?<![\d.])(?:\d[ -]?){13,19}(?![\d.])"), lambda s: _luhn(re.sub(r"\D", "", s))),
    ("phone", re.compile(r"(?<![\w.])\+\d[\d ()-]{7,}\d(?!\w)"), lambda s: 9 <= len(re.sub(r"\D", "", s)) <= 15),
    ("phone", re.compile(r"(?<![\w.])\(?\d{3}\)?[ -]\d{3}[ -]\d{4}(?!\w)"), None),
]


def _luhn(digits: str) -> bool:
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d = d * 2 - 9 if d * 2 > 9 else d * 2
        total += d
    return total % 10 == 0


@dataclass
class Scrubbed:
    value: Any
    counts: Counter[str] = field(default_factory=Counter)

    @property
    def total(self) -> int:
        return sum(self.counts.values())


def scrub_text(text: str, counts: Counter[str] | None = None, only: frozenset[str] | None = None) -> str:
    """Mask matches. `only` limits it to some labels (for example just {"secret"}); None masks everything."""
    counts = counts if counts is not None else Counter()
    for label, pattern, valid in _PATTERNS:
        if only is not None and label not in only:
            continue
        def swap(m: re.Match[str], label: str = label, valid: Callable[[str], bool] | None = valid) -> str:
            if valid and not valid(m.group(0)):
                return m.group(0)
            counts[label] += 1
            return f"[{label}]"
        text = pattern.sub(swap, text)
    return text


def scrub(obj: Any) -> Scrubbed:
    """Scrub every string inside dicts, lists and tuples. Values under secret-looking keys are replaced whole."""
    counts: Counter[str] = Counter()

    def walk(x: Any, key: str | None = None) -> Any:
        if isinstance(x, str):
            if key and _SECRET_KEYS.search(key):
                counts["secret"] += 1
                return "[secret]"
            return scrub_text(x, counts)
        if isinstance(x, dict):
            return {k: walk(v, str(k)) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [walk(v, key) for v in x]
        return x  # numbers, booleans and None are never personal identifiers

    return Scrubbed(walk(obj), counts)
