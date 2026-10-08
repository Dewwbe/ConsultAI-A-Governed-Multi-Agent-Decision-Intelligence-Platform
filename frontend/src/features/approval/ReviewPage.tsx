import { Gavel, ShieldAlert } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ConflictError, ForbiddenError, ValidationError } from "@/api/errors";
import { useEngagement, useMe, useSubmitApproval, type ApprovalInput } from "@/api/hooks";
import type { Engagement } from "@/api/types";
import { ErrorState, LoadingState } from "@/components/states/states";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/dialog";
import { formatMonths, formatPct, formatUsd, humanize, riskLevel } from "@/lib/format";
import { StatusBadge } from "../engagements/StatusBadge";
import { Section, Stat } from "../engagements/panels/common";
import { ApprovalHistory } from "./ApprovalHistory";

type Decision = ApprovalInput["decision"];

const DECISIONS: { value: Decision; label: string; hint: string }[] = [
  { value: "approve", label: "Approve", hint: "Accept the recommendation as written. A client-facing report is produced." },
  { value: "modify", label: "Modify", hint: "Accept it with your edits to the rationale or assumptions. Figures cannot be edited." },
  { value: "reject", label: "Reject", hint: "Do not proceed. The engagement ends without a report." },
];

const CONFIRM: Record<Decision, { title: string; button: string; destructive: boolean; body: (changed: string[]) => string }> = {
  approve: {
    title: "Approve this recommendation?",
    button: "Approve",
    destructive: false,
    body: () => "A client-facing report will be produced from it. This cannot be undone.",
  },
  modify: {
    title: "Approve with your changes?",
    button: "Approve with changes",
    destructive: false,
    body: (changed) => `Your edits to ${changed.join(" and ")} will be used in the report. This cannot be undone.`,
  },
  reject: {
    title: "Reject this recommendation?",
    button: "Reject",
    destructive: true,
    body: () => "The engagement ends without a report. This cannot be undone.",
  },
};

const lines = (text: string) => text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
const sameLines = (a: string[], b: string[]) => a.length === b.length && a.every((x, i) => x === b[i]);

function Metrics({ engagement }: { engagement: Engagement }) {
  const { state, budget } = engagement;
  const sc = state.evaluation_scores ?? {};
  const rec = state.recommendation;
  const topRisk = [...(state.risks ?? [])].sort((a, b) => b.risk_score - a.risk_score)[0];
  // "Financial confidence": every figure was computed by a tool, and the recommendation repeats them faithfully.
  const financial =
    typeof sc.tool_call_accuracy === "number" && typeof sc.contradiction_free === "number"
      ? Math.min(sc.tool_call_accuracy, sc.contradiction_free)
      : undefined;
  const score = (v: number | undefined) => (v === undefined ? "n/a" : v.toFixed(2));
  return (
    <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
      <Stat label="Recommendation" value={rec ? rec.name : "n/a"} hint={rec ? `Option ${rec.id}` : undefined} />
      <Stat label="Evidence score" value={score(sc.citation_validity)} hint="Share of claims whose quote was verified in its source" />
      <Stat label="Financial confidence" value={score(financial)} hint="Figures computed by tools, and consistent with the recommendation" />
      <Stat
        label="Risk level"
        value={<span className="capitalize">{state.risk_level ?? "n/a"}</span>}
        hint={topRisk ? `Top risk: ${topRisk.risk} (${riskLevel(topRisk.risk_score)})` : undefined}
      />
      <Stat label="Groundedness" value={score(sc.groundedness)} hint="Judge score, capped by the evidence score" />
      <Stat label="Constraint match" value={score(sc.constraint_satisfaction)} hint="Options that satisfy every stated constraint" />
      <Stat label="Cost so far" value={`$${budget.cost_usd.toFixed(3)}`} hint="Estimated, not a bill" />
      <Stat label="Investment" value={rec ? formatUsd(rec.cost_usd, true) : "n/a"} hint={rec ? `ROI ${formatPct(rec.roi)} · launch ${formatMonths(rec.launch_months)}` : undefined} />
    </dl>
  );
}

