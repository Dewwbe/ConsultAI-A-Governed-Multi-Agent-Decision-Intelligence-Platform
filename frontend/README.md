# ConsultAI frontend

React 18 + TypeScript + Vite, Tailwind CSS 4 with shadcn/ui-style components, TanStack Query, React Router.
This is stage **F0** of the frontend track (scaffold and contract). See `docs/IMPLEMENTATION_PLAN.md`
for the stages that follow: F1 engagement workspace, F2 human approval, F3 AI Control Center,
F4 governance views, F5 hardening.

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
| `npm test` | Vitest + React Testing Library + MSW (mock API), runs once |
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
* **entra**: Microsoft sign-in with MSAL arrives in **F2**.

Roles shown in the UI come from the server (`GET /me`), never from local state. Hiding a link or page is a
convenience: the API enforces every protected action again. `RequireRole` guards a route; the nav hides items
the user cannot open.

## Layout

```
src/
  api/          generated schema, client, typed errors, query hooks
  auth/         AuthProvider (dev identity), RequireRole
  components/   ui/ (button, card, badge, alert, skeleton), layout/ (AppShell), states/ (loading, empty, error)
  lib/          cn(), safe localStorage, theme
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
