import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/auth/AuthProvider";
import { useApi } from "./ApiProvider";
import { unwrap } from "./errors";

export function useHealth() {
  const api = useApi();
  return useQuery({
    queryKey: ["health"],
    queryFn: () => unwrap(api.GET("/health")),
    refetchInterval: 30_000,
  });
}

/** The server's view of who you are. Roles shown in the UI come from here, never from local state. */
export function useMe() {
  const api = useApi();
  const { identityKey } = useAuth();
  return useQuery({
    queryKey: ["me", identityKey],
    queryFn: () => unwrap(api.GET("/me")),
  });
}
