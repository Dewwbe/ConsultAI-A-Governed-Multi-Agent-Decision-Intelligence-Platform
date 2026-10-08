import type { AccountInfo, IPublicClientApplication } from "@azure/msal-browser";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it, vi } from "vitest";
import { createApi } from "@/api/client";
import { API } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { renderApp } from "@/test/utils";
import { EntraSession, entraConfigFromEnv } from "./entra";

const SCOPES = ["api://client-1/access_as_user"];
const ACCOUNT = { homeAccountId: "acct-1", name: "Pat Partner", username: "pat@contoso.com" } as AccountInfo;

/** A stand-in for MSAL's PublicClientApplication: records calls, returns what the test says. */
function fakeMsal(over: Partial<Record<keyof IPublicClientApplication, unknown>> = {}) {
  const msal = {
    initialize: vi.fn().mockResolvedValue(undefined),
    handleRedirectPromise: vi.fn().mockResolvedValue(null),
    getActiveAccount: vi.fn().mockReturnValue(null),
    getAllAccounts: vi.fn().mockReturnValue([]),
    setActiveAccount: vi.fn(),
    loginRedirect: vi.fn().mockResolvedValue(undefined),
    logoutRedirect: vi.fn().mockResolvedValue(undefined),
    acquireTokenSilent: vi.fn().mockResolvedValue({ accessToken: "tok-1" }),
    acquireTokenRedirect: vi.fn().mockResolvedValue(undefined),
    ...over,
  };
  return msal as typeof msal & IPublicClientApplication;
}
const session = (msal: IPublicClientApplication) => new EntraSession(msal, SCOPES);

describe("entraConfigFromEnv", () => {
  it("needs a client and a tenant, and defaults the API scope", () => {
    expect(entraConfigFromEnv({})).toBeNull();
    expect(entraConfigFromEnv({ VITE_ENTRA_CLIENT_ID: "c" })).toBeNull();
    expect(entraConfigFromEnv({ VITE_ENTRA_CLIENT_ID: "c", VITE_ENTRA_TENANT_ID: "t" })).toEqual({
      clientId: "c",
      tenantId: "t",
      scopes: ["api://c/access_as_user"],
    });
    expect(
      entraConfigFromEnv({ VITE_ENTRA_CLIENT_ID: "c", VITE_ENTRA_TENANT_ID: "t", VITE_ENTRA_API_SCOPE: "api://x/y" })?.scopes,
    ).toEqual(["api://x/y"]);
  });
});

describe("EntraSession", () => {
  it("prefers the account from a redirect that just finished, and makes it active", async () => {
    const msal = fakeMsal({ handleRedirectPromise: vi.fn().mockResolvedValue({ account: ACCOUNT }) });
    expect(await session(msal).init()).toEqual({ id: "acct-1", name: "Pat Partner", username: "pat@contoso.com" });
    expect(msal.setActiveAccount).toHaveBeenCalledWith(ACCOUNT);
  });

  it("falls back to the cached account, and to signed-out when there is none", async () => {
    const cached = fakeMsal({ getAllAccounts: vi.fn().mockReturnValue([ACCOUNT]) });
    expect((await session(cached).init())?.id).toBe("acct-1");
    expect(await session(fakeMsal()).init()).toBeNull();
  });

  it("gets tokens silently for the API scope", async () => {
    const msal = fakeMsal({ getActiveAccount: vi.fn().mockReturnValue(ACCOUNT) });
    expect(await session(msal).getToken()).toBe("tok-1");
    expect(msal.acquireTokenSilent).toHaveBeenCalledWith({ scopes: SCOPES, account: ACCOUNT });
  });

  it("returns no token when nobody is signed in", async () => {
    const msal = fakeMsal();
    expect(await session(msal).getToken()).toBeNull();
    expect(msal.acquireTokenSilent).not.toHaveBeenCalled();
  });

  it("sends the user back to Microsoft when interaction is needed, instead of failing", async () => {
    const err = Object.assign(new Error("login required"), { name: "InteractionRequiredAuthError" });
    const msal = fakeMsal({
      getActiveAccount: vi.fn().mockReturnValue(ACCOUNT),
      acquireTokenSilent: vi.fn().mockRejectedValue(err),
    });
    expect(await session(msal).getToken()).toBeNull();
    expect(msal.acquireTokenRedirect).toHaveBeenCalledWith({ scopes: SCOPES, account: ACCOUNT });
  });

  it("does not hide other token failures", async () => {
    const msal = fakeMsal({
      getActiveAccount: vi.fn().mockReturnValue(ACCOUNT),
      acquireTokenSilent: vi.fn().mockRejectedValue(new Error("network down")),
    });
    await expect(session(msal).getToken()).rejects.toThrow("network down");
  });

  it("signs in with the API scope and signs out the active account", async () => {
    const msal = fakeMsal({ getActiveAccount: vi.fn().mockReturnValue(ACCOUNT) });
    await session(msal).signIn();
    expect(msal.loginRedirect).toHaveBeenCalledWith({ scopes: SCOPES });
    await session(msal).signOut();
    expect(msal.logoutRedirect).toHaveBeenCalledWith({ account: ACCOUNT });
  });
});

