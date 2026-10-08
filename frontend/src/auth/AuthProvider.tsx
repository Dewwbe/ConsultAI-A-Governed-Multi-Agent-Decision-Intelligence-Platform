import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import type { DevIdentity } from "@/api/client";
import { safeStorage } from "@/lib/utils";

export type AuthMode = "dev" | "entra";

/** Roles the dev identity picker offers. `Partner` is the backend's approver role. */
export const DEV_ROLES = ["Partner", "Analyst", "Admin"] as const;

const STORAGE_KEY = "consultai.devIdentity";
const DEFAULT_IDENTITY: DevIdentity = { user: "dev-user", roles: [] };

interface AuthState {
  mode: AuthMode;
  identity: DevIdentity | null;
  /** Changes whenever the identity does; used in query keys so data refetches after a switch. */
  identityKey: string;
  setIdentity: (identity: DevIdentity) => void;
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
}: {
  children: ReactNode;
  mode?: AuthMode;
  initialIdentity?: DevIdentity;
}) {
  const [identity, setState] = useState<DevIdentity>(() => initialIdentity ?? loadIdentity());

  const setIdentity = useCallback((next: DevIdentity) => {
    setState(next);
    safeStorage.set(STORAGE_KEY, JSON.stringify(next));
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      mode,
      // Entra sign-in (MSAL) arrives in F2; until then no identity header is sent in that mode.
      identity: mode === "dev" ? identity : null,
      identityKey: mode === "dev" ? `${identity.user}|${[...identity.roles].sort().join(",")}` : "entra",
      setIdentity,
    }),
    [mode, identity, setIdentity],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
