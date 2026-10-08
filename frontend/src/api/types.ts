import type { components } from "./schema";

type S = components["schemas"];

export type Engagement = S["EngagementDetail"];
export type EngagementSummary = S["EngagementSummary"];
export type EngagementList = S["EngagementList"];
export type EngagementRequest = S["EngagementRequest"];
export type EngagementState = S["EngagementState"];
export type EngagementStatus = Engagement["status"];
export type DataClassification = EngagementRequest["data_classification"] & string;

export type EvidenceOut = S["EvidenceOut"];
export type Evidence = S["Evidence"];
export type RetrievalRecord = S["RetrievalRecordOut"];
export type TablesOut = S["TablesOut"];
export type TraceOut = S["TraceOut"];
export type FinancialModel = S["FinancialModel"];
export type Risk = S["Risk"];
export type Option = S["Option"];
export type Recommendation = S["Recommendation"];
export type GuardianDecision = S["GuardianDecision"];
export type ReplayOut = S["ReplayOut"];

/** One server-sent event of an engagement run. */
export interface EngagementEvent {
  id: number;
  type: string;
  ts?: string;
  name?: string;
  kind?: string;
  status?: string;
  latency_ms?: number;
  decision?: string;
  approver?: string;
  risk_level?: string | null;
  recommendation?: string | null;
  halted_reason?: string | null;
  error?: string;
}

/** Events after which the server closes the stream: the run paused or ended. */
export const TERMINAL_EVENTS = ["approval_requested", "run_completed", "run_escalated", "run_failed"] as const;
export const isTerminalEvent = (type: string): boolean => (TERMINAL_EVENTS as readonly string[]).includes(type);
