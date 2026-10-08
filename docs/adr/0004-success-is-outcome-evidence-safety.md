# 0004. Success means outcome, evidence and safety (anti-reward-hacking)

**Status:** accepted

**Decision.** A run counts as successful only if all three hold: the **outcome** satisfies the question and its
constraints; the **evidence** behind each claim is verified (the quoted text is found in the cited source);
and **safety** held (no blocked action, no policy breach, no unreviewed high-risk step). The LLM judge's score
is *bounded by* the deterministic checks: groundedness is capped by citation validity, and tool-call accuracy
and contradiction checks are computed without a model.

**Why.** If success is "the task finished" or "the judge liked it", agents (and the people tuning them) are
rewarded for confident, well-formatted output rather than correct output. Making each leg independently
checkable removes the easy shortcuts: citing a source that does not say it, skipping a required tool, meeting
a constraint by quietly dropping it, or finishing fast by skipping the Guardian.

**Consequences.** Headline metrics such as *cost per successful task* use this definition, so a cheap run that
fails a leg does not look efficient. The decision dataset records human decisions next to scores so the judge
can later be calibrated against what partners actually did. A sustained drop in these scores moves the
platform to a cautious mode (stronger models, wider retrieval, then mandatory partner review).
