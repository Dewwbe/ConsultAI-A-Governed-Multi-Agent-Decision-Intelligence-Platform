# 0006. Frontend stack, generated client and fetch-based SSE

**Status:** accepted

**Decision.** React 18 + TypeScript (strict) + Vite; Tailwind 4 with shadcn-style components we own; TanStack
Query for server state; React Router; Recharts for charts (palette validated for colour-blind separation and
contrast, with a table view of every chart). The API client is **generated** from the backend's OpenAPI
(`openapi-typescript` + `openapi-fetch`), and CI fails if the committed copy is stale. Live progress uses
Server-Sent Events read with `fetch`, not `EventSource`.

**Why.** A generated client makes UI/API drift a build failure. `EventSource` cannot send an Authorization
header, which Entra tokens need; a fetch reader can, and reconnects from the last event id. If the stream is
unavailable the page falls back to polling the trace, so a proxy that buffers SSE degrades to slower updates
rather than a broken page.

**Consequences.** Test fixtures are recorded from a real backend run, so mocks cannot drift from the contract.
Roles shown in the UI come from `/me`; hiding a screen is a convenience and the API enforces every action.
Heavy routes (charts, governance) load lazily. Accessibility is tested with axe on every page and the whole
journey with Playwright against the real API.
