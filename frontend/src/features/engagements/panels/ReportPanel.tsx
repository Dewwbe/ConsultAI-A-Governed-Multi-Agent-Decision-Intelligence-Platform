import { CheckCircle2, ClipboardCheck, Download, FileText, Gavel, Layers, ListChecks, Printer, TriangleAlert, XCircle } from "lucide-react";
import { Suspense, lazy, useState } from "react";
import type { Engagement } from "@/api/types";
import { EmptyState, LoadingState } from "@/components/states/states";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatMonths, formatPct, formatUsd, formatYears, riskLevel } from "@/lib/format";
import { cn } from "@/lib/utils";
import { DataTable, ScoreBar, SectionCard, Td, Th } from "./common";

// the Markdown renderer is large and only the Report tab needs it
const Markdown = lazy(() => import("react-markdown"));

const DECISION = {
  approve: { label: "Approved", variant: "success", Icon: CheckCircle2 },
  modify: { label: "Approved with changes", variant: "warning", Icon: CheckCircle2 },
  reject: { label: "Rejected", variant: "destructive", Icon: XCircle },
} as const;

const SCORES: [string, string][] = [
  ["groundedness", "Claims supported by evidence"],
  ["citation_validity", "Quotes verified in their sources"],
  ["constraint_satisfaction", "Options meeting your constraints"],
  ["contradiction_free", "Free of contradictions"],
  ["completeness", "Completeness"],
  ["policy_compliance", "Policy compliance"],
];

function Figure({ label, value, emphasis }: { label: string; value: string; emphasis?: boolean }) {
  return (
    <div className={cn("rounded-lg border p-3", emphasis && "border-primary/50 bg-accent-soft")}>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={cn("mt-0.5 text-lg font-semibold tabular-nums", emphasis && "text-primary")}>{value}</dd>
    </div>
  );
}

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/markdown;charset=utf-8" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  a.click();
  URL.revokeObjectURL(url);
}

/**
 * The client-facing report, laid out for a reader: each part in its own card, figures as tiles, options and risks as
 * tables. The text version (what is downloaded) follows at the end. react-markdown renders it without raw HTML, so
 * report text cannot inject markup.
 */
