import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "@/auth/AuthProvider";
import { useApi } from "./ApiProvider";
import { unwrap } from "./errors";
import { liveConfig } from "./liveConfig";
import type { paths } from "./schema";
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
    refetchInterval: (q) => (q.state.data?.items.some((i) => i.status === "running" || i.status === "queued") ? 3_000 : false),
  });
}

/** `poll` is switched on when the live stream is unavailable: refetch until the run stops running. */
export function useEngagement(id: string, options: { poll?: boolean } = {}) {
  const api = useApi();
  const { identityKey } = useAuth();
  return useQuery({
    queryKey: ["engagement", id, identityKey],
    queryFn: () => unwrap(api.GET("/engagements/{workflow_id}", { params: { path: { workflow_id: id } } })),
    refetchInterval: (q) => (options.poll && (q.state.data?.status === "running" || q.state.data?.status === "queued") ? liveConfig.pollMs : false),
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

export function useApprovals(id: string) {
  const api = useApi();
  const { identityKey } = useAuth();
  return useQuery({
    queryKey: ["engagement", id, identityKey, "approvals"],
    queryFn: () => unwrap(api.GET("/engagements/{workflow_id}/approvals", { params: { path: { workflow_id: id } } })),
  });
}

export interface ApprovalInput {
  decision: "approve" | "modify" | "reject";
  /** modify only: the rationale and/or assumptions fields */
  changes?: { rationale?: string; assumptions?: string[] };
  reason: string;
}

/** Submit a partner's decision. The server decides who may; a 403/409/422 comes back as a typed error. */
export function useSubmitApproval(id: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ decision, changes, reason }: ApprovalInput) =>
      unwrap(
        api.POST("/engagements/{workflow_id}/approval", {
          params: { path: { workflow_id: id } },
          body: { decision, changes: changes ?? {}, reason },
        }),
      ),
    // success changes the engagement and the list; a 409 means our copy is stale, so refresh it too
    onSettled: () => {
      void qc.invalidateQueries({ queryKey: ["engagement", id] });
      void qc.invalidateQueries({ queryKey: ["engagements"] });
    },
  });
}

export type MetricName = NonNullable<paths["/metrics/timeseries"]["get"]["parameters"]["query"]>["metric"];

/** Aggregated metrics over a window. `since` is an ISO timestamp (omit for all time). */
export function useMetricsSummary(since?: string) {
  const api = useApi();
  const { identityKey } = useAuth();
  return useQuery({
    queryKey: ["metrics", identityKey, "summary", since ?? "all"],
    queryFn: () => unwrap(api.GET("/metrics/summary", { params: { query: { ...(since ? { since } : {}) } } })),
    placeholderData: keepPreviousData,
  });
}

export function useTimeseries(metric: MetricName, since?: string, bucket: "hour" | "day" = "day") {
  const api = useApi();
  const { identityKey } = useAuth();
  return useQuery({
    queryKey: ["metrics", identityKey, "timeseries", metric, bucket, since ?? "all"],
    queryFn: () => unwrap(api.GET("/metrics/timeseries", { params: { query: { metric, bucket, ...(since ? { since } : {}) } } })),
    placeholderData: keepPreviousData,
  });
}

export function useCost(id: string) {
  const api = useApi();
  const { identityKey } = useAuth();
  return useQuery({
    queryKey: ["engagement", id, identityKey, "cost"],
    queryFn: () => unwrap(api.GET("/engagements/{workflow_id}/cost", { params: { path: { workflow_id: id } } })),
  });
}

export function useGuardianLog(id: string) {
  const api = useApi();
  const { identityKey } = useAuth();
  return useQuery({
    queryKey: ["engagement", id, identityKey, "guardian"],
    queryFn: () => unwrap(api.GET("/engagements/{workflow_id}/guardian", { params: { path: { workflow_id: id } } })),
  });
}

/** Governance views refresh slowly: they describe configuration and health, not a live run. */
function useGovernance<T>(key: string, fetcher: () => Promise<T>, refetchMs: number | false = false) {
  const { identityKey } = useAuth();
  return useQuery({ queryKey: ["governance", key, identityKey], queryFn: fetcher, refetchInterval: refetchMs });
}

export function usePolicy() {
  const api = useApi();
  return useGovernance("policy", () => unwrap(api.GET("/governance/policy")));
}

export function usePolicyVersions() {
  const api = useApi();
  return useGovernance("versions", () => unwrap(api.GET("/governance/policy/versions")));
}

export function usePolicyVersion(key: string | null) {
  const api = useApi();
  const { identityKey } = useAuth();
  return useQuery({
    queryKey: ["governance", "version", key, identityKey],
    queryFn: () => unwrap(api.GET("/governance/policy/versions/{key}", { params: { path: { key: key ?? "" } } })),
    enabled: key !== null,
  });
}

export function useTools() {
  const api = useApi();
  return useGovernance("tools", () => unwrap(api.GET("/governance/tools")));
}

export function useProviders() {
  const api = useApi();
  return useGovernance("providers", () => unwrap(api.GET("/governance/providers")), 10_000);
}

export function useBudgets() {
  const api = useApi();
  return useGovernance("budgets", () => unwrap(api.GET("/governance/budgets")), 10_000);
}

export function useDegradation() {
  const api = useApi();
  return useGovernance("degradation", () => unwrap(api.GET("/governance/degradation")), 10_000);
}
