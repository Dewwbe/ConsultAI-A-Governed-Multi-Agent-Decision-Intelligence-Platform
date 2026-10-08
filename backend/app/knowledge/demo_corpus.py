"""Illustrative demo corpus so the offline pipeline has grounded evidence.
These entries are PLACEHOLDERS for development only — not real market data."""

DEMO_CORPUS = [
    {"id": "doc_demo_1", "source": "demo://market-overview", "date": "2026-01-01",
     "text": "retail market growth expansion demand placeholder demo evidence", "confidence": 0.8,
     "country": "UAE", "industry": "Retail", "classification": "public"},
    {"id": "doc_demo_2", "source": "demo://regulatory-guide", "date": "2026-01-01",
     "text": "regulatory approval licensing timeline risk placeholder demo evidence", "confidence": 0.75,
     "country": "UAE", "industry": "Retail", "classification": "internal"},
    {"id": "doc_demo_3", "source": "demo://competitor-scan", "date": "2026-01-01",
     "text": "competition competitor landscape market share placeholder demo evidence", "confidence": 0.7,
     "country": "UAE", "industry": "Retail", "classification": "internal"},
    # Restricted: only callers in the `partners` group may see it (exercises permission filters).
    {"id": "doc_demo_4", "source": "demo://partner-pricing-memo", "date": "2026-02-01",
     "text": "partner pricing negotiation margin expansion market placeholder demo evidence",
     "confidence": 0.8, "country": "UAE", "industry": "Retail", "classification": "confidential",
     "allowed_groups": ["partners"]},
]
