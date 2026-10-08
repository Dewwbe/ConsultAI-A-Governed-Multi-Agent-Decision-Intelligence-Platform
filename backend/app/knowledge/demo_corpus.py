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

    # ---- Synthetic scenario briefings. FICTIONAL figures for demonstration: not real market data. ----
    # Internal classification, so a "public" engagement correctly cannot use them.
    {"id": "doc_syn_5", "source": "synthetic://uae-retail-market-size", "date": "2026-03-01",
     "text": ("SYNTHETIC DEMO DATA (fictional). In this scenario, UAE retail market demand is modelled at USD 45 "
              "billion of annual sales, growing 5% a year, driven by tourism and a young urban population. "
              "Online retail is assumed to hold 18% of sales and to keep rising."),
     "confidence": 0.7, "country": "UAE", "industry": "Retail", "classification": "internal"},
    {"id": "doc_syn_6", "source": "synthetic://uae-customer-segments", "date": "2026-03-01",
     "text": ("SYNTHETIC DEMO DATA (fictional). In this scenario, UAE retail customer segments are tourists at 25% "
              "of spend, resident expatriates at 50% and nationals at 25%. Expatriate customers are the most "
              "price sensitive, and demand peaks during the winter tourism season."),
     "confidence": 0.65, "country": "UAE", "industry": "Retail", "classification": "internal"},
    {"id": "doc_syn_7", "source": "synthetic://uae-competitor-landscape", "date": "2026-03-01",
     "text": ("SYNTHETIC DEMO DATA (fictional). In this scenario the UAE competitive landscape is led by three "
              "regional operators holding 55% market share. International entrants typically reach 2 to 4% share "
              "within three years, and competition is strongest in large shopping malls."),
     "confidence": 0.7, "country": "UAE", "industry": "Retail", "classification": "internal"},
    {"id": "doc_syn_8", "source": "synthetic://uae-entry-options", "date": "2026-03-01",
     "text": ("SYNTHETIC DEMO DATA (fictional). Market-entry options and operating requirements in the UAE "
              "scenario: a local distribution partner shortens launch to 9 to 12 months, a company-owned store "
              "needs 15 to 18 months of fit-out and licensing, and an online-only entry can launch in 6 months "
              "but needs local fulfilment."),
     "confidence": 0.7, "country": "UAE", "industry": "Retail", "classification": "internal"},
    {"id": "doc_syn_9", "source": "synthetic://uae-expansion-costs", "date": "2026-03-01",
     "text": ("SYNTHETIC DEMO DATA (fictional). Expansion costs and funding requirements in the UAE scenario: a "
              "partner-led entry needs roughly USD 2 to 4 million of upfront investment, and a company-owned "
              "multi-store entry needs USD 7 to 9 million. Break-even takes 18 to 30 months, and year-three "
              "revenue potential is modelled at 6 to 9% of the home-market revenue base."),
     "confidence": 0.65, "country": "UAE", "industry": "Retail", "classification": "internal"},
    {"id": "doc_syn_10", "source": "synthetic://uae-market-entry-regulation", "date": "2026-03-01",
     "text": ("SYNTHETIC DEMO DATA (fictional). Regulatory requirements and market-entry risks in the UAE scenario: "
              "foreign retailers need a trade licence, assumed to take 3 to 6 months and longer if documentation "
              "is incomplete. Free-zone entities follow different ownership rules. Market-entry risk is "
              "concentrated in licence delays and dependence on a local partner."),
     "confidence": 0.75, "country": "UAE", "industry": "Retail", "classification": "internal"},
    {"id": "doc_syn_11", "source": "synthetic://uae-currency-and-duties", "date": "2026-03-01",
     "text": ("SYNTHETIC DEMO DATA (fictional). Funding and currency in the UAE scenario: the dirham is pegged to "
              "the US dollar, so currency risk on revenue is low, and import duties of 5% apply to most retail "
              "goods, which affects profitability."),
     "confidence": 0.7, "country": "UAE", "industry": "Retail", "classification": "internal"},
    {"id": "doc_syn_12", "source": "synthetic://comparable-entries", "date": "2026-03-01",
     "text": ("SYNTHETIC DEMO DATA (fictional). In comparable market-entry cases in this scenario, pilot-first "
              "expansion reached 70% of planned year-one revenue, and partner-led entries reached break-even "
              "about six months sooner than company-owned entries. Expansion plans that skipped a pilot "
              "overran their budget more often."),
     "confidence": 0.6, "country": "UAE", "industry": "Retail", "classification": "internal"},
]
