# 0002. Deterministic Guardian first, AI Guardian second, human third

**Status:** accepted

**Decision.** Safety checks run in three layers: (1) deterministic rules from `policy.yaml` (financial
threshold, risk tiers, blocked tools, data classification); (2) an LLM Guardian that reads the output for
risks rules cannot express; (3) a human partner for anything the first two escalate. The merge is
**stricter-only**: the AI layer can raise a decision (allow to escalate) but can never lower what a rule
decided. Every decision records the policy version it was made under.

**Why.** Rules are predictable but blind to context; models see context but can be talked into things.
Letting the model only tighten the result keeps a prompt injection or a lenient model from weakening a rule.

**Consequences.** Escalation is the safe default when layers disagree or a layer is unavailable. Partners see
the reasons for each escalation. The AI layer's cost and failures show up in the Control Center.
