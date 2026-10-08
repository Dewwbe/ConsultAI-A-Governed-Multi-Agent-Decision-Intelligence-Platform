import { useApprovals } from "@/api/hooks";
import { EmptyState, ErrorState, LoadingState } from "@/components/states/states";
import { Badge } from "@/components/ui/badge";
import { formatDateTime, humanize } from "@/lib/format";

const DECISION = {
  approve: { label: "Approved", variant: "success" },
  modify: { label: "Modified", variant: "warning" },
  reject: { label: "Rejected", variant: "destructive" },
} as const;

/** Who decided what, when and why. Comes straight from the server's audit-backed history. */
export function ApprovalHistory({ workflowId }: { workflowId: string }) {
  const history = useApprovals(workflowId);
  if (history.isPending) return <LoadingState label="Loading approval history" lines={2} />;
  if (history.isError) return <ErrorState error={history.error} onRetry={() => void history.refetch()} />;
  if (history.data.length === 0) {
    return <EmptyState title="No decisions yet" description="Approvals, modifications and rejections are recorded here with who made them." />;
  }
  return (
    <ol aria-label="Approval history" className="space-y-3">
      {history.data.map((a) => {
        const meta = DECISION[a.decision];
        const changed = Object.keys(a.changes);
        return (
          <li key={`${a.decided_at}-${a.approver_id}`} className="rounded-lg border bg-card p-4 text-sm">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant={meta.variant}>{meta.label}</Badge>
              <span className="font-medium">{a.approver_name}</span>
              <span className="text-muted-foreground">({a.approver_roles.join(", ") || "no roles"})</span>
              <time dateTime={a.decided_at} className="text-muted-foreground">
                {formatDateTime(a.decided_at)}
              </time>
            </div>
            {a.reason && <p className="mt-2">&ldquo;{a.reason}&rdquo;</p>}
            {changed.length > 0 && (
              <div className="mt-2 space-y-1 text-xs text-muted-foreground">
                <p>Changed: {changed.map(humanize).join(", ")}</p>
                {changed.map((k) => (
                  <p key={k} className="whitespace-pre-wrap rounded bg-muted/60 p-2 text-foreground">
                    <span className="font-medium">{humanize(k)}: </span>
                    {Array.isArray(a.changes[k]) ? (a.changes[k] as string[]).join("\n") : String(a.changes[k])}
                  </p>
                ))}
              </div>
            )}
            <p className="mt-2 text-xs text-muted-foreground">Result: {humanize(a.resulting_status)}</p>
          </li>
        );
      })}
    </ol>
  );
}
