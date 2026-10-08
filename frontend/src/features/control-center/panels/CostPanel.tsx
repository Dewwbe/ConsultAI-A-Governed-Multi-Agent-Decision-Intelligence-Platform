import { useCost } from "@/api/hooks";
import { BarList, Meter } from "@/components/charts/charts";
import { ErrorState, LoadingState } from "@/components/states/states";
import { Badge } from "@/components/ui/badge";
import { Section, Stat } from "@/features/engagements/panels/common";

const usd = (v: number) => `$${v.toFixed(v < 1 ? 4 : 2)}`;

/** Where the money and tokens went, and how much of each budget this run used. */
export function CostPanel({ workflowId }: { workflowId: string }) {
  const cost = useCost(workflowId);
  if (cost.isPending) return <LoadingState label="Loading the cost breakdown" />;
  if (cost.isError) return <ErrorState error={cost.error} onRetry={() => void cost.refetch()} />;
  const c = cost.data;
  const tokens = c.input_tokens + c.output_tokens;
  return (
    <div className="space-y-8">
      <dl className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Estimated cost" value={usd(c.total_cost_usd)} hint="From the placeholder price table" />
        <Stat label="Tokens" value={tokens.toLocaleString()} hint={`${c.input_tokens.toLocaleString()} in, ${c.output_tokens.toLocaleString()} out`} />
        <Stat
          label="Cost per successful task"
          value={c.cost_per_successful_task === null ? "n/a" : usd(c.cost_per_successful_task)}
          hint={c.successful ? "This run succeeded" : "Not a success (yet): outcome, evidence and safety must all hold"}
        />
        <Stat label="Outcome" value={<Badge variant={c.successful ? "success" : "outline"}>{c.successful ? "Successful" : "Not successful"}</Badge>} />
      </dl>

      <Section title="Cost by agent" description="Model calls only; tools in this system are free.">
        {c.by_agent.length ? (
          <BarList ariaLabel="Cost by agent" format={usd} items={[...c.by_agent].sort((a, b) => b.cost_usd - a.cost_usd).map((a) => ({ label: a.agent, value: a.cost_usd, hint: `${a.calls} calls, ${(a.input_tokens + a.output_tokens).toLocaleString()} tokens` }))} />
        ) : (
          <p className="text-sm text-muted-foreground">No model calls yet.</p>
        )}
      </Section>

      <Section title="Cost by model tier" description="The router picks a tier per task, by risk, budget and data classification.">
        {c.by_model.length ? (
          <BarList ariaLabel="Cost by model" format={usd} color="var(--series-2)" items={[...c.by_model].sort((a, b) => b.cost_usd - a.cost_usd).map((m) => ({ label: `${m.tier} (${m.model})`, value: m.cost_usd, hint: `${m.calls} calls` }))} />
        ) : (
          <p className="text-sm text-muted-foreground">No model calls yet.</p>
        )}
      </Section>

      <Section title="Budget used" description="A run stops and goes to a human before it can exceed any of these.">
        <div className="max-w-xl space-y-4">
          <Meter label="Cost" used={c.budget.cost_usd.used} limit={c.budget.cost_usd.limit} format={usd} />
          <Meter label="Tokens" used={c.budget.tokens.used} limit={c.budget.tokens.limit} format={(v) => v.toLocaleString()} />
          <Meter label="Tool calls" used={c.budget.tool_calls.used} limit={c.budget.tool_calls.limit} format={(v) => String(v)} />
          <Meter label="Time" used={c.budget.duration_sec.used} limit={c.budget.duration_sec.limit} format={(v) => `${v.toFixed(0)} s`} />
        </div>
      </Section>
    </div>
  );
}
