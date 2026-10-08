import { TriangleAlert } from "lucide-react";
import { Link } from "react-router-dom";
import { useBudgets } from "@/api/hooks";
import type { EngagementStatus, RunBudgetUse } from "@/api/types";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { DataTable, Section, Stat, Td, Th } from "@/features/engagements/panels/common";
import { StatusBadge } from "@/features/engagements/StatusBadge";
import { formatDuration, formatPct } from "@/lib/format";
import { Query } from "./Query";

const LABEL = { tokens: "tokens", cost_usd: "cost", tool_calls: "tool calls", duration_sec: "time" } as const;

function Rows({ rows, caption }: { rows: RunBudgetUse[]; caption: string }) {
  return (
    <DataTable caption={caption}>
      <thead><tr><Th>Run</Th><Th>Status</Th><Th>Tokens</Th><Th>Cost</Th><Th>Tool calls</Th><Th>Time</Th><Th>Tightest budget</Th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.workflow_id}>
            <Td><Link className="font-mono text-xs underline" to={`/control-center/${r.workflow_id}`}>{r.workflow_id}</Link></Td>
            <Td><StatusBadge status={r.status as EngagementStatus} /></Td>
            <Td className="tabular-nums">{r.tokens.toLocaleString()}</Td>
            <Td className="tabular-nums">${r.cost_usd.toFixed(4)}</Td>
            <Td className="tabular-nums">{r.tool_calls}</Td>
            <Td className="tabular-nums">{formatDuration(r.duration_sec * 1000)}</Td>
            <Td>
              <span className="tabular-nums">{formatPct(r.utilization)}</span> of {LABEL[r.tightest]}
              {r.near_limit && <Badge variant="warning" className="ml-2">Near limit</Badge>}
            </Td>
          </tr>
        ))}
      </tbody>
    </DataTable>
  );
}

export function BudgetsTab() {
  const budgets = useBudgets();
  return (
    <Query q={budgets} what="budgets">
      {(b) => (
        <div className="space-y-8">
          {b.near_limit_count > 0 && (
            <Alert variant="warning">
              <div className="flex gap-3">
                <TriangleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-warning" />
                <div>
                  <AlertTitle>{b.near_limit_count} run{b.near_limit_count === 1 ? " is" : "s are"} near a budget limit</AlertTitle>
                  <AlertDescription>A run that hits a limit stops and escalates instead of continuing.</AlertDescription>
                </div>
              </div>
            </Alert>
          )}
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Tokens per run" value={b.defaults.max_tokens.toLocaleString()} />
            <Stat label="Cost per run" value={`$${b.defaults.max_cost_usd.toFixed(2)}`} />
            <Stat label="Tool calls per run" value={b.defaults.max_tool_calls} />
            <Stat label="Time per run" value={formatDuration(b.defaults.max_duration_sec * 1000)} />
          </dl>
          <Section title="Running now">
            {b.running.length === 0 ? <p className="text-sm text-muted-foreground">Nothing is running.</p> : <Rows rows={b.running} caption="Budget use of running engagements" />}
          </Section>
          <Section title="Recent runs" description="Newest first.">
            {b.recent.length === 0 ? <p className="text-sm text-muted-foreground">No finished runs yet.</p> : <Rows rows={b.recent} caption="Budget use of recent engagements" />}
          </Section>
        </div>
      )}
    </Query>
  );
}
