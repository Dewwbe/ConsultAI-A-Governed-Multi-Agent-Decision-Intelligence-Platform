import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/auth/AuthProvider";
import { useApi } from "./ApiProvider";
import { unwrap } from "./errors";
import { liveConfig } from "./liveConfig";
import type { EngagementRequest, EngagementStatus } from "./types";

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

export const PAGE_SIZE = 15;

export function useEngagements(params: { status?: EngagementStatus | undefined; page: number }) {
  const api = useApi();
  const { identityKey } = useAuth();
  return useQuery({
    queryKey: ["engagements", identityKey, params.status ?? "all", params.page],
    queryFn: () =>
      unwrap(
        api.GET("/engagements", {
          params: { query: { ...(params.status ? { status: params.status } : {}), limit: PAGE_SIZE, offset: params.page * PAGE_SIZE } },
        }),
      ),
    placeholderData: keepPreviousData,
    // keep the list fresh while anything on it is still running
    refetchInterval: (q) => (q.state.data?.items.some((i) => i.status === "running") ? 3_000 : false),
  });
}

/** `poll` is switched on when the live stream is unavailable: refetch until the run stops running. */
export function useEngagement(id: string, options: { poll?: boolean } = {}) {
  const api = useApi();
  const { identityKey } = useAuth();
  return useQuery({
    queryKey: ["engagement", id, identityKey],
    queryFn: () => unwrap(api.GET("/engagements/{workflow_id}", { params: { path: { workflow_id: id } } })),
    refetchInterval: (q) => (options.poll && q.state.data?.status === "running" ? liveConfig.pollMs : false),
  });
}

export function useEvidence(id: string, enabled = true) {
  const api = useApi();
  const { identityKey } = useAuth();
  return useQuery({
    queryKey: ["engagement", id, identityKey, "evidence"],
    queryFn: () => unwrap(api.GET("/engagements/{workflow_id}/evidence", { params: { path: { workflow_id: id } } })),
    enabled,
  });
}

export function useTables(id: string, enabled = true) {
  const api = useApi();
  const { identityKey } = useAuth();
  return useQuery({
    queryKey: ["engagement", id, identityKey, "tables"],
    queryFn: () => unwrap(api.GET("/engagements/{workflow_id}/tables", { params: { path: { workflow_id: id } } })),
    enabled,
  });
}

export function useTrace(id: string, options: { enabled?: boolean; poll?: boolean } = {}) {
  const api = useApi();
  const { identityKey } = useAuth();
  return useQuery({
    queryKey: ["engagement", id, identityKey, "trace"],
    queryFn: () => unwrap(api.GET("/control-center/{workflow_id}/trace", { params: { path: { workflow_id: id } } })),
    enabled: options.enabled ?? true,
    refetchInterval: options.poll ? liveConfig.pollMs : false,
  });
}

export function useCreateEngagement() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    // wait=false: the server answers at once with status "running" and keeps working in the background
    mutationFn: (body: EngagementRequest) => unwrap(api.POST("/engagements", { params: { query: { wait: false } }, body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["engagements"] }),
  });
}

export function useReplayRetrieval(workflowId: string) {
  const api = useApi();
  return useMutation({
    mutationFn: (retrievalId: string) =>
      unwrap(
        api.POST("/engagements/{workflow_id}/retrievals/{retrieval_id}/replay", {
          params: { path: { workflow_id: workflowId, retrieval_id: retrievalId } },
        }),
      ),
  });
}
