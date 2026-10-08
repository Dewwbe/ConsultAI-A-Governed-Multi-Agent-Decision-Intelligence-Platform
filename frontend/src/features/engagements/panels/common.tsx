import type { HTMLAttributes, ReactNode, TdHTMLAttributes, ThHTMLAttributes } from "react";
import { EmptyState, LoadingState } from "@/components/states/states";
import { cn } from "@/lib/utils";

/** What to show where data has not arrived: a skeleton while the run is working, else an empty state. */
export function Pending({ running, what }: { running: boolean; what: string }) {
  return running ? (
    <LoadingState label={`Waiting for ${what}`} lines={2} />
  ) : (
    <EmptyState title={`No ${what}`} description="This run did not produce it." />
  );
}

/** A scrollable semantic table. The caption names it for screen readers without taking space. */
export function DataTable({ caption, children, className }: { caption: string; children: ReactNode; className?: string }) {
  return (
    <div className={cn("overflow-x-auto rounded-lg border", className)}>
      <table className="w-full min-w-max border-collapse text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        {children}
      </table>
    </div>
  );
}

export function Th({ className, ...props }: ThHTMLAttributes<HTMLTableCellElement>) {
  return <th scope="col" className={cn("border-b bg-muted/60 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground", className)} {...props} />;
}

export function Td({ className, ...props }: TdHTMLAttributes<HTMLTableCellElement>) {
  return <td className={cn("border-b px-3 py-2 align-top last:border-b-0", className)} {...props} />;
}

export function Num({ children }: { children: ReactNode }) {
  return <span className="tabular-nums">{children}</span>;
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="rounded-lg border bg-card p-3">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 text-lg font-semibold tabular-nums">{value}</dd>
      {hint && <dd className="mt-0.5 text-xs text-muted-foreground">{hint}</dd>}
    </div>
  );
}

export function Section({ title, description, children, ...props }: { title: string; description?: string } & HTMLAttributes<HTMLElement>) {
  return (
    <section className="space-y-3" {...props}>
      <div>
        <h2 className="text-sm font-semibold">{title}</h2>
        {description && <p className="text-xs text-muted-foreground">{description}</p>}
      </div>
      {children}
    </section>
  );
}

/** A 0-1 score with its number always visible, so the bar is never the only signal. */
export function ScoreBar({ label, value, low = 0.7 }: { label: string; value: number; low?: number }) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  const weak = value < low;
  return (
    <div>
      <div className="flex items-baseline justify-between text-sm">
        <span>{label}</span>
        <span className={cn("font-medium tabular-nums", weak && "text-warning")}>
          {value.toFixed(2)}
          {weak && <span className="sr-only"> (below the usual minimum)</span>}
        </span>
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden="true">
        <div className={cn("h-full rounded-full", weak ? "bg-warning" : "bg-primary")} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
