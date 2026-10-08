"""Memory classification rule: not every sentence becomes long-term memory.

Deterministic and conservative. A statement is promoted only if it is durable (a preference,
or a stated fact/constraint) and safe (no personal data or secrets). Questions, chit-chat and
one-off remarks stay in short-term memory only. Replace/augment with an LLM classifier later,
keeping `classify_memory` as the gate: sensitive content must always be rejected here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_CHITCHAT = re.compile(
    r"^\s*(hi|hello|hey|thanks|thank you|ok|okay|got it|sure|yes|no|cool|great)\b[\s.!]*$", re.IGNORECASE)
_SENSITIVE = re.compile(
    r"[\w.+-]+@[\w-]+\.[\w.]+"                       # e-mail
    r"|\b(?:\d[ -]?){13,16}\b"                      # card-like number
    r"|\+?\d[\d ()-]{8,}\d"                         # phone-like number
    r"|\b[A-Za-z0-9_\-]{32,}\b"                     # long token / key
    r"|\b(password|passwd|secret|api[ _-]?key|token)\b", re.IGNORECASE)
_QUESTION = re.compile(
    r"\?\s*$|^\s*(what|why|how|when|where|who|which|can|could|should|is|are|do|does)\b", re.IGNORECASE)
_PREFERENCE = re.compile(
    r"\b(i|we)\s+(prefer|like|want|always|never|need)\b|\bplease\s+(always|never|use|avoid)\b"
    r"|\b(always|never)\b|\bprefer\b", re.IGNORECASE)
_FACT = re.compile(
    r"\$\s?\d|\b\d+(\.\d+)?\s?(m|k|million|billion)\b|\bbudget\b|\bdeadline\b"
    r"|\bwithin\s+\d+\s+(days|weeks|months|years)\b|\bour\s+(company|team|policy|clients?|stores?)\b"
    r"|\bwe\s+(operate|have|are|sell|serve)\b", re.IGNORECASE)

MIN_CHARS = 12
SENSITIVE_REASON = "contains personal data or secrets"


@dataclass(frozen=True)
class MemoryDecision:
    store: bool
    type: str = "none"      # preference | fact | none
    scope: str = "none"     # user | engagement | none
    reason: str = ""


def classify_memory(text: str, *, engagement_scoped: bool = False) -> MemoryDecision:
    t = text.strip()
    if len(t) < MIN_CHARS or _CHITCHAT.match(t):
        return MemoryDecision(False, reason="chit-chat or too short")
    if _SENSITIVE.search(t):  # checked before anything that could store it
        return MemoryDecision(False, reason=SENSITIVE_REASON)
    if _QUESTION.search(t):
        return MemoryDecision(False, reason="question: transient")
    if _PREFERENCE.search(t):
        return MemoryDecision(True, "preference", "user", "stated preference")
    if _FACT.search(t):
        return MemoryDecision(True, "fact", "engagement" if engagement_scoped else "user",
                              "stated fact or constraint")
    return MemoryDecision(False, reason="not durable")
