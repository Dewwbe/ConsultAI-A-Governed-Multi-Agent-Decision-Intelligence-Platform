import createClient, { type Middleware } from "openapi-fetch";
import type { paths } from "./schema";

export const DEFAULT_API_BASE_URL = "http://localhost:8000";

/** Development identity. The backend trusts these headers only when it runs with AUTH_MODE=dev. */
export interface DevIdentity {
  user: string;
  roles: string[];
}

export interface ApiOptions {
  baseUrl?: string;
  /** Called per request, so switching identity needs no new client. */
  getIdentity?: () => DevIdentity | null;
  fetch?: typeof fetch;
}

export function identityHeaders(identity: DevIdentity | null | undefined): Record<string, string> {
  return identity ? { "X-Dev-User": identity.user, "X-Dev-Roles": identity.roles.join(",") } : {};
}

export function createApi({ baseUrl, getIdentity, fetch: fetchImpl }: ApiOptions = {}) {
  const resolvedBase = (baseUrl ?? import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL).replace(/\/+$/, "");
  const client = createClient<paths>({
    baseUrl: resolvedBase,
    // Look fetch up per call instead of capturing it now: keeps test mocks and polyfills effective.
    fetch: fetchImpl ?? ((request: Request) => globalThis.fetch(request)),
  });
  const identity: Middleware = {
    onRequest({ request }) {
      for (const [k, v] of Object.entries(identityHeaders(getIdentity?.()))) request.headers.set(k, v);
      return request;
    },
  };
  client.use(identity);
  // Streaming (SSE) bypasses openapi-fetch, so expose what it needs: the base URL and the auth headers.
  return Object.assign(client, {
    config: { baseUrl: resolvedBase, getHeaders: () => identityHeaders(getIdentity?.()) },
  });
}

export type Api = ReturnType<typeof createApi>;
export type { components } from "./schema";
