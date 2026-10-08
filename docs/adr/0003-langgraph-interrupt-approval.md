# 0003. LangGraph with an interrupt for approval, state checkpointed

**Status:** accepted

**Decision.** The workflow is a LangGraph state machine. The approval node uses an *interrupt*: the run stops,
its state is checkpointed (SQLite in development, Postgres in production), and resumes when a partner decides.
Non-serialisable runtime objects (budget, tracer, registry) live in a per-workflow runtime context that is
rebuilt from database snapshots after a restart.

**Why.** Approval can take days. A run must survive a process restart while it waits, and it must resume from
exactly the state the partner reviewed, not re-run the agents.

**Consequences.** State must be serialisable and versioned; anything else goes in the runtime context. A
partner's *modify* decision edits only rationale and assumptions: figures come from tools and cannot be
changed in review. Approval is enforced by role in the API, not in the UI.
