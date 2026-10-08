import { useState } from "react";
import { useGuardianLog } from "@/api/hooks";
import type { GuardianDecision } from "@/api/types";
import { EmptyState, ErrorState, LoadingState } from "@/components/states/states";
import { Badge } from "@/components/ui/badge";
import { DataTable, Num, Td, Th } from "@/features/engagements/panels/common";
import { humanize } from "@/lib/format";

const ACTION_VARIANT: Record<string, "success" | "warning" | "destructive" | "outline"> = {
  ALLOW: "success", MODIFY: "warning", RETRY: "warning", ESCALATE: "warning", BLOCK: "destructive",
};

export function ActionBadge({ action }: { action: string }) {
  return <Badge variant={ACTION_VARIANT[action] ?? "outline"}>{action}</Badge>;
}

/** The Guardian's decisions with reasons and the policy version that governed each. */
export function GuardianPanel({ workflowId }: { workflowId: string }) {
  const log = useGuardianLog(workflowId);
  const [workflowOnly, setWorkflowOnly] = useState(true);
  if (log.isPending) return <LoadingState label="Loading the Guardian log" />;
  if (log.isError) return <ErrorState error={log.error} onRetry={() => void log.refetch()} />;
  const all: GuardianDecision[] = log.data;
  if (all.length === 0) return <EmptyState title="No Guardian decisions yet" />;
  const decisions = workflowOnly ? all.filter((d) => d.subject === "workflow") : all;
  const trigger = [...all].reverse().find((d) => d.subject === "workflow" && d.action === "ESCALATE");
  const versions = [...new Set(all.map((d) => d.policy_version).filter(Boolean))];
  return (
    <div className="space-y-4">
      {trigger && (
        <div className="rounded-lg border border-warning/50 bg-warning/5 p-4 text-sm">
          <p className="font-semibold">Why approval was triggered</p>
          <ul className="mt-1 list-disc pl-5">{trigger.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
        </div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-3 text-sm">
        <p className="text-muted-foreground">
          {all.length} decisions under policy {versions.length ? versions.join(", ") : "n/a"}.
        </p>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={workflowOnly} onChange={(e) => setWorkflowOnly(e.target.checked)} />
          Recommendation-level decisions only
        </label>
      </div>
      <DataTable caption="Guardian decisions">
        <thead>
          <tr>
            <Th>Subject</Th>
            <Th>Decision</Th>
            <Th>Risk</Th>
            <Th className="text-right">Score</Th>
            <Th>Layer</Th>
            <Th>Policy</Th>
            <Th>Reasons</Th>
          </tr>
        </thead>
        <tbody>
          {decisions.map((d, i) => (
            <tr key={`${d.subject}-${i}`}>
              <Td className="whitespace-nowrap">{d.subject === "workflow" ? "Recommendation" : d.subject}</Td>
              <Td><ActionBadge action={d.action} /></Td>
              <Td className="capitalize">{d.risk_level}</Td>
              <Td className="text-right"><Num>{d.risk_score.toFixed(2)}</Num></Td>
              <Td>{humanize(d.source ?? "deterministic")}</Td>
              <Td className="whitespace-nowrap">{d.policy_version ?? "n/a"}</Td>
              <Td className="max-w-md">
                <ul className="list-disc pl-4">{d.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
                {d.feedback && <p className="mt-1 text-xs text-muted-foreground">Feedback: {d.feedback}</p>}
              </Td>
            </tr>
          ))}
        </tbody>
      </DataTable>
    </div>
  );
}
