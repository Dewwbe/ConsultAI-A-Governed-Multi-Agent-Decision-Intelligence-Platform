# 0001. The model chooses; deterministic code calculates

**Status:** accepted

**Decision.** Agents decide *which* analysis to run and how to explain it. Every number in a recommendation
(ROI, NPV, payback, growth) comes from a registered tool in `tools/financial.py`, not from model text. Tool
arguments are validated against a JSON schema and checked against policy before they run.

**Why.** Language models produce fluent, plausible arithmetic that is sometimes wrong, and a wrong figure in a
client report is the costliest failure this platform has. Tools are testable, repeatable and auditable.

**Consequences.** A claim with no tool output or cited source behind it is flagged by the evaluator. Adding a
new kind of calculation means adding a tool, not a prompt. Tool latency and failure now matter, hence the
per-tool timeouts and retry limits in the registry.
