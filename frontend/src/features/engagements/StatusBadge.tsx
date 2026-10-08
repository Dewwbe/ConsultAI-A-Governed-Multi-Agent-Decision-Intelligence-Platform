import { CircleCheck, CircleX, LoaderCircle, OctagonAlert, ShieldAlert, UserCheck } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { EngagementStatus } from "@/api/types";

interface Meta {
  label: string;
  variant: "default" | "outline" | "success" | "warning" | "destructive";
  Icon: typeof CircleCheck;
  spin?: boolean;
  description: string;
}

/** One place that decides how a status looks. The icon and the word carry the meaning, not just colour. */
export const STATUS_META: Record<EngagementStatus, Meta> = {
  running: { label: "Running", variant: "default", Icon: LoaderCircle, spin: true, description: "Agents are working on it" },
  awaiting_approval: { label: "Awaiting approval", variant: "warning", Icon: UserCheck, description: "A partner must decide" },
  completed: { label: "Completed", variant: "success", Icon: CircleCheck, description: "Finished with a report" },
  rejected: { label: "Rejected", variant: "outline", Icon: CircleX, description: "A partner rejected the recommendation" },
  escalated: { label: "Escalated", variant: "destructive", Icon: ShieldAlert, description: "Stopped for human investigation" },
  failed: { label: "Failed", variant: "destructive", Icon: OctagonAlert, description: "The run crashed" },
};

export const STATUS_ORDER: EngagementStatus[] = ["running", "awaiting_approval", "completed", "rejected", "escalated", "failed"];

export function StatusBadge({ status }: { status: EngagementStatus }) {
  const { label, variant, Icon, spin, description } = STATUS_META[status];
  return (
    <Badge variant={variant} title={description}>
      <Icon aria-hidden="true" className={spin ? "size-3.5 motion-safe:animate-spin" : "size-3.5"} />
      {label}
    </Badge>
  );
}
