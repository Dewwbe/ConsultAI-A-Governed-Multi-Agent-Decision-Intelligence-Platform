import { Ban, CircleAlert, CircleCheck, CircleDashed, CirclePause, LoaderCircle } from "lucide-react";
import { formatDuration } from "@/lib/format";
import { cn } from "@/lib/utils";
import { describeProgress, type PipelineGroup, type PipelineStep, type StepState } from "./pipeline";

const STATE_META: Record<StepState, { label: string; Icon: typeof CircleCheck; tone: string }> = {
  pending: { label: "Pending", Icon: CircleDashed, tone: "text-muted-foreground" },
  running: { label: "Running", Icon: LoaderCircle, tone: "text-primary" },
  done: { label: "Done", Icon: CircleCheck, tone: "text-success" },
  error: { label: "Failed", Icon: CircleAlert, tone: "text-destructive" },
  paused: { label: "Waiting", Icon: CirclePause, tone: "text-warning" },
  skipped: { label: "Skipped", Icon: Ban, tone: "text-muted-foreground" },
};

function Step({ step }: { step: PipelineStep }) {
  const { label, Icon, tone } = STATE_META[step.state];
  return (
    <li
      aria-current={step.state === "running" || step.state === "paused" ? "step" : undefined}
      className={cn(
        "min-w-32 rounded-lg border bg-card px-3 py-2",
        (step.state === "running" || step.state === "paused") && "border-primary ring-1 ring-primary/40",
        step.state === "skipped" && "opacity-60",
      )}
    >
      <div className="flex items-center gap-2">
        <Icon aria-hidden="true" className={cn("size-4 shrink-0", tone, step.state === "running" && "motion-safe:animate-spin")} />
        <span className="text-sm font-medium">{step.label}</span>
        {step.attempts > 1 && (
          <span className="rounded-full bg-secondary px-1.5 text-xs text-secondary-foreground" title={step.note}>
            ×{step.attempts}
          </span>
        )}
      </div>
      <p className={cn("mt-0.5 text-xs", tone)}>
        {label}
        {step.state === "done" && step.latencyMs !== undefined && (
          <span className="text-muted-foreground"> · {formatDuration(step.latencyMs)}</span>
        )}
        {(step.state === "paused" || step.state === "skipped" || step.state === "done") && step.note && step.attempts <= 1 && (
          <span className="text-muted-foreground"> · {step.note}</span>
        )}
      </p>
    </li>
  );
}

/** The agent pipeline as an ordered list; steps that run in parallel sit in one column. */
export function PipelineView({ groups }: { groups: PipelineGroup[] }) {
  return (
    <div>
      <ol aria-label="Pipeline progress" className="flex flex-wrap items-stretch gap-2">
        {groups.map((group) => (
          <li key={group.map((s) => s.key).join("+")} className="flex">
            <ol className="flex flex-col gap-2" aria-label={group.length > 1 ? `Parallel: ${group.map((s) => s.label).join(" and ")}` : undefined}>
              {group.map((step) => (
                <Step key={step.key} step={step} />
              ))}
            </ol>
          </li>
        ))}
      </ol>
      {/* Announce progress to screen readers without moving focus. */}
      <p role="status" aria-live="polite" className="sr-only">
        {describeProgress(groups)}
      </p>
    </div>
  );
}
