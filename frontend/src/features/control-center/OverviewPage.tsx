import { TriangleAlert } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useEngagements, useMetricsSummary, useTimeseries } from "@/api/hooks";
import { BarList, ChartCard, TrendChart } from "@/components/charts/charts";
import { EmptyState, ErrorState, LoadingState } from "@/components/states/states";
import { Alert, AlertTitle } from "@/components/ui/alert";
import { DataTable, Section, Stat, Td, Th } from "@/features/engagements/panels/common";
import { StatusBadge } from "@/features/engagements/StatusBadge";
import { formatDateTime, formatDuration, formatPct } from "@/lib/format";
import { WINDOWS, mergeSeries, sinceFor, type WindowId } from "./series";

const usd = (v: number) => `$${v.toFixed(v < 1 ? 4 : 2)}`;
const pct = (v: number | null | undefined) => (v === null || v === undefined ? "n/a" : formatPct(v));

export function ControlCenterPage() {
  const [windowId, setWindowId] = useState<WindowId>("7d");
  const since = useMemo(() => sinceFor(windowId), [windowId]);
  const bucket = WINDOWS.find((w) => w.id === windowId)?.bucket ?? "day";
  const summary = useMetricsSummary(since);
  const groundedness = useTimeseries("groundedness", since, bucket);
  const tools = useTimeseries("tool_call_accuracy", since, bucket);
  const contradictions = useTimeseries("contradiction_free", since, bucket);
  const cost = useTimeseries("cost_usd", since, bucket);
  const success = useTimeseries("success_rate", since, bucket);
  const recent = useEngagements({ status: undefined, page: 0 });

  const quality = useMemo(
    () => mergeSeries({ groundedness: groundedness.data, tool_call_accuracy: tools.data, contradiction_free: contradictions.data }, bucket),
    [groundedness.data, tools.data, contradictions.data, bucket],
  );
  const costRows = useMemo(() => mergeSeries({ cost: cost.data }, bucket), [cost.data, bucket]);
  const successRows = useMemo(() => mergeSeries({ success: success.data }, bucket), [success.data, bucket]);

  const s = summary.data;
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Control Center</h1>
          <p className="mt-1 text-sm text-muted-foreground">How the agents are doing: quality, cost and safety across runs, and a way into any single run.</p>
        </div>
        <div className="flex items-center gap-2">
          <label htmlFor="window" className="text-sm font-medium">Window</label>
          <select id="window" className="h-9 rounded-md border bg-background px-2 text-sm" value={windowId} onChange={(e) => setWindowId(e.target.value as WindowId)}>
            {WINDOWS.map((w) => <option key={w.id} value={w.id}>{w.label}</option>)}
          </select>
        </div>
      </div>

      {summary.isPending && <LoadingState label="Loading metrics" lines={4} />}
      {summary.isError && <ErrorState error={summary.error} onRetry={() => void summary.refetch()} />}
      {s && s.runs === 0 && <EmptyState title="No runs in this window" description="Start an engagement, or widen the window." />}

      {s && s.runs > 0 && (
        <>
          {s.flags.length > 0 && (
            <Alert variant="warning">
              <div className="flex gap-3">
                <TriangleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-warning" />
                <div>
                  <AlertTitle>Quality is below policy</AlertTitle>
                  <ul className="mt-1 list-disc pl-5 text-sm">{s.flags.map((f) => <li key={f.metric}>{f.message}</li>)}</ul>
                </div>
              </div>
            </Alert>
          )}

          <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Runs" value={s.runs} hint={Object.entries(s.by_status).map(([k, v]) => `${v} ${k.replace("_", " ")}`).join(", ")} />
            <Stat label="Success rate" value={pct(s.economics.success_rate)} hint="Outcome, evidence and safety all hold" />
            <Stat label="Cost per successful task" value={s.economics.cost_per_successful_task === null ? "n/a" : usd(s.economics.cost_per_successful_task)} hint={`${usd(s.economics.total_cost_usd)} spent in total`} />
            <Stat label="Escalation rate" value={pct(s.safety.escalation_rate)} hint="Runs a human had to look at" />
            <Stat label="Approved" value={pct(s.business.approval_rate)} hint={`${s.business.decided} decided, ${s.business.awaiting_approval} waiting`} />
            <Stat label="Modified or rejected" value={`${pct(s.business.modification_rate)} / ${pct(s.business.rejection_rate)}`} />
            <Stat label="Median decision time" value={s.business.median_decision_seconds === null ? "n/a" : formatDuration(s.business.median_decision_seconds * 1000)} />
            <Stat label="Typical run time" value={s.economics.p50_duration_sec === null ? "n/a" : formatDuration(s.economics.p50_duration_sec * 1000)} hint={s.economics.p95_duration_sec === null ? undefined : `slowest 5%: ${formatDuration(s.economics.p95_duration_sec * 1000)}`} />
          </dl>

          <div className="grid gap-4 lg:grid-cols-2">
            <ChartCard
              title="Quality over time"
              description="Higher is better, 0 to 1. Each point averages the runs in that period."
              legend={[
                { label: "Groundedness", color: "var(--series-1)" },
                { label: "Tool accuracy", color: "var(--series-2)" },
                { label: "Contradiction free", color: "var(--series-3)" },
              ]}
              table={{ columns: ["Period", "Groundedness", "Tool accuracy", "Contradiction free"], rows: quality.map((r) => [r.label, fmt(r.groundedness), fmt(r.tool_call_accuracy), fmt(r.contradiction_free)]) }}
            >
              <TrendChart
                data={quality}
                domain={[0, 1]}
                series={[
                  { key: "groundedness", label: "Groundedness", color: "var(--series-1)" },
                  { key: "tool_call_accuracy", label: "Tool accuracy", color: "var(--series-2)" },
                  { key: "contradiction_free", label: "Contradiction free", color: "var(--series-3)" },
                ]}
              />
            </ChartCard>

            <ChartCard title="Cost over time" description="Estimated model spend per period." table={{ columns: ["Period", "Cost"], rows: costRows.map((r) => [r.label, typeof r.cost === "number" ? usd(r.cost) : null]) }}>
              <TrendChart data={costRows} format={usd} series={[{ key: "cost", label: "Cost", color: "var(--series-1)" }]} />
            </ChartCard>

            <ChartCard title="Success rate over time" description="Share of runs that were successful." table={{ columns: ["Period", "Success rate"], rows: successRows.map((r) => [r.label, typeof r.success === "number" ? formatPct(r.success) : null]) }}>
              <TrendChart data={successRows} domain={[0, 1]} format={(v) => formatPct(v)} series={[{ key: "success", label: "Success rate", color: "var(--series-1)" }]} />
            </ChartCard>

            <ChartCard
              title="Where the money goes"
              description="Estimated cost by agent in this window."
              table={{ columns: ["Agent", "Calls", "Tokens", "Cost"], rows: s.economics.cost_by_agent.map((a) => [a.agent, a.calls, a.input_tokens + a.output_tokens, usd(a.cost_usd)]) }}
            >
              <BarList ariaLabel="Cost by agent" format={usd} items={[...s.economics.cost_by_agent].sort((a, b) => b.cost_usd - a.cost_usd).map((a) => ({ label: a.agent, value: a.cost_usd, hint: `${a.calls} calls` }))} />
            </ChartCard>
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            <Section title="Tools and models">
              <ul className="space-y-1 text-sm">
                <li>Tool call success: {pct(s.tool.tool_call_success_rate)}</li>
                <li>Invalid schema on first try: {pct(s.tool.invalid_schema_rate)}</li>
                <li>Repaired by a second model call: {pct(s.tool.llm_repair_rate)}</li>
                <li>Needed a stronger model: {pct(s.tool.llm_fallback_rate)}</li>
                <li>Escalated for bad output: {s.tool.schema_escalations}</li>
              </ul>
            </Section>
            <Section title="Safety">
              <ul className="space-y-1 text-sm">
                <li>Groundedness: {s.safety.groundedness?.toFixed(2) ?? "n/a"}</li>
                <li>Contradiction free: {s.safety.contradiction_free?.toFixed(2) ?? "n/a"}</li>
                <li>Blocked actions: {pct(s.safety.unauthorized_action_rate)} of Guardian decisions</li>
                <li>Runs halted for investigation: {s.safety.runs_halted}</li>
              </ul>
            </Section>
            <Section title="Understanding the task">
              <ul className="space-y-1 text-sm">
                <li>Task adherence: {s.intent.task_adherence?.toFixed(2) ?? "n/a"}</li>
                <li>Constraints met: {s.intent.constraint_satisfaction?.toFixed(2) ?? "n/a"}</li>
                <li>Completeness: {s.intent.completeness?.toFixed(2) ?? "n/a"}</li>
              </ul>
              <p className="text-xs text-muted-foreground">Policy {s.policy_version}</p>
            </Section>
          </div>
        </>
      )}

      <Section title="Recent runs" description="Open one to see its trace, tool calls, retrievals, Guardian decisions, cost and quality.">
        {recent.isPending && <LoadingState label="Loading runs" lines={3} />}
        {recent.isError && <ErrorState error={recent.error} onRetry={() => void recent.refetch()} />}
        {recent.isSuccess && recent.data.items.length === 0 && <EmptyState title="No runs yet" />}
        {recent.isSuccess && recent.data.items.length > 0 && (
          <DataTable caption="Recent runs">
            <thead>
              <tr><Th>Question</Th><Th>Status</Th><Th>Risk</Th><Th className="text-right">Cost</Th><Th>Started</Th></tr>
            </thead>
            <tbody>
              {recent.data.items.map((r) => (
                <tr key={r.workflow_id} className="hover:bg-muted/40">
                  <Td className="max-w-md"><Link className="font-medium underline-offset-2 hover:underline" to={`/control-center/${r.workflow_id}`}>{r.business_problem}</Link></Td>
                  <Td><StatusBadge status={r.status} /></Td>
                  <Td className="capitalize">{r.risk_level ?? "-"}</Td>
                  <Td className="text-right tabular-nums">{usd(r.cost_usd)}</Td>
                  <Td className="whitespace-nowrap text-muted-foreground">{formatDateTime(r.created_at)}</Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        )}
      </Section>
    </div>
  );
}

function fmt(v: string | number | null | undefined): string | null {
  return typeof v === "number" ? v.toFixed(2) : null;
}
