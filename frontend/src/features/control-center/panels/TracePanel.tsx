import { CircleAlert, EyeOff } from "lucide-react";
import { useMemo, useState } from "react";
import type { SpanOut, TraceOut } from "@/api/types";
import { EmptyState } from "@/components/states/states";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Legend } from "@/components/charts/charts";
import { formatDuration } from "@/lib/format";
import { cn } from "@/lib/utils";
import { KIND_META, buildWaterfall, isRedacted, kindOf, type SpanKind, type SpanRow } from "../spans";

export function JsonBlock({ value, label }: { value: unknown; label: string }) {
  if (isRedacted(value)) {
    return (
      <p className="flex items-center gap-2 rounded border border-dashed p-2 text-xs text-muted-foreground">
        <EyeOff aria-hidden="true" className="size-3.5" /> {label}: hidden for your role.
      </p>
    );
  }
  return (
    <figure>
      <figcaption className="mb-1 text-xs font-medium text-muted-foreground">{label}</figcaption>
      <pre className="max-h-64 overflow-auto rounded border bg-muted/50 p-2 text-xs">{JSON.stringify(value, null, 2)}</pre>
    </figure>
  );
}

const PAYLOAD_KEYS = ["consultai.tool_arguments", "consultai.tool_result", "consultai.sql", "consultai.query", "consultai.retrieval"];
const HIDDEN_KEYS = new Set(["consultai.workflow_id", ...PAYLOAD_KEYS]);

export function SpanDetail({ span }: { span: SpanOut }) {
  const a = span.attributes;
  const facts: [string, string][] = [
    ["Kind", KIND_META[kindOf(span)].label],
    ["Status", span.status],
    ["Latency", formatDuration(span.latency_ms)],
  ];
  if (a["gen_ai.agent.name"]) facts.push(["Agent", String(a["gen_ai.agent.name"])]);
  if (a["gen_ai.tool.name"]) facts.push(["Tool", String(a["gen_ai.tool.name"])]);
  if (a["gen_ai.request.model"]) facts.push(["Model", `${String(a["gen_ai.request.model"])} (${String(a["consultai.tier"] ?? "")})`]);
  if (a["consultai.prompt"]) facts.push(["Prompt", String(a["consultai.prompt"])]);
  if (a["consultai.stage"]) facts.push(["Attempt", String(a["consultai.stage"])]);
  if (a["gen_ai.usage.input_tokens"] !== undefined) {
    facts.push(["Tokens", `${String(a["gen_ai.usage.input_tokens"])} in, ${String(a["gen_ai.usage.output_tokens"])} out`]);
  }
  if (a["consultai.cost_usd"]) facts.push(["Cost", `$${Number(a["consultai.cost_usd"]).toFixed(5)}`]);
  const payloads = PAYLOAD_KEYS.filter((k) => k in a);
  const rest = Object.entries(a).filter(([k]) => !HIDDEN_KEYS.has(k) && !k.startsWith("gen_ai.") && !["consultai.tier", "consultai.stage", "consultai.prompt", "consultai.cost_usd"].includes(k));
  return (
    <div className="space-y-3 text-sm" aria-label={`Details of ${span.name}`} role="region">
      <h4 className="font-semibold">{span.name}</h4>
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
        {facts.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-muted-foreground">{k}</dt>
            <dd>{v}</dd>
          </div>
        ))}
      </dl>
      {span.error && (
        <p className="flex gap-2 rounded border border-destructive/50 bg-destructive/5 p-2 text-xs text-destructive">
          <CircleAlert aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" /> {span.error}
        </p>
      )}
      {payloads.map((k) => (
        <JsonBlock key={k} value={a[k]} label={k.replace("consultai.", "").replace("_", " ")} />
      ))}
      {rest.length > 0 && <JsonBlock value={Object.fromEntries(rest)} label="other attributes" />}
    </div>
  );
}

