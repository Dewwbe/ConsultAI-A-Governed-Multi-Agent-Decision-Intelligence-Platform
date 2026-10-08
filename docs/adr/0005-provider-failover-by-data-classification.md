# 0005. Provider failover is restricted by data classification

**Status:** accepted

**Decision.** Each model provider has a circuit breaker and rate limits. When a provider fails, a call may
move to another provider **only if policy allows that provider to see data of that classification**
(`data_classification.<class>.allowed_providers`). If none is allowed the call fails and the run escalates; it
does not fall back to an unapproved provider. Personal data is redacted before leaving the platform according
to the classification (`pii` in policy). Each fallback is logged with its reason.

**Why.** Availability must not quietly override a confidentiality rule. Confidential client data going to
whichever model happened to be up is the failure this prevents.

**Consequences.** Confidential work can be unavailable when its one allowed provider is down; the UI shows the
tripped breaker, the retry time and recent fallbacks to administrators. Adding a provider is a policy change,
which is versioned and drift-checked.
