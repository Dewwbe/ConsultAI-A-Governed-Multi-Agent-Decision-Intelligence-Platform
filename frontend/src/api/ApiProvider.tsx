import { createContext, useContext, useMemo, useRef, type ReactNode } from "react";
import { useAuth } from "@/auth/AuthProvider";
import { createApi, type Api } from "./client";

const ApiContext = createContext<Api | null>(null);

export function ApiProvider({ children, api }: { children: ReactNode; api?: Api }) {
  const { identity, getToken } = useAuth();
  // The client is built once; it reads the current identity and token on every request.
  const identityRef = useRef(identity);
  identityRef.current = identity;
  const tokenRef = useRef(getToken);
  tokenRef.current = getToken;
  const client = useMemo(
    () => api ?? createApi({ getIdentity: () => identityRef.current, getToken: () => tokenRef.current() }),
    [api],
  );
  return <ApiContext.Provider value={client}>{children}</ApiContext.Provider>;
}

export function useApi(): Api {
  const api = useContext(ApiContext);
  if (!api) throw new Error("useApi must be used inside <ApiProvider>");
  return api;
}