describe("api client with a token", () => {
  it("sends the bearer token, and the token wins over a dev identity", async () => {
    let seen: Headers | undefined;
    server.use(
      http.get(`${API}/health`, ({ request }) => {
        seen = request.headers;
        return HttpResponse.json({ status: "ok", llm_provider: "stub" });
      }),
    );
    const api = createApi({ baseUrl: API, getToken: async () => "tok-9", getIdentity: () => ({ user: "x", roles: ["Partner"] }) });
    await api.GET("/health");
    expect(seen?.get("authorization")).toBe("Bearer tok-9");
    expect(seen?.has("x-dev-user")).toBe(false);
    expect(await api.config.getHeaders()).toEqual({ Authorization: "Bearer tok-9" }); // what the event stream sends
  });

  it("falls back to the dev identity when there is no token", async () => {
    const api = createApi({ baseUrl: API, getToken: async () => null, getIdentity: () => ({ user: "x", roles: ["A"] }) });
    expect(await api.config.getHeaders()).toEqual({ "X-Dev-User": "x", "X-Dev-Roles": "A" });
  });
});

describe("the app in Entra mode", () => {
  it("shows a sign-in screen and calls nothing until the user signs in", async () => {
    const calls: string[] = [];
    server.use(
      http.all(`${API}/*`, ({ request }) => {
        calls.push(request.url);
        return HttpResponse.json({});
      }),
    );
    const msal = fakeMsal();
    renderApp("/", undefined, { authMode: "entra", entraSession: session(msal) });
    const button = await screen.findByRole("button", { name: /sign in with microsoft/i });
    expect(calls).toEqual([]); // not a single API request while signed out
    await userEvent.click(button);
    expect(msal.loginRedirect).toHaveBeenCalledWith({ scopes: SCOPES });
    expect(screen.queryByText(/dev sign-in/i)).not.toBeInTheDocument();
  });

  it("once signed in, sends the token on every call and shows the account", async () => {
    const auth: (string | null)[] = [];
    server.use(
      http.get(`${API}/me`, ({ request }) => {
        auth.push(request.headers.get("authorization"));
        return HttpResponse.json({ user_id: "oid-1", name: "Pat Partner", roles: ["Partner"], can_approve: true });
      }),
    );
    const msal = fakeMsal({
      getAllAccounts: vi.fn().mockReturnValue([ACCOUNT]),
      getActiveAccount: vi.fn().mockReturnValue(ACCOUNT),
    });
    renderApp("/", undefined, { authMode: "entra", entraSession: session(msal) });
    expect(await screen.findByText("Pat Partner", { selector: "span[title]" })).toBeInTheDocument();
    await waitFor(() => expect(auth.length).toBeGreaterThan(0));
    expect(auth.every((a) => a === "Bearer tok-1")).toBe(true);
    expect(screen.queryByText(/dev sign-in/i)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /sign out/i }));
    expect(msal.logoutRedirect).toHaveBeenCalled();
  });

  it("says plainly when Microsoft sign-in is not configured", async () => {
    renderApp("/", undefined, { authMode: "entra" }); // no session, and no VITE_ENTRA_* in tests
    expect(await screen.findByText("Sign-in is unavailable")).toBeInTheDocument();
    expect(screen.getByText(/VITE_ENTRA_CLIENT_ID/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /sign in with microsoft/i })).not.toBeInTheDocument();
  });

  it("shows an initialisation failure instead of a blank page", async () => {
    const msal = fakeMsal({ initialize: vi.fn().mockRejectedValue(new Error("popup blocked")) });
    renderApp("/", undefined, { authMode: "entra", entraSession: session(msal) });
    expect(await screen.findByText("popup blocked")).toBeInTheDocument();
  });
});