function WaterfallRow({ row, total, selected, onSelect }: { row: SpanRow; total: number; selected: boolean; onSelect: () => void }) {
  const { span } = row;
  const kind = kindOf(span);
  const left = (row.offsetMs / total) * 100;
  const width = Math.max(0.6, (row.durationMs / total) * 100);
  return (
    <li>
      {row.idleBeforeMs !== undefined && (
        <p className="py-1 text-center text-xs text-muted-foreground">
          waited {formatDuration(row.idleBeforeMs)} (for a decision)
        </p>
      )}
      <button
        type="button"
        onClick={onSelect}
        aria-pressed={selected}
        className={cn(
          "grid w-full grid-cols-[minmax(9rem,16rem)_1fr_4.5rem] items-center gap-3 rounded px-2 py-1 text-left text-sm hover:bg-muted",
          selected && "bg-secondary",
        )}
      >
        <span className="flex min-w-0 items-center gap-1.5" style={{ paddingLeft: `${row.depth * 14}px` }}>
          <span aria-hidden="true" className="size-2 shrink-0 rounded-sm" style={{ background: KIND_META[kind].color }} />
          <span className="truncate" title={span.name}>
            {span.name}
          </span>
          {span.status === "error" && <CircleAlert aria-label="failed" className="size-3.5 shrink-0 text-destructive" />}
        </span>
        <span aria-hidden="true" className="relative h-4 rounded bg-muted/60">
          <span className="absolute top-0.5 h-3" style={{ left: `${left}%`, width: `${Math.min(width, 100 - left)}%`, background: KIND_META[kind].color, borderRadius: "0 3px 3px 0" }} />
        </span>
        <span className="text-right tabular-nums text-muted-foreground">{formatDuration(row.durationMs)}</span>
      </button>
    </li>
  );
}

/** The run as a waterfall: who ran when, for how long, and what each step did. */
export function TracePanel({ trace }: { trace: TraceOut }) {
  const waterfall = useMemo(() => buildWaterfall(trace.spans), [trace.spans]);
  const kinds = useMemo(() => [...new Set(trace.spans.map((s) => kindOf(s)))] as SpanKind[], [trace.spans]);
  const [hidden, setHidden] = useState<Set<SpanKind>>(new Set());
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const rows = waterfall.rows.filter((r) => !hidden.has(kindOf(r.span)));
  const selected = trace.spans.find((s) => s.span_id === selectedId) ?? null;
  const errors = trace.spans.filter((s) => s.status === "error").length;

  if (trace.spans.length === 0) return <EmptyState title="No spans yet" description="They appear as the run progresses." />;
  return (
    <div className="space-y-4">
      {trace.redaction.payloads_redacted && (
        <Alert variant="warning">
          <AlertTitle>Some detail is hidden from you</AlertTitle>
          <AlertDescription>{trace.redaction.reason ?? "Payloads are withheld for your role."} Timings, statuses and the Guardian&apos;s decisions are still shown.</AlertDescription>
        </Alert>
      )}
      <p className="text-sm text-muted-foreground">
        {trace.span_count} spans, {formatDuration(waterfall.totalMs)} of active time, {trace.tool_calls} tool calls
        {errors > 0 && <span className="text-destructive">, {errors} failed</span>}.
        {trace.redaction.pii_scrubbed > 0 && ` ${trace.redaction.pii_scrubbed} personal identifiers or secrets were masked.`}
      </p>

      <fieldset>
        <legend className="mb-1 text-xs font-medium text-muted-foreground">Show</legend>
        <div className="flex flex-wrap gap-2">
          {kinds.map((k) => (
            <label key={k} className="flex cursor-pointer items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs has-[:checked]:bg-secondary">
              <input
                type="checkbox"
                checked={!hidden.has(k)}
                onChange={() => setHidden((h) => { const n = new Set(h); if (n.has(k)) n.delete(k); else n.add(k); return n; })}
              />
              <span aria-hidden="true" className="size-2 rounded-sm" style={{ background: KIND_META[k].color }} />
              {KIND_META[k].label}
            </label>
          ))}
        </div>
      </fieldset>
      <Legend items={kinds.map((k) => ({ label: KIND_META[k].label, color: KIND_META[k].color }))} />

      <div className="grid gap-4 lg:grid-cols-[3fr_2fr]">
        <ol aria-label="Spans" className="max-h-[32rem] overflow-y-auto rounded-lg border p-1">
          {rows.map((r) => (
            <WaterfallRow key={r.span.span_id} row={r} total={waterfall.totalMs} selected={r.span.span_id === selectedId} onSelect={() => setSelectedId(r.span.span_id)} />
          ))}
        </ol>
        <div className="rounded-lg border p-3">
          {selected ? <SpanDetail span={selected} /> : <p className="text-sm text-muted-foreground">Select a span to inspect it.</p>}
        </div>
      </div>
    </div>
  );
}