function DecisionPanel({ engagement, canApprove, roles }: { engagement: Engagement; canApprove: boolean; roles: string[] }) {
  const navigate = useNavigate();
  const submit = useSubmitApproval(engagement.workflow_id);
  const rec = engagement.state.recommendation;
  const [decision, setDecision] = useState<Decision | null>(null);
  const [reason, setReason] = useState("");
  const [rationale, setRationale] = useState(rec?.rationale ?? "");
  const [assumptions, setAssumptions] = useState((rec?.assumptions ?? []).join("\n"));
  const [errors, setErrors] = useState<{ reason?: string; changes?: string }>({});
  const [confirming, setConfirming] = useState(false);

  if (!canApprove) {
    return (
      <Alert variant="warning">
        <div className="flex gap-3">
          <ShieldAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-warning" />
          <div>
            <AlertTitle>You can review this, but not decide it</AlertTitle>
            <AlertDescription>
              Approving, modifying or rejecting needs the Partner role. You have: {roles.length ? roles.join(", ") : "no roles"}. Ask a partner to decide.
            </AlertDescription>
          </div>
        </div>
      </Alert>
    );
  }

  const changes = (): ApprovalInput["changes"] => {
    const out: NonNullable<ApprovalInput["changes"]> = {};
    if (rec && rationale.trim() && rationale.trim() !== rec.rationale.trim()) out.rationale = rationale.trim();
    if (rec && !sameLines(lines(assumptions), rec.assumptions)) out.assumptions = lines(assumptions);
    return out;
  };

  const review = (e: FormEvent) => {
    e.preventDefault();
    if (!decision) return;
    const next: typeof errors = {};
    if ((decision === "modify" || decision === "reject") && !reason.trim()) next.reason = `Give a reason for ${decision === "modify" ? "the change" : "rejecting"}.`;
    if (decision === "modify" && Object.keys(changes() ?? {}).length === 0) next.changes = "Change the rationale or the assumptions first.";
    setErrors(next);
    if (Object.keys(next).length === 0) {
      submit.reset();
      setConfirming(true);
    }
  };

  const confirm = () => {
    if (!decision) return;
    submit.mutate(
      { decision, reason: reason.trim(), ...(decision === "modify" ? { changes: changes() } : {}) },
      {
        onSuccess: () => void navigate(`/engagements/${engagement.workflow_id}`, { state: { decided: decision } }),
        onSettled: () => setConfirming(false),
      },
    );
  };

  const changedFields = Object.keys(changes() ?? {}).map(humanize);
  const serverError = submit.error;

  return (
    <form onSubmit={review} className="space-y-5" aria-label="Your decision" noValidate>
      <fieldset className="grid gap-3 md:grid-cols-3">
        <legend className="mb-2 text-sm font-medium">Decision</legend>
        {DECISIONS.map((d) => (
          <label key={d.value} className="flex cursor-pointer gap-3 rounded-lg border p-3 has-[:checked]:border-primary has-[:checked]:bg-primary/5">
            <input
              type="radio"
              name="decision"
              value={d.value}
              checked={decision === d.value}
              onChange={() => { setDecision(d.value); setErrors({}); submit.reset(); }}
              className="mt-1"
            />
            <span>
              <span className="block text-sm font-medium">{d.label}</span>
              <span className="block text-xs text-muted-foreground">{d.hint}</span>
            </span>
          </label>
        ))}
      </fieldset>

      {decision === "modify" && (
        <div className="space-y-4 rounded-lg border p-4">
          <p className="text-sm text-muted-foreground">Edit only what you disagree with. Numbers come from tools and cannot be changed here.</p>
          <div className="space-y-1.5">
            <label htmlFor="rationale" className="block text-sm font-medium">Rationale</label>
            <textarea id="rationale" rows={4} className="w-full rounded-md border bg-background px-3 py-2 text-sm" value={rationale} onChange={(e) => setRationale(e.target.value)} />
          </div>
          <div className="space-y-1.5">
            <label htmlFor="assumptions" className="block text-sm font-medium">Assumptions</label>
            <textarea id="assumptions" rows={5} className="w-full rounded-md border bg-background px-3 py-2 text-sm" value={assumptions} onChange={(e) => setAssumptions(e.target.value)} aria-describedby="assumptions-hint" />
            <p id="assumptions-hint" className="text-xs text-muted-foreground">One per line.</p>
          </div>
          {errors.changes && <p role="alert" className="text-sm font-medium text-destructive">{errors.changes}</p>}
        </div>
      )}

      {decision && (
        <div className="space-y-1.5">
          <label htmlFor="reason" className="block text-sm font-medium">
            Reason {decision === "approve" ? "(optional)" : "(required)"}
          </label>
          <textarea
            id="reason"
            rows={3}
            className="w-full rounded-md border bg-background px-3 py-2 text-sm aria-[invalid=true]:border-destructive"
            value={reason}
            onChange={(e) => { setReason(e.target.value); if (errors.reason) setErrors((x) => ({ ...x, reason: undefined })); }}
            aria-invalid={Boolean(errors.reason)}
            aria-describedby={errors.reason ? "reason-error" : undefined}
          />
          {errors.reason && <p id="reason-error" className="text-xs font-medium text-destructive">{errors.reason}</p>}
          <p className="text-xs text-muted-foreground">Recorded with your name in the approval history, and used to calibrate the judge.</p>
        </div>
      )}

      {serverError && <DecisionError error={serverError} onReload={() => void submit.reset()} />}

      <Button type="submit" disabled={!decision || submit.isPending}>
        <Gavel /> Review decision
      </Button>

      {decision && (
        <ConfirmDialog
          open={confirming}
          title={CONFIRM[decision].title}
          confirmLabel={CONFIRM[decision].button}
          destructive={CONFIRM[decision].destructive}
          busy={submit.isPending}
          onConfirm={confirm}
          onCancel={() => setConfirming(false)}
        >
          <p>{CONFIRM[decision].body(changedFields)}</p>
          {reason.trim() && <p className="rounded bg-muted/60 p-2 italic">&ldquo;{reason.trim()}&rdquo;</p>}
        </ConfirmDialog>
      )}
    </form>
  );
}

