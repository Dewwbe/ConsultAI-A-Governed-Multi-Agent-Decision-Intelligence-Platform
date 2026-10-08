import { useState } from "react";
import type { GuardianDecision, SpanOut, TraceOut } from "@/api/types";
import { EmptyState } from "@/components/states/states";
import { Badge } from "@/components/ui/badge";
import { formatDuration } from "@/lib/format";
import { DataTable, Td, Th } from "@/features/engagements/panels/common";
import { attr, toolOutcome, toolSpans, type ToolOutcome } from "../spans";
import { JsonBlock } from "./TracePanel";

const OUTCOME: Record<ToolOutcome, { label: string; variant: "success" | "destructive" | "warning" }> = {
  ok: { label: "Succeeded", variant: "success" },
  blocked: { label: "Blocked by Guardian", variant: "destructive" },
  invalid_arguments: { label: "Invalid arguments", variant: "warning" },
  timeout: { label: "Timed out", variant: "destructive" },
  error: { label: "Failed", variant: "destructive" },
};

export function OutcomeBadge({ outcome }: { outcome: ToolOutcome }) {
  const o = OUTCOME[outcome];
  return <Badge variant={o.variant}>{o.label}</Badge>;
}

function GuardianCard({ decision }: { decision: GuardianDecision }) {
  return (
    <div className="rounded border p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={decision.action === "ALLOW" ? "success" : "destructive"}>{decision.action}</Badge>
        <Badge variant="outline">{decision.risk_level} risk</Badge>
        {decision.policy_version && <span className="text-xs text-muted-foreground">policy {decision.policy_version}</span>}
      </div>
      <ul className="mt-2 list-disc pl-5 text-xs">
        {decision.reasons.map((r) => <li key={r}>{r}</li>)}
      </ul>
    </div>
  );
}

function ToolInspector({ span }: { span: SpanOut }) {
  const errors = attr<string[]>(span, "consultai.schema_errors");
  const decision = attr<GuardianDecision>(span, "consultai.guardian");
  const attempts = attr<number>(span, "consultai.attempts");
  return (
    <div className="space-y-3" role="region" aria-label={`Inspector for ${span.name}`}>
      <h4 className="text-sm font-semibold">{attr<string>(span, "gen_ai.tool.name") ?? span.name}</h4>
      {decision && (
        <div>
          <p className="mb-1 text-xs font-medium text-muted-foreground">Guardian decision for this call</p>
          <GuardianCard decision={decision} />
        </div>
      )}
      <JsonBlock label="arguments" value={attr(span, "consultai.tool_arguments") ?? {}} />
      {errors && errors.length > 0 && (
        <div className="rounded border border-warning/50 bg-warning/5 p-2 text-xs">
          <p className="font-medium">Schema validation errors</p>
          <ul className="list-disc pl-5">{errors.map((e) => <li key={e}>{e}</li>)}</ul>
        </div>
      )}
      {attr(span, "consultai.tool_result") !== undefined && <JsonBlock label="result" value={attr(span, "consultai.tool_result")} />}
      <p className="text-xs text-muted-foreground">
        {attempts !== undefined ? `${attempts} attempt${attempts === 1 ? "" : "s"}` : "not run"}
        {attempts !== undefined && attempts > 1 && " (the first failed with a transient error and was retried)"}
        {" · "}timeout {String(attr(span, "consultai.timeout_ms") ?? "n/a")} ms
        {attr(span, "consultai.slow") ? " · exceeded its timeout" : ""}
      </p>
      {span.error && <p className="text-xs text-destructive">{span.error}</p>}
    </div>
  );
}

export function ToolsPanel({ trace }: { trace: TraceOut }) {
  const tools = toolSpans(trace.spans);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = tools.find((t) => t.span_id === selectedId) ?? null;
  if (tools.length === 0) return <EmptyState title="No tool calls" description="The agents have not called any tools yet." />;
  const counts = tools.reduce<Record<string, number>>((acc, t) => ({ ...acc, [toolOutcome(t)]: (acc[toolOutcome(t)] ?? 0) + 1 }), {});
  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        {tools.length} tool calls: {Object.entries(counts).map(([k, v]) => `${v} ${OUTCOME[k as ToolOutcome].label.toLowerCase()}`).join(", ")}.
      </p>
      <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
        <DataTable caption="Tool calls">
          <thead>
            <tr>
              <Th>Tool</Th>
              <Th>Agent</Th>
              <Th>Outcome</Th>
              <Th className="text-right">Tries</Th>
              <Th className="text-right">Time</Th>
            </tr>
          </thead>
          <tbody>
            {tools.map((t) => (
              <tr key={t.span_id} className={t.span_id === selectedId ? "bg-secondary" : undefined}>
                <Td>
                  <button type="button" className="font-medium underline-offset-2 hover:underline" aria-pressed={t.span_id === selectedId} onClick={() => setSelectedId(t.span_id)}>
                    {attr<string>(t, "gen_ai.tool.name") ?? t.name}
                  </button>
                  {attr<string>(t, "consultai.purpose") && <span className="ml-2 text-xs text-muted-foreground">{attr<string>(t, "consultai.purpose")?.replace("_", " ")}</span>}
                </Td>
                <Td>{attr<string>(t, "gen_ai.agent.name") ?? ""}</Td>
                <Td><OutcomeBadge outcome={toolOutcome(t)} /></Td>
                <Td className="text-right tabular-nums">{attr<number>(t, "consultai.attempts") ?? "-"}</Td>
                <Td className="text-right tabular-nums">{formatDuration(t.latency_ms)}</Td>
              </tr>
            ))}
          </tbody>
        </DataTable>
        <div className="rounded-lg border p-3">
          {selected ? <ToolInspector span={selected} /> : <p className="text-sm text-muted-foreground">Select a tool call to see its arguments, result and the Guardian&apos;s decision.</p>}
        </div>
      </div>
    </div>
  );
}
