# Architecture decision records

Short records of decisions that are costly to reverse, written when they were made.
Each one says what was decided, why, and what it costs us.

| # | Decision |
|---|---|
| [0001](0001-llm-chooses-code-calculates.md) | The model chooses; deterministic code calculates |
| [0002](0002-guardian-layers-and-human-approval.md) | Deterministic Guardian first, AI Guardian second, human third |
| [0003](0003-langgraph-interrupt-approval.md) | LangGraph with an interrupt for approval, state checkpointed |
| [0004](0004-success-is-outcome-evidence-safety.md) | Success means outcome, evidence and safety (anti-reward-hacking) |
| [0005](0005-provider-failover-by-data-classification.md) | Provider failover is restricted by data classification |
| [0006](0006-frontend-stack-and-live-updates.md) | Frontend stack, generated client and fetch-based SSE |
