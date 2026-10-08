import { EmptyState } from "@/components/states/states";

function Planned({ title, stage, description }: { title: string; stage: string; description: string }) {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">{title}</h1>
      <EmptyState title={`Arrives in ${stage}`} description={description} />
    </div>
  );
}

export const ControlCenter = () => (
  <Planned
    title="Control Center"
    stage="F3"
    description="Traces, tool calls, retrievals, Guardian decisions, cost and quality."
  />
);

export const Governance = () => (
  <Planned
    title="Governance"
    stage="F4"
    description="Policy versions, the tool registry, provider status and budgets."
  />
);
