import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { DevIdentity } from "@/api/client";
import { safeStorage } from "@/lib/utils";
import { createEntraSession, entraConfigFromEnv, type EntraSession, type SignedInAccount } from "./entra";

export type AuthMode = "dev" | "entra";

/** Roles the dev identity picker offers. `Partner` is the backend's approver role. */
export const DEV_ROLES = ["Partner", "Analyst", "Admin"] as const;

const STORAGE_KEY = "consultai.devIdentity";
const DEFAULT_IDENTITY: DevIdentity = { user: "dev-user", roles: [] };

export interface AuthState {
  mode: AuthMode;
  /** False while Entra is finishing a sign-in redirect. Nothing calls the API until it is true. */
  ready: boolean;
  signedIn: boolean;
  /** Dev mode only. */
  identity: DevIdentity | null;
  /** Entra mode only. */
  account: SignedInAccount | null;
  /** Why sign-in cannot work (for example missing configuration). */
  error: string | null;
  /** Changes whenever who you are does; used in query keys so data refetches after a switch. */
  identityKey: string;
  setIdentity: (identity: DevIdentity) => void;
  signIn: () => Promise<void>;
  signOut: () => Promise<void>;
  getToken: () => Promise<string | null>;
}

const AuthContext = createContext<AuthState | null>(null);

function loadIdentity(): DevIdentity {
  const raw = safeStorage.get(STORAGE_KEY);
  if (!raw) return DEFAULT_IDENTITY;
  try {
    const parsed = JSON.parse(raw) as Partial<DevIdentity>;
    if (typeof parsed.user === "string" && Array.isArray(parsed.roles)) {
      return { user: parsed.user, roles: parsed.roles.filter((r): r is string => typeof r === "string") };
    }
  } catch {
    /* corrupt value: fall back to the default */
  }
  return DEFAULT_IDENTITY;
}

export function AuthProvider({
  children,
  mode = import.meta.env.VITE_AUTH_MODE ?? "dev",
  initialIdentity,
  entraSession,
}: {
  children: ReactNode;
  mode?: AuthMode;
  initialIdentity?: DevIdentity;
  /** Injected in tests; in production the session is built from VITE_ENTRA_* settings. */
  entraSession?: EntraSession;
}) {
  const [identity, setState] = useState<DevIdentity>(() => initialIdentity ?? loadIdentity());
  const [account, setAccount] = useState<SignedInAccount | null>(null);
  const [entraReady, setEntraReady] = useState(mode !== "entra");
  const [error, setError] = useState<string | null>(null);
  const session = useRef<EntraSession | null>(entraSession ?? null);

  useEffect(() => {
    if (mode !== "entra") return;
    let cancelled = false;
    (async () => {
      try {
        if (!session.current) {
          const config = entraConfigFromEnv();
          if (!config) throw new Error("Microsoft sign-in is not configured (set VITE_ENTRA_CLIENT_ID and VITE_ENTRA_TENANT_ID).");
          session.current = await createEntraSession(config);
        }
        const signedIn = await session.current.init();
        if (!cancelled) setAccount(signedIn);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : "Sign-in could not start.");
      } finally {
        if (!cancelled) setEntraReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [mode]);

  const setIdentity = useCallback((next: DevIdentity) => {
    setState(next);
    safeStorage.set(STORAGE_KEY, JSON.stringify(next));
  }, []);

  const getToken = useCallback(async () => (mode === "entra" ? (session.current?.getToken() ?? null) : null), [mode]);
  const signIn = useCallback(async () => {
    try {
      await session.current?.signIn();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Sign-in failed.");
    }
  }, []);
  const signOut = useCallback(async () => {
    setAccount(null);
    await session.current?.signOut();
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      mode,
      ready: entraReady,
      signedIn: mode === "dev" ? true : account !== null,
      identity: mode === "dev" ? identity : null,
      account,
      error,
      identityKey: mode === "dev" ? `${identity.user}|${[...identity.roles].sort().join(",")}` : `entra|${account?.id ?? "anonymous"}`,
      setIdentity,
      signIn,
      signOut,
      getToken,
    }),
    [mode, entraReady, account, identity, error, setIdentity, signIn, signOut, getToken],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
