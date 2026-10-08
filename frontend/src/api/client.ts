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

export function createApi({ baseUrl, getIdentity, fetch: fetchImpl }: ApiOptions = {}) {
  const client = createClient<paths>({
    baseUrl: baseUrl ?? import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL,
    // Look fetch up per call instead of capturing it now: keeps test mocks and polyfills effective.
    fetch: fetchImpl ?? ((request: Request) => globalThis.fetch(request)),
  });
  const identity: Middleware = {
    onRequest({ request }) {
      const who = getIdentity?.();
      if (who) {
        request.headers.set("X-Dev-User", who.user);
        request.headers.set("X-Dev-Roles", who.roles.join(","));
      }
      return request;
    },
  };
  client.use(identity);
  return client;
}

export type Api = ReturnType<typeof createApi>;
export type { components } from "./schema";
