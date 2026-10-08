import { useId, useState, type ReactNode } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export interface LegendItem {
  label: string;
  color: string;
}

/** A legend is always present for two or more series: colour alone never carries identity. */
export function Legend({ items, className }: { items: LegendItem[]; className?: string }) {
  if (items.length < 2) return null;
  return (
    <ul aria-label="Legend" className={cn("flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground", className)}>
      {items.map((i) => (
        <li key={i.label} className="flex items-center gap-1.5">
          <span aria-hidden="true" className="inline-block h-0.5 w-4 rounded" style={{ background: i.color, height: 3 }} />
          <span className="text-foreground">{i.label}</span>
        </li>
      ))}
    </ul>
  );
}

export interface TableView {
  columns: string[];
  rows: (string | number | null)[][];
}

/** A chart with a title, an optional legend, and a "View as table" switch (the accessible twin of the chart). */
export function ChartCard({
  title,
  description,
  legend,
  table,
  children,
}: {
  title: string;
  description?: string;
  legend?: LegendItem[];
  table: TableView;
  children: ReactNode;
}) {
  const [asTable, setAsTable] = useState(false);
  const id = useId();
  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3">
        <div>
          <CardTitle>{title}</CardTitle>
          {description && <CardDescription>{description}</CardDescription>}
        </div>
        <Button variant="ghost" size="sm" aria-pressed={asTable} aria-controls={id} onClick={() => setAsTable((v) => !v)}>
          {asTable ? "View chart" : "View as table"}
        </Button>
      </CardHeader>
      <CardContent className="space-y-3">
        {!asTable && legend && <Legend items={legend} />}
        <div id={id}>
          {asTable ? (
            <div className="overflow-x-auto rounded-lg border">
              <table className="w-full min-w-max border-collapse text-left text-sm">
                <caption className="sr-only">{title}</caption>
                <thead>
                  <tr>
                    {table.columns.map((c) => (
                      <th key={c} scope="col" className="border-b bg-muted/60 px-3 py-2 text-xs font-semibold text-muted-foreground">
                        {c}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {table.rows.map((row, i) => (
                    <tr key={i}>
                      {row.map((cell, j) => (
                        <td key={j} className="border-b px-3 py-2 tabular-nums last:border-b-0">
                          {cell ?? "n/a"}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            children
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export interface TrendSeries {
  key: string;
  label: string;
  color: string;
}

export interface TrendPoint {
  label: string;
  [series: string]: string | number | null;
}

interface TooltipInput {
  active?: boolean | undefined;
  payload?: ReadonlyArray<{ dataKey?: unknown; value?: unknown }> | undefined;
  label?: string | number | undefined;
}

function TrendTooltip({ active, payload, label, series, format }: TooltipInput & { series: TrendSeries[]; format: (v: number) => string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border bg-card px-3 py-2 text-xs shadow-md">
      <p className="mb-1 font-medium">{label}</p>
      {series.map((s) => {
        const v = payload.find((p) => p.dataKey === s.key)?.value;
        return (
          <p key={s.key} className="flex items-center gap-1.5">
            <span aria-hidden="true" className="inline-block size-2 rounded-full" style={{ background: s.color }} />
            <span className="text-muted-foreground">{s.label}</span>
            <span className="ml-auto pl-3 font-medium tabular-nums">{typeof v === "number" ? format(v) : "n/a"}</span>
          </p>
        );
      })}
    </div>
  );
}

/** Lines for a measure over time: 2px strokes, 8px markers with a surface ring, hairline solid grid, one axis. */
export function TrendChart({
  data,
  series,
  format = (v) => v.toFixed(2),
  domain,
  height = 220,
}: {
  data: TrendPoint[];
  series: TrendSeries[];
  format?: (v: number) => string;
  domain?: [number, number];
  height?: number;
}) {
  return (
    <div role="img" aria-label={`Chart of ${series.map((s) => s.label).join(", ")} over time. A table view is available.`}>
      <ResponsiveContainer width="100%" height={height} initialDimension={{ width: 640, height }}>
        <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
          <CartesianGrid stroke="var(--chart-grid)" strokeWidth={1} vertical={false} />
          <XAxis dataKey="label" stroke="var(--chart-axis)" tick={{ fill: "var(--chart-muted)", fontSize: 11 }} tickLine={false} />
          <YAxis
            stroke="var(--chart-axis)"
            tick={{ fill: "var(--chart-muted)", fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            width={44}
            tickFormatter={format}
            {...(domain ? { domain } : {})}
          />
          <Tooltip
            cursor={{ stroke: "var(--chart-axis)", strokeWidth: 1 }}
            content={(props) => <TrendTooltip {...(props as TooltipInput)} series={series} format={format} />}
          />
          {series.map((s) => (
            <Line
              key={s.key}
              type="monotone"
              dataKey={s.key}
              name={s.label}
              stroke={s.color}
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
              dot={{ r: 4, fill: s.color, stroke: "var(--card)", strokeWidth: 2 }}
              activeDot={{ r: 6, fill: s.color, stroke: "var(--card)", strokeWidth: 2 }}
              connectNulls
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export interface BarItem {
  label: string;
  value: number;
  hint?: string;
}

/** Horizontal bars for a magnitude: one series, sorted, thin (<=24px) with a rounded data end and the value at the tip. */
export function BarList({
  items,
  format,
  color = "var(--series-1)",
  ariaLabel,
}: {
  items: BarItem[];
  format: (v: number) => string;
  color?: string;
  ariaLabel: string;
}) {
  const max = Math.max(...items.map((i) => i.value), 0) || 1;
  return (
    <ul aria-label={ariaLabel} className="space-y-2.5">
      {items.map((i) => (
        <li key={i.label} className="grid grid-cols-[8.5rem_1fr_auto] items-center gap-3 text-sm" title={i.hint}>
          <span className="truncate text-muted-foreground">{i.label}</span>
          <span className="h-4 rounded-r bg-transparent">
            <span
              className="block h-4 max-w-full"
              style={{ width: `${Math.max(1.5, (i.value / max) * 100)}%`, background: color, borderRadius: "0 4px 4px 0" }}
            />
          </span>
          <span className="min-w-14 text-right font-medium tabular-nums">{format(i.value)}</span>
        </li>
      ))}
    </ul>
  );
}

/** A budget meter. The fill takes on severity as it fills; the unfilled track stays a quiet neutral. */
export function Meter({ label, used, limit, format }: { label: string; used: number; limit: number; format: (v: number) => string }) {
  const ratio = limit > 0 ? used / limit : 0;
  const pct = Math.min(100, ratio * 100);
  const state = ratio >= 1 ? "over budget" : ratio >= 0.8 ? "nearly used" : "within budget";
  const color = ratio >= 1 ? "var(--destructive)" : ratio >= 0.8 ? "var(--warning)" : "var(--series-1)";
  return (
    <div>
      <div className="flex items-baseline justify-between text-sm">
        <span>{label}</span>
        <span className="tabular-nums">
          {format(used)} <span className="text-muted-foreground">of {format(limit)}</span>
          <span className="ml-2 text-xs text-muted-foreground">{state}</span>
        </span>
      </div>
      <div
        role="meter"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={limit}
        aria-valuenow={Math.min(used, limit)}
        aria-valuetext={`${format(used)} of ${format(limit)}, ${state}`}
        className="mt-1 h-2 overflow-hidden rounded-full bg-muted"
      >
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
      </div>
    </div>
  );
}