export function ReportPanel({ engagement }: { engagement: Engagement }) {
  const [showText, setShowText] = useState(false);
  const { state } = engagement;
  const report = state.report;
  if (!report) {
    const reason =
      engagement.status === "awaiting_approval"
        ? "The report is written after a partner approves the recommendation."
        : engagement.status === "rejected"
          ? "The recommendation was rejected, so no report was produced."
          : engagement.status === "running"
            ? "It is written once the analysis and any approval are done."
            : "This run ended before a report was produced.";
    return <EmptyState title="No report yet" description={reason} />;
  }
  const rec = state.recommendation;
  const feedback = state.approval_feedback;
  const decision = feedback ? DECISION[feedback.decision as keyof typeof DECISION] : undefined;
  const risks = [...(state.risks ?? [])].sort((a, b) => b.risk_score - a.risk_score).slice(0, 5);
  const scores = state.evaluation_scores ?? {};
  const fileName = `consultai-report-${engagement.workflow_id}.md`;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3 rounded-xl border bg-card p-4 shadow-sm print:border-0 print:shadow-none">
        <div className="space-y-1">
          <p className="text-xs font-medium uppercase tracking-wide text-primary">Engagement report</p>
          <p className="text-lg font-semibold">{state.engagement_spec?.decision_question ?? state.business_problem}</p>
          {decision && (
            <Badge variant={decision.variant}>
              <decision.Icon aria-hidden="true" className="size-3.5" /> {decision.label}
            </Badge>
          )}
        </div>
        <div className="flex gap-2 print:hidden">
          <Button variant="outline" size="sm" onClick={() => download(fileName, report.markdown)}>
            <Download aria-hidden="true" /> Download
          </Button>
          <Button variant="outline" size="sm" onClick={() => window.print()}>
            <Printer aria-hidden="true" /> Print
          </Button>
        </div>
      </div>

      {rec && (
        <SectionCard title="1. Recommendation" description="What we advise, and the figures behind it." icon={<CheckCircle2 className="size-4" />}>
          <div className="space-y-4">
            <div>
              <p className="text-base font-semibold">Option {rec.id}: {rec.name}</p>
              <p className="mt-1 text-sm leading-relaxed">{rec.rationale}</p>
            </div>
            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
              <Figure label="Investment" value={formatUsd(rec.cost_usd, true)} emphasis />
              <Figure label="Return on investment" value={formatPct(rec.roi)} emphasis />
              <Figure label="Net present value" value={formatUsd(rec.npv, true)} />
              <Figure label="Payback" value={formatYears(rec.payback_years)} />
              <Figure label="Time to launch" value={formatMonths(rec.launch_months)} />
              <Figure label="Risk" value={rec.risk} />
            </dl>
          </div>
        </SectionCard>
      )}

      {feedback && decision && (
        <SectionCard title="2. Partner decision" description="The human sign-off this report depends on." icon={<Gavel className="size-4" />}>
          <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[10rem_1fr]">
            <dt className="text-muted-foreground">Decision</dt>
            <dd className="font-medium">{decision.label}</dd>
            {feedback.reason && (
              <>
                <dt className="text-muted-foreground">Reason</dt>
                <dd>{feedback.reason}</dd>
              </>
            )}
            {Object.entries(feedback.changes ?? {}).map(([field, value]) => (
              <div key={field} className="contents">
                <dt className="text-muted-foreground">Edited {field}</dt>
                <dd>{Array.isArray(value) ? value.join("; ") : String(value)}</dd>
              </div>
            ))}
          </dl>
        </SectionCard>
      )}

      {state.options && state.options.length > 0 && (
        <SectionCard title="3. Options considered" description="Every option was checked against your budget and timeline." icon={<Layers className="size-4" />}>
          <DataTable caption="Options considered">
            <thead>
              <tr><Th>Option</Th><Th className="text-right">Investment</Th><Th className="text-right">ROI</Th><Th>Risk</Th><Th>Meets your constraints</Th></tr>
            </thead>
            <tbody>
              {state.options.map((o) => {
                const chosen = rec?.id === o.id;
                const fits = o.within_constraints ?? o.within_budget;
                return (
                  <tr key={o.id} className={cn(chosen && "bg-accent-soft")}>
                    <Td className="font-medium">
                      {o.id}. {o.name}
                      {chosen && <Badge className="ml-2">Recommended</Badge>}
                    </Td>
                    <Td className="text-right tabular-nums">{formatUsd(o.cost_usd, true)}</Td>
                    <Td className="text-right tabular-nums">{formatPct(o.roi)}</Td>
                    <Td>{o.risk}</Td>
                    <Td>{fits ? "Yes" : `No: ${(o.constraint_violations ?? ["outside budget"]).join("; ")}`}</Td>
                  </tr>
                );
              })}
            </tbody>
          </DataTable>
        </SectionCard>
      )}

      {risks.length > 0 && (
        <SectionCard title="4. Key risks" description="Highest first. Score is probability × impact." icon={<TriangleAlert className="size-4" />}>
          <DataTable caption="Key risks">
            <thead><tr><Th>Risk</Th><Th>Score</Th><Th>Mitigation</Th></tr></thead>
            <tbody>
              {risks.map((r) => (
                <tr key={r.risk}>
                  <Td>
                    <div className="font-medium">{r.risk}</div>
                    <div className="text-xs text-muted-foreground">{r.category}{r.requires_human_review ? " · needs a partner's judgement" : ""}</div>
                  </Td>
                  <Td className="whitespace-nowrap tabular-nums">{r.risk_score.toFixed(2)} ({riskLevel(r.risk_score)})</Td>
                  <Td>{r.mitigation}</Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </SectionCard>
      )}

      {rec?.assumptions && rec.assumptions.length > 0 && (
        <SectionCard title="5. Assumptions" description="The recommendation holds only while these hold." icon={<ListChecks className="size-4" />}>
          <ul className="space-y-1.5 text-sm">{rec.assumptions.map((a) => <li key={a} className="ml-5 list-disc">{a}</li>)}</ul>
        </SectionCard>
      )}

      <SectionCard title="6. Quality checks" description="Scored 0 to 1 by automatic checks and an independent reviewer model." icon={<ClipboardCheck className="size-4" />}>
        <div className="grid gap-x-8 gap-y-3 md:grid-cols-2">
          {SCORES.filter(([k]) => typeof scores[k] === "number").map(([k, label]) => (
            <ScoreBar key={k} label={label} value={scores[k] as number} />
          ))}
        </div>
      </SectionCard>

      <SectionCard title="Report text" description="The same report as plain text: exactly what Download saves, for pasting into an email or document." icon={<FileText className="size-4" />}>
        <Button variant="outline" size="sm" aria-expanded={showText} onClick={() => setShowText((v) => !v)}>
          {showText ? "Hide the full text" : "Show the full text"}
        </Button>
        {showText && (
        <article className="mt-4 max-w-3xl space-y-3 text-sm leading-relaxed [&_h1]:text-lg [&_h1]:font-semibold [&_h2]:mt-5 [&_h2]:border-l-4 [&_h2]:border-primary [&_h2]:pl-2 [&_h2]:font-semibold [&_h3]:mt-3 [&_h3]:font-medium [&_hr]:my-4 [&_li]:ml-5 [&_li]:list-disc [&_strong]:font-semibold">
          <Suspense fallback={<LoadingState label="Loading the report" lines={4} />}>
            <Markdown>{report.markdown}</Markdown>
          </Suspense>
        </article>
        )}
      </SectionCard>
    </div>
  );
}
