import { ArrowRight, CheckCircle2, CircleSlash, MessageSquareText, Plus, Sparkles, Users, XCircle } from "lucide-react";
import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import { DEFAULT_API_BASE_URL } from "@/api/client";
import { useEngagements, useHealth, useMe, useMetricsSummary } from "@/api/hooks";
import type { EngagementStatus } from "@/api/types";
import { BarList } from "@/components/charts/charts";
import { EmptyState, ErrorState, LoadingState } from "@/components/states/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { sinceFor } from "@/features/control-center/series";
import { DataTable, SectionCard, Td, Th } from "@/features/engagements/panels/common";
import { STATUS_META, StatusBadge } from "@/features/engagements/StatusBadge";
import { formatDateTime, formatDuration, formatPct } from "@/lib/format";
import { cn } from "@/lib/utils";
import { AGENTS, EXAMPLE_QUESTIONS, GOOD_FITS, NOT_FOR, STAGE_LABEL } from "./content";

const usd = (v: number) => `$${v.toFixed(v < 1 ? 4 : 2)}`;

function initials(name: string) {
  return name.split(/[\s._-]+/).filter(Boolean).slice(0, 2).map((p) => p[0]!.toUpperCase()).join("") || "?";
}

/** The purple band: who you are, what you may do, and the way in. */
function Welcome() {
  const me = useMe();
  return (
    <section aria-label="Your access" className="rounded-2xl bg-gradient-to-br from-brand-from to-brand-to p-6 text-brand-foreground shadow-md">
      {me.isPending && <p className="text-sm">Loading your profile…</p>}
      {me.isError && <p className="text-sm">We could not load your profile.</p>}
      {me.isSuccess && (
        <div className="flex flex-wrap items-center justify-between gap-6">
          <div className="flex items-center gap-4">
            <span aria-hidden="true" className="grid size-16 shrink-0 place-items-center rounded-full bg-white/15 text-xl font-semibold ring-2 ring-white/40">
              {initials(me.data.name)}
            </span>
            <div>
              <p className="text-sm opacity-90">Welcome back</p>
              <p className="text-2xl font-semibold">{me.data.name}</p>
              <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
                {me.data.roles.length === 0 ? (
                  <span className="rounded-full bg-white/15 px-2 py-0.5">No role: read only</span>
                ) : (
                  me.data.roles.map((r) => <span key={r} className="rounded-full bg-white/15 px-2 py-0.5 font-medium">{r}</span>)
                )}
                <span className="inline-flex items-center gap-1 rounded-full bg-white/15 px-2 py-0.5">
                  {me.data.can_approve ? <CheckCircle2 aria-hidden="true" className="size-3.5" /> : <XCircle aria-hidden="true" className="size-3.5" />}
                  {me.data.can_approve ? "Can approve" : "Cannot approve"}
                </span>
              </div>
            </div>
          </div>
          <div className="max-w-md space-y-3">
            <p className="text-sm opacity-95">
              Ask a strategic question. Specialist agents research it, model the numbers and weigh the risks; a Guardian checks
              the work against policy, and a partner signs off anything high-stakes.
            </p>
            <Button asChild className="bg-white text-[#4a2783] hover:bg-white/90">
              <Link to="/engagements/new"><Plus aria-hidden="true" /> New engagement</Link>
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}

function Kpi({ label, value, hint, to }: { label: string; value: string; hint?: string; to?: string }) {
  const body = (
    <>
      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="mt-1 text-3xl font-semibold tabular-nums text-primary">{value}</dd>
      {hint && <dd className="mt-1 text-xs text-muted-foreground">{hint}</dd>}
    </>
  );
  return (
    <div className="rounded-xl border bg-card p-4 shadow-sm">
      {to ? <Link to={to} className="block rounded focus-visible:outline-2">{body}</Link> : body}
    </div>
  );
}

function Summary({ since }: { since: string | undefined }) {
  const summary = useMetricsSummary(since);
  if (summary.isPending) return <LoadingState label="Loading the summary" lines={2} />;
  if (summary.isError) return <ErrorState error={summary.error} onRetry={() => void summary.refetch()} />;
  const s = summary.data;
  if (s.runs === 0) return <EmptyState title="No engagements yet" description="Start one from the questions below and the numbers appear here." />;
  return (
    <dl className="grid grid-cols-2 gap-4 lg:grid-cols-5">
      <Kpi label="Engagements" value={String(s.runs)} hint="in the last 30 days" to="/engagements" />
      <Kpi label="Success rate" value={formatPct(s.economics.success_rate)} hint="outcome, evidence and safety all held" />
      <Kpi label="Awaiting a partner" value={String(s.business.awaiting_approval)} hint="open them to decide" to="/engagements?status=awaiting_approval" />
      <Kpi label="Cost per success" value={s.economics.cost_per_successful_task == null ? "n/a" : usd(s.economics.cost_per_successful_task)} hint={`${usd(s.economics.total_cost_usd)} in total`} />
      <Kpi label="Typical run" value={s.economics.p50_duration_sec == null ? "n/a" : formatDuration(s.economics.p50_duration_sec * 1000)} hint="median, start to finish" />
    </dl>
  );
}

function StatusAndSpend({ since }: { since: string | undefined }) {
  const summary = useMetricsSummary(since);
  const status = useMemo(() => {
    const counts = (summary.data?.by_status ?? {}) as Record<string, number>;
    return Object.entries(counts)
      .map(([k, v]) => ({ label: STATUS_META[k as EngagementStatus]?.label ?? k, value: v }))
      .sort((a, b) => b.value - a.value);
  }, [summary.data]);
  const spend = useMemo(() => {
    const byAgent = new Map((summary.data?.economics.cost_by_agent ?? []).map((a) => [a.agent, a]));
    return AGENTS.filter((a) => byAgent.has(a.key))
      .map((a) => ({ label: a.name, value: byAgent.get(a.key)!.cost_usd, hint: `${byAgent.get(a.key)!.calls} model calls` }))
      .sort((a, b) => b.value - a.value);
  }, [summary.data]);
  if (!summary.data || summary.data.runs === 0) return null;
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <SectionCard title="Engagements by status" description="Where the work stands now.">
        <BarList items={status} format={(v) => String(v)} ariaLabel="Engagements by status" />
      </SectionCard>
      <SectionCard title="Effort by agent" description="Estimated model spend per agent; hover a bar for its call count.">
        {spend.length ? <BarList items={spend} format={usd} ariaLabel="Spend by agent" /> : <p className="text-sm text-muted-foreground">No agent costs recorded yet.</p>}
      </SectionCard>
    </div>
  );
}

function Agents({ since }: { since: string | undefined }) {
  const summary = useMetricsSummary(since);
  const calls = new Map((summary.data?.economics.cost_by_agent ?? []).map((a) => [a.agent, a.calls]));
  return (
    <SectionCard title="The agents that work on every engagement" description="Each has one job and only the tools policy allows it. The Guardian and a partner sit between them and the client." icon={<Users className="size-4" />}>
      <ol className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {AGENTS.map((a, i) => (
          <li key={a.key} className={cn("flex gap-3 rounded-lg border p-3", a.stage === "control" && "border-primary/40 bg-accent-soft")}>
            <span aria-hidden="true" className="grid size-9 shrink-0 place-items-center rounded-lg bg-primary text-primary-foreground">
              <a.Icon className="size-4" />
            </span>
            <div className="min-w-0 space-y-1">
              <p className="flex flex-wrap items-center gap-2">
                <span className="font-semibold">{i + 1}. {a.name}</span>
                <Badge variant="outline">{STAGE_LABEL[a.stage]}</Badge>
              </p>
              <p className="text-sm">{a.role}</p>
              <p className="text-xs text-muted-foreground">
                Uses: {a.uses}
                {calls.get(a.key) ? ` · ${calls.get(a.key)} model calls in 30 days` : ""}
              </p>
            </div>
          </li>
        ))}
      </ol>
    </SectionCard>
  );
}

function Questions() {
  const navigate = useNavigate();
  return (
    <SectionCard title="Questions you can ask" description="Pick one to open the form already filled in. You can edit it before starting." icon={<MessageSquareText className="size-4" />}>
      <div className="space-y-5">
        <ul className="grid gap-3 md:grid-cols-2">
          {EXAMPLE_QUESTIONS.map((q) => (
            <li key={q.form.business_problem}>
              <button
                type="button"
                onClick={() => navigate("/engagements/new", { state: { prefill: q.form } })}
                className="group flex h-full w-full items-start justify-between gap-3 rounded-lg border bg-card p-3 text-left transition-colors hover:border-primary hover:bg-accent-soft focus-visible:outline-2"
              >
                <span className="space-y-1">
                  <span className="block text-xs font-medium uppercase tracking-wide text-primary">{q.category} · {q.form.industry}</span>
                  <span className="block font-medium">{q.form.business_problem}</span>
                  <span className="block text-xs text-muted-foreground">{q.form.constraints.split("\n").join(" · ")}</span>
                </span>
                <ArrowRight aria-hidden="true" className="mt-1 size-4 shrink-0 text-muted-foreground group-hover:text-primary" />
              </button>
            </li>
          ))}
        </ul>
        <div className="grid gap-4 border-t pt-4 md:grid-cols-2">
          <div>
            <h3 className="flex items-center gap-2 text-sm font-semibold"><Sparkles aria-hidden="true" className="size-4 text-success" /> Works best for</h3>
            <ul className="mt-2 space-y-1.5 text-sm">{GOOD_FITS.map((t) => <li key={t} className="ml-5 list-disc">{t}</li>)}</ul>
          </div>
          <div>
            <h3 className="flex items-center gap-2 text-sm font-semibold"><CircleSlash aria-hidden="true" className="size-4 text-muted-foreground" /> Not designed for</h3>
            <ul className="mt-2 space-y-1.5 text-sm">{NOT_FOR.map((t) => <li key={t} className="ml-5 list-disc">{t}</li>)}</ul>
          </div>
        </div>
      </div>
    </SectionCard>
  );
}

function Recent() {
  const recent = useEngagements({ status: undefined, page: 0 });
  const items = recent.data?.items.slice(0, 5) ?? [];
  return (
    <SectionCard title="Recent engagements" actions={<Button asChild variant="ghost" size="sm"><Link to="/engagements">View all</Link></Button>}>
      {recent.isPending && <LoadingState label="Loading engagements" lines={3} />}
      {recent.isError && <ErrorState error={recent.error} onRetry={() => void recent.refetch()} />}
      {recent.isSuccess && items.length === 0 && <p className="text-sm text-muted-foreground">Nothing yet. Start with one of the questions above.</p>}
      {items.length > 0 && (
        <DataTable caption="Recent engagements">
          <thead><tr><Th>Question</Th><Th>Status</Th><Th>Started</Th></tr></thead>
          <tbody>
            {items.map((e) => (
              <tr key={e.workflow_id}>
                <Td><Link className="font-medium hover:underline" to={`/engagements/${e.workflow_id}`}>{e.business_problem}</Link></Td>
                <Td><StatusBadge status={e.status} /></Td>
                <Td className="whitespace-nowrap text-muted-foreground">{formatDateTime(e.created_at)}</Td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
    </SectionCard>
  );
}

function HealthCard() {
  const health = useHealth();
  return (
    <Card>
      <CardHeader>
        <CardTitle>API status</CardTitle>
        <CardDescription className="break-all">{import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL}</CardDescription>
      </CardHeader>
      <CardContent>
        {health.isPending && <LoadingState label="Checking the API" lines={2} />}
        {health.isError && <ErrorState error={health.error} onRetry={() => void health.refetch()} />}
        {health.isSuccess && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
            <dt className="text-muted-foreground">Status</dt>
            <dd className="flex items-center gap-1.5 font-medium">
              <CheckCircle2 aria-hidden="true" className="size-4 text-success" /> {health.data.status}
            </dd>
            <dt className="text-muted-foreground">Model provider</dt>
            <dd className="font-medium">{health.data.llm_provider}</dd>
          </dl>
        )}
      </CardContent>
    </Card>
  );
}

export function Dashboard() {
  const since = useMemo(() => sinceFor("30d"), []);
  return (
    <div className="space-y-6">
      <h1 className="sr-only">Dashboard</h1>
      <Welcome />
      <Summary since={since} />
      <StatusAndSpend since={since} />
      <Agents since={since} />
      <Questions />
      <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
        <Recent />
        <HealthCard />
      </div>
    </div>
  );
}
