import { CircleAlert, CircleCheck } from "lucide-react";
import { useMetricsSummary } from "@/api/hooks";
import type { Engagement } from "@/api/types";
import { EmptyState } from "@/components/states/states";
import { Section } from "@/features/engagements/panels/common";
import { humanize } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Each score and the policy minimum it is held to. */
const THRESHOLD_FOR: Record<string, string> = {
  groundedness: "min_groundedness",
  constraint_satisfaction: "min_constraint_satisfaction",
  task_adherence: "min_task_adherence",
  contradiction_free: "min_contradiction_free",
  tool_call_accuracy: "min_tool_call_accuracy",
};
const ORDER = ["groundedness", "citation_validity", "constraint_satisfaction", "task_adherence", "contradiction_free", "tool_call_accuracy", "completeness", "policy_compliance"];

function ScoreRow({ name, value, min }: { name: string; value: number; min: number | undefined }) {
  const below = min !== undefined && value < min;
  return (
    <li className="space-y-1">
      <div className="flex items-center justify-between text-sm">
        <span>{humanize(name)}</span>
        <span className="flex items-center gap-1.5 tabular-nums">
          {min !== undefined &&
            (below ? (
              <span className="flex items-center gap-1 text-xs text-warning"><CircleAlert aria-hidden="true" className="size-3.5" /> below minimum {min.toFixed(2)}</span>
            ) : (
              <span className="flex items-center gap-1 text-xs text-muted-foreground"><CircleCheck aria-hidden="true" className="size-3.5 text-success" /> meets {min.toFixed(2)}</span>
            ))}
          <span className="font-medium">{value.toFixed(2)}</span>
        </span>
      </div>
      <div className="relative h-2 rounded-full bg-muted" aria-hidden="true">
        <div className="h-full rounded-full" style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%`, background: below ? "var(--warning)" : "var(--series-1)" }} />
        {min !== undefined && <div className="absolute -top-0.5 h-3 w-0.5 bg-foreground" style={{ left: `${min * 100}%` }} />}
      </div>
    </li>
  );
}

/** This run's evaluation scores against the policy minimums, and what the evaluators noticed. */
export function QualityPanel({ engagement }: { engagement: Engagement }) {
  const summary = useMetricsSummary();
  const scores = engagement.state.evaluation_scores ?? {};
  const names = ORDER.filter((n) => typeof scores[n] === "number");
  const issues = (engagement.state.failures ?? []).filter((f) => f["type"] === "eval_issue").map((f) => String(f["issue"]));
  const thresholds = summary.data?.thresholds ?? {};
  if (names.length === 0) return <EmptyState title="No evaluation yet" description="Scores appear once the evaluator has run." />;
  const quality = scores["quality"];
  return (
    <div className="space-y-6">
      {typeof quality === "number" && (
        <p className="text-sm">
          Overall quality <strong className="tabular-nums">{quality.toFixed(2)}</strong>
          <span className="text-muted-foreground"> (outcome, evidence, safety and reliability, minus penalties)</span>
        </p>
      )}
      <ul aria-label="Evaluation scores" className={cn("grid gap-x-8 gap-y-4 md:grid-cols-2")}>
        {names.map((n) => {
          const key = THRESHOLD_FOR[n];
          return <ScoreRow key={n} name={n} value={scores[n] as number} min={key ? thresholds[key] : undefined} />;
        })}
      </ul>
      <p className="text-xs text-muted-foreground">The marker on each bar is the policy minimum{summary.data ? ` (policy ${summary.data.policy_version})` : ""}.</p>
      <Section title="What the evaluators noticed">
        {issues.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nothing flagged.</p>
        ) : (
          <ul className="list-disc space-y-1 pl-5 text-sm">{issues.map((i) => <li key={i}>{i}</li>)}</ul>
        )}
      </Section>
    </div>
  );
}
