"""Risk taxonomy and historical-risk store.

Each category carries guidance: a plausible probability band and impact band, used to calibrate
model-proposed ratings (a rating outside the band is clamped and flagged, never silently
accepted). Historical entries are analogues the Risk Agent can cite.

All bands and history entries are PLACEHOLDERS for development; replace them with the firm's
own risk register before relying on any score.
"""
from __future__ import annotations

import re
from typing import Any

TAXONOMY: dict[str, dict[str, Any]] = {
    "Financial": {"description": "Cost overruns, FX, funding, margin erosion",
                  "probability": (0.15, 0.6), "impact": (0.4, 0.9)},
    "Operational": {"description": "Supply chain, logistics, staffing, process failure",
                    "probability": (0.2, 0.7), "impact": (0.3, 0.8)},
    "Market": {"description": "Demand shortfall, pricing pressure, competitor response",
               "probability": (0.25, 0.7), "impact": (0.4, 0.85)},
    "Regulatory": {"description": "Licensing, approvals, compliance, foreign-ownership rules",
                   "probability": (0.3, 0.8), "impact": (0.5, 0.95)},
    "Cybersecurity": {"description": "Breach, ransomware, data loss",
                      "probability": (0.1, 0.4), "impact": (0.5, 0.95)},
    "Technology": {"description": "Platform failure, integration, scalability",
                   "probability": (0.15, 0.55), "impact": (0.3, 0.8)},
    "Reputational": {"description": "Brand damage, negative press, stakeholder trust",
                     "probability": (0.05, 0.4), "impact": (0.4, 0.9)},
    "People": {"description": "Key-person loss, hiring, culture, retention",
               "probability": (0.2, 0.6), "impact": (0.2, 0.7)},
    "Implementation": {"description": "Delay, scope creep, change-management failure",
                       "probability": (0.3, 0.75), "impact": (0.3, 0.8)},
    "Third-party": {"description": "Partner, vendor or distributor underperformance",
                    "probability": (0.2, 0.6), "impact": (0.3, 0.75)},
    "Data/privacy": {"description": "Privacy law, data residency, consent",
                     "probability": (0.15, 0.5), "impact": (0.4, 0.9)},
}

HISTORY: list[dict[str, Any]] = [
    {"id": "hist_001", "category": "Regulatory", "risk": "Market-entry licence delayed beyond plan",
     "probability": 0.6, "impact": 0.8, "outcome": "Launch slipped two quarters",
     "keywords": ["licence", "license", "approval", "entry", "regulatory", "expansion"],
     "source": "placeholder://risk-register/2023-q4"},
    {"id": "hist_002", "category": "Market", "risk": "Demand below plan in a new region",
     "probability": 0.45, "impact": 0.6, "outcome": "Revenue reached 70% of plan in year one",
     "keywords": ["demand", "expansion", "new", "market", "region", "launch"],
     "source": "placeholder://risk-register/2024-q2"},
    {"id": "hist_003", "category": "Third-party", "risk": "Local partner under-delivered",
     "probability": 0.35, "impact": 0.55, "outcome": "Contract renegotiated, six-month delay",
     "keywords": ["partner", "partnership", "distributor", "joint", "local"],
     "source": "placeholder://risk-register/2024-q3"},
    {"id": "hist_004", "category": "Financial", "risk": "Currency movement eroded margin",
     "probability": 0.4, "impact": 0.5, "outcome": "Margin 3 points below plan",
     "keywords": ["currency", "fx", "margin", "pricing", "import"],
     "source": "placeholder://risk-register/2025-q1"},
]

CATEGORIES = list(TAXONOMY)


def guidance(category: str) -> dict[str, Any] | None:
    g = TAXONOMY.get(category)
    return None if g is None else {"category": category, **g}


def calibrate(category: str, probability: float, impact: float) -> tuple[float, float, str | None]:
    """Clamp a rating into the category's band. Returns (probability, impact, note-or-None)."""
    g = TAXONOMY[category]
    p = min(max(probability, g["probability"][0]), g["probability"][1])
    i = min(max(impact, g["impact"][0]), g["impact"][1])
    if (p, i) == (probability, impact):
        return probability, impact, None
    return p, i, (f"rating adjusted to {category} guidance: probability {probability:.2f}->{p:.2f}, "
                  f"impact {impact:.2f}->{i:.2f}")


def similar_history(text: str, category: str | None = None, k: int = 3) -> list[dict[str, Any]]:
    words = set(re.findall(r"[a-z]+", text.lower()))
    scored = []
    for h in HISTORY:
        if category and h["category"] != category:
            continue
        overlap = len(words & set(h["keywords"]))
        if overlap:
            scored.append((overlap, h["id"], h))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [h for _, _, h in scored[:k]]


def risk_lookup(query: str = "", category: str | None = None) -> dict[str, Any]:
    """Tool: taxonomy guidance (all categories, or one) plus historical analogues for `query`."""
    if category is not None and category not in TAXONOMY:
        raise ValueError(f"unknown risk category '{category}'")
    cats = [category] if category else CATEGORIES
    return {"guidance": [guidance(c) for c in cats],
            "history": similar_history(query, category) if query else []}
