import type { Engagement } from "@/api/types";
import { Pending, Section } from "./common";

function List({ items }: { items: string[] }) {
  return items.length === 0 ? (
    <p className="text-sm text-muted-foreground">None.</p>
  ) : (
    <ul className="list-disc space-y-1 pl-5 text-sm">
      {items.map((i) => (
        <li key={i}>{i}</li>
      ))}
    </ul>
  );
}

/** The engagement specification Discovery produced from the original question. */
export function SpecPanel({ engagement }: { engagement: Engagement }) {
  const spec = engagement.state.engagement_spec;
  if (!spec) return <Pending running={engagement.status === "running"} what="engagement specification" />;
  return (
    <div className="grid gap-6 md:grid-cols-2">
      <Section title="Decision question">
        <p className="text-sm">{spec.decision_question}</p>
      </Section>
      <Section title="Business objective">
        <p className="text-sm">{spec.business_objective}</p>
      </Section>
      <Section title="Success metrics">
        <List items={spec.success_metrics} />
      </Section>
      <Section title="Client constraints" description="Kept exactly as stated; the model cannot reword them.">
        <List items={spec.constraints} />
      </Section>
      <Section title="Analyses required">
        <List items={spec.required_analysis} />
      </Section>
      <Section title="Data required">
        <List items={spec.required_data} />
      </Section>
      <Section title="Agents assigned">
        <ul className="flex flex-wrap gap-1.5 text-sm">
          {spec.required_agents.map((a) => (
            <li key={a} className="rounded-full border px-2.5 py-0.5">
              {a}
            </li>
          ))}
        </ul>
      </Section>
      {engagement.state.questions && engagement.state.questions.length > 0 && (
        <Section title="Open questions">
          <List items={engagement.state.questions} />
        </Section>
      )}
    </div>
  );
}
