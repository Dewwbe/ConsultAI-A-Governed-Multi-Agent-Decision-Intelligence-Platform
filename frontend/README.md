# ConsultAI frontend

React 18 + TypeScript + Vite, Tailwind CSS 4 with shadcn/ui-style components, TanStack Query, React Router.
All stages are built: F0 scaffold, F1 engagement workspace, F2 human approval, F3 AI Control Center, F4 governance views,
F5 hardening (accessibility tests, end-to-end tests, tablet layouts, demo mode). See `../docs/STATUS.md`.

## Run it

```bash
cd frontend
npm install
cp .env.example .env          # set VITE_API_BASE_URL if the API is not on :8000
npm run dev                   # http://localhost:5173
```

The API must allow the origin (the backend's default `CORS_ORIGINS` includes `http://localhost:5173`) and
run with `AUTH_MODE=dev`, in which case you pick an identity from the header menu.

> If something else already answers on port 8000, start the backend elsewhere
> (`uvicorn app.main:app --port 8010`) and set `VITE_API_BASE_URL=http://localhost:8010`.

## Scripts

| Command | What it does |
|---|---|
| `npm run dev` | Dev server with hot reload |
| `npm test` | Vitest + React Testing Library + MSW (mock API), including an axe accessibility check of every page |
| `npm run e2e` | Playwright: starts the real API (stub models, throwaway DB) and the UI, then runs the whole journey in Chromium, plus a tablet layout check |
| `npm run screenshots` | Regenerates `../docs/screenshots` from the running app |
| `npm run demo` | API, seeded data and UI in one command (see the root README) |
| `E2E_API_URL=http://localhost:8030 npm test -- src/test/integration.test.ts` | Contract test against a real running backend (skipped by default) |
| `npm run lint` / `typecheck` | ESLint and `tsc --noEmit` (strict) |
| `npm run build` | Typecheck, then production build to `dist/` |
| `npm run api:update` | Re-export the backend OpenAPI schema and regenerate the typed client |

## The API contract

`src/api/schema.d.ts` is **generated** from the backend's OpenAPI schema (`openapi.json`); do not edit it.
After changing a backend endpoint or model, run `npm run api:update` and commit both files. CI regenerates
them and fails if the committed copies are stale, so the UI cannot drift from the API.

All calls go through `openapi-fetch` and `unwrap()`, which turns failures into typed errors
(`NotFoundError` for 404, `ConflictError` for 409 "not awaiting approval", `ForbiddenError`, `UnauthorizedError`,
`ValidationError`, `ServerError`, `NetworkError`). Branch on the class, not the status code. Only transient
errors (network, 5xx) are retried.

## Authentication and roles

* **dev** (`VITE_AUTH_MODE=dev`): the header menu sets a user and roles, sent as `X-Dev-User` / `X-Dev-Roles`.
  The backend only honours these when it runs in dev mode.
* **entra** (`VITE_AUTH_MODE=entra` plus `VITE_ENTRA_CLIENT_ID` / `VITE_ENTRA_TENANT_ID`): Microsoft sign-in with MSAL (redirect flow,
  tokens in session storage only, loaded lazily). Nothing calls the API until the user is signed in.

Roles shown in the UI come from the server (`GET /me`), never from local state. Hiding a link or page is a
convenience: the API enforces every protected action again. `RequireRole` guards a route; the nav hides items
the user cannot open.

## What F1 gives you

* **New engagement** (`/engagements/new`): the form validates exactly as the API does (question 5-4000 characters,
  industry up to 200, at most 20 objectives and 20 constraints), puts server-side field errors next to the field,
  and starts the run in the background (`wait=false`).
* **Engagements** (`/engagements`): status filter and pagination kept in the address; running rows refresh themselves.
* **Engagement page** (`/engagements/:id`): a live pipeline (Discovery, Research and Data in parallel, Financial,
  Risk, Solution, Evaluation, Guardian, Approval, Report) driven by Server-Sent Events, plus tabs for the summary,
  specification, evidence (with quote verification and retrieval replay), data lineage, financials, risks, options
  and the report.

* **Review and decide** (`/engagements/:id/review`): the metrics a partner needs (evidence score, financial confidence, risk,
  groundedness, constraint match, cost), the Guardian's reasons, then Approve / Modify / Reject. Modify edits only the
  rationale and assumptions (numbers trace to tools and are never editable); modify and reject require a reason; every
  decision goes through an accessible confirmation dialog. Users without the Partner role can read but not decide, and the
  server enforces that again (403), with typed handling for 409 (no longer waiting) and 422. History lives under the
  Approvals tab and on the review page.

### Live updates

`useEngagementLive` reads the event stream with `fetch` (not `EventSource`, which cannot send the auth headers).
It reconnects from the last event id after a dropped connection, never retries a 401/403/404, and after three failed
attempts falls back to polling, rebuilding the pipeline from the trace.

## What F3 and F4 give you

* **Control Center** (`/control-center`): success, escalation and approval rates, cost per successful task, quality and
  cost over time (every chart has a legend and a "View as table" switch), where the money goes, tool and safety
  figures, and recent runs. Quality flags say in words when a metric is below policy.
* **Run page** (`/control-center/:id`): overview, trace (a timeline of agents, tools and models with what each saw),
  tool calls and their outcomes (including blocked and timed out), retrievals (with replay), Guardian decisions,
  cost by agent and model, and the scores. Request and response payloads are shown only to roles allowed to see them.
* **Governance** (`/governance`, Admin or Auditor): the policy in force, its version history with a drift flag and the
  text of any version; the tool registry; provider health (circuit breaker, rate-limit use, which data each provider
  may see, recent fallbacks); budgets with near-limit alerts; and the quality-degradation level with its history.
* A run waiting for a free slot shows as **Queued**; if the queue is full the form says the platform is busy and for how long (429).

## Testing

* `npm test` runs against recorded fixtures: `python backend/scripts/record_fixtures.py frontend/src/mocks/fixtures`
  re-records them from a real stub run after a backend change.
* `src/test/a11y.test.tsx` runs axe on every page (colour contrast is excluded because jsdom has no layout; the chart
  palette is validated separately). A new page should be added there.
* `e2e/` holds the Playwright journey. It reuses servers already running on its ports (8011 and 5174) when not in CI.

## Layout

```
src/
  api/          generated schema, client, typed errors, query hooks
  auth/         AuthProvider (dev identity), RequireRole
  components/   ui/ (button, card, badge, alert, skeleton), layout/ (AppShell), states/ (loading, empty, error)
  lib/          cn(), safe localStorage, theme
  features/     engagements/ (pipeline logic, live hook, pages, panels), approval/, control-center/, governance/
  pages/        route components
  mocks/        MSW handlers that mirror the backend contract (tests)
  test/         test setup and render helpers
```

## Conventions

* Colours come from the tokens in `src/index.css` (light and dark); do not hard-code hex values in components.
* Every screen handles loading, empty and error states with the shared components in `components/states`.
* Never store tokens in `localStorage`; only harmless preferences (theme, dev identity) are stored there.
* Tests fail on any request that no mock handles, so a component cannot silently call an unmocked endpoint.

## Container

```bash
docker build -t consultai-web --build-arg VITE_API_BASE_URL=http://localhost:8000 .
docker run -p 8080:80 -e API_ORIGIN=http://localhost:8000 consultai-web
```

nginx serves the build with a strict content security policy (own scripts and styles only, and only the API
origin for `connect-src`). `docker compose up` from the repository root starts the API, Postgres and this app.