/** The three errors a decision can hit, each with its own explanation. */
function DecisionError({ error, onReload }: { error: unknown; onReload: () => void }) {
  if (error instanceof ConflictError) {
    return (
      <Alert variant="warning">
        <AlertTitle>This engagement is no longer waiting for a decision</AlertTitle>
        <AlertDescription>{error.detail}. Someone else may already have decided it. The page now shows its current state.</AlertDescription>
        <Button variant="outline" size="sm" className="mt-2" onClick={onReload}>Dismiss</Button>
      </Alert>
    );
  }
  if (error instanceof ForbiddenError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>The server refused your decision</AlertTitle>
        <AlertDescription>{error.detail}. Your role may have changed since this page loaded.</AlertDescription>
      </Alert>
    );
  }
  if (error instanceof ValidationError) {
    return (
      <Alert variant="destructive">
        <AlertTitle>The decision was not accepted</AlertTitle>
        <AlertDescription>{error.detail}</AlertDescription>
      </Alert>
    );
  }
  return <ErrorState error={error} />;
}

export function ReviewPage() {
  const { id = "" } = useParams();
  const query = useEngagement(id);
  const me = useMe();
  const engagement = query.data;

  if (query.isPending || me.isPending) return <LoadingState label="Loading the review" lines={4} />;
  if (query.isError || !engagement) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;

  const rec = engagement.state.recommendation;
  const guardian = [...engagement.guardian_decisions].reverse().find((g) => g.subject === "workflow");
  const awaiting = engagement.status === "awaiting_approval";
  const topRisks = [...(engagement.state.risks ?? [])].sort((a, b) => b.risk_score - a.risk_score).slice(0, 3);

  return (
    <div className="space-y-6">
      <div>
        <Link to={`/engagements/${id}`} className="text-sm text-muted-foreground hover:underline">&larr; Engagement</Link>
        <div className="mt-1 flex flex-wrap items-start justify-between gap-3">
          <h1 className="max-w-3xl text-2xl font-semibold">Review: {engagement.state.business_problem}</h1>
          <StatusBadge status={engagement.status} />
        </div>
        <p className="mt-1 font-mono text-xs text-muted-foreground">{engagement.workflow_id}</p>
      </div>

      {!awaiting && (
        <Alert>
          <AlertTitle>This engagement is not waiting for a decision</AlertTitle>
          <AlertDescription>
            It is {engagement.status.replace("_", " ")}. The review is shown read-only, with its history below.
          </AlertDescription>
        </Alert>
      )}

      {rec ? (
        <>
          <Metrics engagement={engagement} />

          {guardian && (
            <Section title="Why this needs a partner" description="The Guardian's reasons for escalating.">
              <div className="flex flex-wrap gap-2">
                <Badge variant="warning">{guardian.action}</Badge>
                <Badge variant="outline">{guardian.risk_level} risk</Badge>
                {guardian.source && guardian.source !== "deterministic" && <Badge variant="outline">{humanize(guardian.source)}</Badge>}
              </div>
              <ul className="list-disc space-y-1 pl-5 text-sm">
                {guardian.reasons.map((r) => <li key={r}>{r}</li>)}
              </ul>
            </Section>
          )}

          <Card>
            <CardHeader>
              <CardTitle>The recommendation</CardTitle>
              <CardDescription>{rec.name} (option {rec.id})</CardDescription>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              <p className="leading-relaxed">{rec.rationale}</p>
              {rec.within_constraints === false && (
                <Alert variant="warning">
                  <AlertTitle>No option satisfies every constraint</AlertTitle>
                  <AlertDescription>{(rec.constraint_violations ?? []).join("; ")}</AlertDescription>
                </Alert>
              )}
              <div>
                <h3 className="mb-1 font-semibold">Assumptions</h3>
                <ul className="list-disc space-y-1 pl-5">{rec.assumptions.map((a) => <li key={a}>{a}</li>)}</ul>
              </div>
              {topRisks.length > 0 && (
                <div>
                  <h3 className="mb-1 font-semibold">Top risks</h3>
                  <ul className="list-disc space-y-1 pl-5">
                    {topRisks.map((r) => <li key={r.risk}>{r.risk} <span className="text-muted-foreground">({riskLevel(r.risk_score)}, {r.risk_score.toFixed(2)})</span></li>)}
                  </ul>
                </div>
              )}
              <Link className="text-sm underline" to={`/engagements/${id}`}>See the full evidence, data, financials and options</Link>
            </CardContent>
          </Card>
        </>
      ) : (
        <Alert variant="warning">
          <AlertTitle>There is no recommendation to review</AlertTitle>
          <AlertDescription>The run stopped before one was produced.</AlertDescription>
        </Alert>
      )}

      {awaiting && rec && (
        <Card>
          <CardHeader>
            <CardTitle>Your decision</CardTitle>
            <CardDescription>It is recorded with your name and cannot be undone.</CardDescription>
          </CardHeader>
          <CardContent>
            <DecisionPanel engagement={engagement} canApprove={Boolean(me.data?.can_approve)} roles={me.data?.roles ?? []} />
          </CardContent>
        </Card>
      )}

      <Section title="Approval history">
        <ApprovalHistory workflowId={id} />
      </Section>
    </div>
  );
}
