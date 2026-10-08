import { ChevronLeft, ChevronRight, Plus } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { PAGE_SIZE, useEngagements } from "@/api/hooks";
import type { EngagementStatus } from "@/api/types";
import { EmptyState, ErrorState, LoadingState } from "@/components/states/states";
import { Button } from "@/components/ui/button";
import { formatDateTime, formatUsd } from "@/lib/format";
import { DataTable, Td, Th } from "./panels/common";
import { STATUS_META, STATUS_ORDER, StatusBadge } from "./StatusBadge";

function parseStatus(value: string | null): EngagementStatus | undefined {
  return STATUS_ORDER.find((s) => s === value);
}

export function EngagementsPage() {
  const [params, setParams] = useSearchParams();
  const status = parseStatus(params.get("status"));
  const page = Math.max(0, Number(params.get("page") ?? 0) || 0);
  const list = useEngagements({ status, page });

  const update = (next: { status?: string | undefined; page?: number }) => {
    const p = new URLSearchParams(params);
    if ("status" in next) {
      if (next.status) p.set("status", next.status);
      else p.delete("status");
      p.delete("page"); // a new filter starts at the first page
    }
    if (next.page !== undefined) {
      if (next.page > 0) p.set("page", String(next.page));
      else p.delete("page");
    }
    setParams(p);
  };

  const total = list.data?.total ?? 0;
  const first = total === 0 ? 0 : page * PAGE_SIZE + 1;
  const last = Math.min(total, (page + 1) * PAGE_SIZE);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">Engagements</h1>
          <p className="mt-1 text-sm text-muted-foreground">Every decision the agents have worked on, newest first.</p>
        </div>
        <Button asChild>
          <Link to="/engagements/new">
            <Plus /> New engagement
          </Link>
        </Button>
      </div>

      <div className="flex items-center gap-2">
        <label htmlFor="status-filter" className="text-sm font-medium">
          Status
        </label>
        <select
          id="status-filter"
          className="h-9 rounded-md border bg-background px-2 text-sm"
          value={status ?? ""}
          onChange={(e) => update({ status: e.target.value || undefined })}
        >
          <option value="">All</option>
          {STATUS_ORDER.map((s) => (
            <option key={s} value={s}>
              {STATUS_META[s].label}
            </option>
          ))}
        </select>
      </div>

      {list.isPending && <LoadingState label="Loading engagements" lines={4} />}
      {list.isError && <ErrorState error={list.error} onRetry={() => void list.refetch()} />}
      {list.isSuccess && list.data.items.length === 0 && (
        <EmptyState
          title={status ? `No ${STATUS_META[status].label.toLowerCase()} engagements` : "No engagements yet"}
          description={status ? "Try another status, or clear the filter." : "Start one to see the agents work."}
          action={
            status ? (
              <Button variant="outline" size="sm" onClick={() => update({ status: undefined })}>
                Clear the filter
              </Button>
            ) : (
              <Button asChild size="sm">
                <Link to="/engagements/new">Start an engagement</Link>
              </Button>
            )
          }
        />
      )}
      {list.isSuccess && list.data.items.length > 0 && (
        <>
          <DataTable caption="Engagements">
            <thead>
              <tr>
                <Th>Question</Th>
                <Th>Status</Th>
                <Th>Recommendation</Th>
                <Th>Risk</Th>
                <Th className="text-right">Cost</Th>
                <Th>Started</Th>
              </tr>
            </thead>
            <tbody>
              {list.data.items.map((e) => (
                <tr key={e.workflow_id} className="hover:bg-muted/40">
                  <Td className="max-w-md">
                    <Link to={`/engagements/${e.workflow_id}`} className="font-medium underline-offset-2 hover:underline">
                      {e.business_problem}
                    </Link>
                    {e.industry && <p className="text-xs text-muted-foreground">{e.industry}</p>}
                  </Td>
                  <Td><StatusBadge status={e.status} /></Td>
                  <Td>{e.recommendation ?? <span className="text-muted-foreground">-</span>}</Td>
                  <Td className="capitalize">{e.risk_level ?? <span className="text-muted-foreground">-</span>}</Td>
                  <Td className="text-right tabular-nums">{formatUsd(e.cost_usd)}</Td>
                  <Td className="whitespace-nowrap text-muted-foreground">{formatDateTime(e.created_at)}</Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
          <nav aria-label="Pagination" className="flex items-center justify-between text-sm">
            <p className="text-muted-foreground" aria-live="polite">
              Showing {first}-{last} of {total}
            </p>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" disabled={page === 0} onClick={() => update({ page: page - 1 })}>
                <ChevronLeft /> Previous
              </Button>
              <Button variant="outline" size="sm" disabled={last >= total} onClick={() => update({ page: page + 1 })}>
                Next <ChevronRight />
              </Button>
            </div>
          </nav>
        </>
      )}
    </div>
  );
}
