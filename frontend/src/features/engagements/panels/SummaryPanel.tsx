import { AlertTriangle, ShieldCheck } from "lucide-react";
import type { Engagement } from "@/api/types";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { formatMonths, formatPct, formatUsd, formatYears, humanize } from "@/lib/format";
import { Pending, ScoreBar, Section, Stat } from "./common";

/** Scores shown as bars, in a stable order. */
const SCORE_ORDER = [
  "groundedness",
  "citation_validity",
  "constraint_satisfaction",
  "task_adherence",
  "contradiction_free",
  "tool_call_accuracy",
  "completeness",
  "policy_compliance",
];

export function SummaryPanel({ engagement }: { engagement: Engagement }) {
  const { state, status } = engagement;
  const running = status === "running";
  const rec = state.recommendation;
  if (!rec) return <Pending running={running} what="recommendation" />;

  const scores = state.evaluation_scores ?? {};
  const bars = SCORE_ORDER.filter((k) => typeof scores[k] === "number");
  const guardian = [...engagement.guardian_decisions].reverse().find((g) => g.subject === "workflow");

  return (
    <div className="space-y-6">
      {rec.within_constraints === false && (
        <Alert variant="warning">
          <div className="flex gap-3">
            <AlertTriangle aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-warning" />
            <div>
              <AlertTitle>No option satisfies every constraint</AlertTitle>
              <AlertDescription>{(rec.constraint_violations ?? []).join("; ") || "The closest option is shown."}</AlertDescription>
            </div>
          </div>
        </Alert>
      )}

      <Section title={`Recommendation: ${rec.name}`} description={`Option ${rec.id}`}>
        <p className="max-w-3xl text-sm leading-relaxed">{rec.rationale}</p>
        <dl className="grid grid-cols-2 gap-3 md:grid-cols-5">
          <Stat label="Investment" value={formatUsd(rec.cost_usd, true)} />
          <Stat label="ROI" value={formatPct(rec.roi)} />
          <Stat label="NPV" value={formatUsd(rec.npv, true)} />
          <Stat label="Payback" value={formatYears(rec.payback_years)} />
          <Stat label="Launch" value={formatMonths(rec.launch_months)} hint={`Risk: ${rec.risk}`} />
        </dl>
      </Section>

      {rec.assumptions.length > 0 && (
        <Section title="Assumptions" description="Explicit assumptions behind the recommendation, built from tool outputs first.">
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {rec.assumptions.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </Section>
      )}

      {bars.length > 0 && (
        <Section title="Evaluation" description="Scores from the deterministic checks and the LLM judge (0 to 1).">
          <div className="grid gap-x-8 gap-y-3 md:grid-cols-2">
            {bars.map((k) => (
              <ScoreBar key={k} label={humanize(k)} value={scores[k] as number} />
            ))}
          </div>
        </Section>
      )}

      {guardian && (
        <Section title="Guardian" description="Why this run needs, or does not need, a human decision.">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant={guardian.action === "ALLOW" ? "success" : "warning"}>
              <ShieldCheck aria-hidden="true" className="size-3.5" />
              {guardian.action}
            </Badge>
            <Badge variant="outline">{guardian.risk_level} risk</Badge>
            {guardian.source && guardian.source !== "deterministic" && <Badge variant="outline">{humanize(guardian.source)}</Badge>}
          </div>
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {guardian.reasons.map((r) => (
              <li key={r}>{r}</li>
            ))}
          </ul>
        </Section>
      )}

      <Section title="Cost" description="Estimated from the placeholder price table, not a bill.">
        <dl className="grid grid-cols-3 gap-3 md:max-w-xl">
          <Stat label="Estimated cost" value={`$${engagement.budget.cost_usd.toFixed(3)}`} />
          <Stat label="Tokens" value={engagement.budget.tokens.toLocaleString()} />
          <Stat label="Tool calls" value={engagement.budget.tool_calls} />
        </dl>
      </Section>
    </div>
  );
}
