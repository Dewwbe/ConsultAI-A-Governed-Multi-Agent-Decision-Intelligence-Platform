import { useMetricsSummary } from "@/api/hooks";
import type { CostBreakdown, Engagement, TraceOut } from "@/api/types";
import { BarList } from "@/components/charts/charts";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Stat } from "@/features/engagements/panels/common";
import { formatDuration } from "@/lib/format";
import { toolOutcome, toolSpans } from "../spans";
import { ActionBadge } from "./GuardianPanel";

const usd = (v: number) => `$${v.toFixed(v < 1 ? 4 : 2)}`;

const KEY_SCORES: [string, string][] = [
  ["groundedness", "min_groundedness"],
  ["constraint_satisfaction", "min_constraint_satisfaction"],
  ["task_adherence", "min_task_adherence"],
  ["tool_call_accuracy", "min_tool_call_accuracy"],
];

function Block({ title, children, to }: { title: string; children: React.ReactNode; to?: string }) {
  return (
    <Card>
      <CardHeader className="flex-row items-baseline justify-between pb-2">
        <CardTitle className="text-sm">{title}</CardTitle>
        {to && <span className="text-xs text-muted-foreground">{to}</span>}
      </CardHeader>
      <CardContent className="space-y-3 text-sm">{children}</CardContent>
    </Card>
  );
}

/** Everything a reviewer needs on one screen: agents, evidence, tool calls, cost, latency, scores and why approval was triggered. */
export function RunSummary({ engagement, trace, cost }: { engagement: Engagement; trace: TraceOut; cost: CostBreakdown | undefined }) {
  const summary = useMetricsSummary();
  const thresholds = summary.data?.thresholds ?? {};
  const spans = trace.spans;
  const agents = spans.filter((s) => s.kind === "agent" || s.kind === "evaluator" || s.kind === "guardian");
  const tools = toolSpans(spans);
  const outcomes = tools.reduce<Record<string, number>>((acc, t) => ({ ...acc, [toolOutcome(t)]: (acc[toolOutcome(t)] ?? 0) + 1 }), {});
  const searches = spans.filter((s) => s.kind === "retrieval").length;
  const claims = engagement.state.research_results ?? [];
  const scores = engagement.state.evaluation_scores ?? {};
  const decision = [...engagement.guardian_decisions].reverse().find((d) => d.subject === "workflow");
  const total = spans.reduce((m, s) => Math.max(m, s.latency_ms), 0);

  return (
    <div className="space-y-4">
      <dl className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Spans" value={trace.span_count} />
        <Stat label="Tool calls" value={trace.tool_calls} hint={trace.tool_errors ? `${trace.tool_errors} failed` : "none failed"} />
        <Stat label="Cost" value={cost ? usd(cost.total_cost_usd) : "n/a"} hint="estimated" />
        <Stat label="Tokens" value={(trace.input_tokens + trace.output_tokens).toLocaleString()} />
        <Stat label="Longest step" value={formatDuration(total)} />
      </dl>
      <div className="grid gap-4 lg:grid-cols-2">
        <Block title="Agents and how long each took">
          <BarList
            ariaLabel="Time per agent"
            format={formatDuration}
            items={agents.filter((a) => a.latency_ms > 0).map((a) => ({ label: a.name, value: a.latency_ms })).sort((a, b) => b.value - a.value)}
          />
        </Block>
        <Block title="Why a human was (or was not) needed">
          {decision ? (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <ActionBadge action={decision.action} />
                <Badge variant="outline">{decision.risk_level} risk</Badge>
                {decision.policy_version && <span className="text-xs text-muted-foreground">policy {decision.policy_version}</span>}
              </div>
              <ul className="list-disc pl-5">{decision.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
            </>
          ) : (
            <p className="text-muted-foreground">The Guardian has not decided yet.</p>
          )}
        </Block>
        <Block title="Evidence retrieved">
          <p>{searches} searches returned {claims.length} verified claims from {new Set(claims.map((c) => c.source)).size} sources.</p>
          <p className="text-xs text-muted-foreground">Open the Retrievals tab to see exactly what the research agent saw.</p>
        </Block>
        <Block title="Tool calls">
          <ul className="flex flex-wrap gap-2">
            {Object.entries(outcomes).map(([k, v]) => <li key={k}><Badge variant={k === "ok" ? "success" : "destructive"}>{v} {k.replace("_", " ")}</Badge></li>)}
          </ul>
        </Block>
        <Block title="Scores against policy">
          <ul className="space-y-1.5">
            {KEY_SCORES.filter(([n]) => typeof scores[n] === "number").map(([n, key]) => {
              const v = scores[n] as number;
              const min = thresholds[key];
              const below = min !== undefined && v < min;
              return (
                <li key={n} className="flex items-center justify-between">
                  <span>{n.replace(/_/g, " ")}</span>
                  <span className="tabular-nums">
                    {v.toFixed(2)} <span className={below ? "text-warning" : "text-muted-foreground"}>{below ? "below minimum" : min !== undefined ? "meets minimum" : ""}</span>
                  </span>
                </li>
              );
            })}
          </ul>
        </Block>
        <Block title="Cost by agent">
          {cost && cost.by_agent.length > 0 ? (
            <BarList ariaLabel="Cost by agent" format={usd} items={[...cost.by_agent].sort((a, b) => b.cost_usd - a.cost_usd).slice(0, 6).map((a) => ({ label: a.agent, value: a.cost_usd }))} />
          ) : (
            <p className="text-muted-foreground">No model calls yet.</p>
          )}
        </Block>
      </div>
    </div>
  );
}
