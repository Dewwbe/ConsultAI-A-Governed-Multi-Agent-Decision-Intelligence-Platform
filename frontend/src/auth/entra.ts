import type { AccountInfo, IPublicClientApplication } from "@azure/msal-browser";

export interface EntraConfig {
  clientId: string;
  tenantId: string;
  /** Scopes for the API. Defaults to the conventional `api://<client-id>/access_as_user`. */
  scopes: string[];
  redirectUri?: string;
}

/** Read the Entra settings from Vite env. Returns null when they are missing, so the UI can say so. */
export function entraConfigFromEnv(env: Record<string, string | undefined> = import.meta.env): EntraConfig | null {
  const clientId = env.VITE_ENTRA_CLIENT_ID;
  const tenantId = env.VITE_ENTRA_TENANT_ID;
  if (!clientId || !tenantId) return null;
  return { clientId, tenantId, scopes: [env.VITE_ENTRA_API_SCOPE || `api://${clientId}/access_as_user`] };
}

export interface SignedInAccount {
  id: string;
  name: string;
  username: string;
}

const toAccount = (a: AccountInfo): SignedInAccount => ({ id: a.homeAccountId, name: a.name || a.username, username: a.username });

/**
 * Thin wrapper over MSAL so the rest of the app depends on four verbs, and tests can supply a fake.
 * Tokens stay in MSAL's own cache (sessionStorage); this app never stores them itself.
 */
export class EntraSession {
  constructor(
    private readonly msal: IPublicClientApplication,
    private readonly scopes: string[],
  ) {}

  /** Finish a redirect sign-in if one just happened, and pick the signed-in account. */
  async init(): Promise<SignedInAccount | null> {
    await this.msal.initialize();
    const result = await this.msal.handleRedirectPromise();
    const account = result?.account ?? this.msal.getActiveAccount() ?? this.msal.getAllAccounts()[0] ?? null;
    if (account) this.msal.setActiveAccount(account);
    return account ? toAccount(account) : null;
  }

  signIn(): Promise<void> {
    return this.msal.loginRedirect({ scopes: this.scopes });
  }

  signOut(): Promise<void> {
    const account = this.msal.getActiveAccount();
    return this.msal.logoutRedirect(account ? { account } : {});
  }

  /** A fresh access token, refreshed silently. If the user must interact again, redirects and returns null. */
  async getToken(): Promise<string | null> {
    const account = this.msal.getActiveAccount();
    if (!account) return null;
    try {
      return (await this.msal.acquireTokenSilent({ scopes: this.scopes, account })).accessToken;
    } catch (e) {
      if ((e as { name?: string }).name === "InteractionRequiredAuthError") {
        await this.msal.acquireTokenRedirect({ scopes: this.scopes, account });
        return null;
      }
      throw e;
    }
  }
}

/** Load MSAL on demand (keeps it out of the main bundle) and build a session. */
export async function createEntraSession(config: EntraConfig): Promise<EntraSession> {
  const { PublicClientApplication } = await import("@azure/msal-browser");
  const msal = new PublicClientApplication({
    auth: {
      clientId: config.clientId,
      authority: `https://login.microsoftonline.com/${config.tenantId}`,
      redirectUri: config.redirectUri ?? window.location.origin,
    },
    // session storage, not local storage: the token disappears when the tab closes
    cache: { cacheLocation: "sessionStorage" },
  });
  return new EntraSession(msal, config.scopes);
}
