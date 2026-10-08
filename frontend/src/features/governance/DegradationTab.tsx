import { useDegradation } from "@/api/hooks";
import { Badge } from "@/components/ui/badge";
import { DataTable, Section, Stat, Td, Th } from "@/features/engagements/panels/common";
import { formatDateTime } from "@/lib/format";
import { Query } from "./Query";

const LEVEL = {
  normal: { label: "Normal", variant: "success", text: "Quality is on target. Runs behave as configured." },
  cautious: { label: "Cautious", variant: "warning", text: "Quality has dipped. Stronger models are used and retrieval widens." },
  restricted: { label: "Restricted", variant: "destructive", text: "Quality has dropped sharply. Every run needs partner review." },
} as const;

const metrics = (m: Record<string, number>) =>
  Object.entries(m).map(([k, v]) => `${k} ${v.toFixed(2)}`).join(", ") || "none";

export function DegradationTab() {
  const q = useDegradation();
  return (
    <Query q={q} what="quality state">
      {({ state, events }) => {
        const l = LEVEL[state.level];
        return (
          <div className="space-y-8">
            <div className="space-y-2">
              <p className="flex items-center gap-2 text-sm">Current level: <Badge variant={l.variant}>{l.label}</Badge></p>
              <p className="text-sm text-muted-foreground">{l.text}</p>
              {state.reasons.length > 0 && <p className="text-sm">Why: {state.reasons.join("; ")}.</p>}
            </div>
            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Stat label="Model tier boost" value={`+${state.actions.tier_boost}`} />
              <Stat label="Retrieval width" value={`x${state.actions.retrieval_k_multiplier}`} />
              <Stat label="Partner review" value={state.actions.require_review ? "Required" : "As usual"} />
              <Stat label="Runs considered" value={state.runs_considered} hint={`since ${formatDateTime(state.since)}`} />
            </dl>
            <Section title="Recent scores" description="Averages over the most recent runs that the level is decided from.">
              <p className="text-sm">{metrics(state.metrics)}</p>
            </Section>
            <Section title="Changes" description="Newest first. The system recovers only after scores clear the limit by a margin, so it does not flap.">
              {events.length === 0 ? (
                <p className="text-sm text-muted-foreground">The level has not changed.</p>
              ) : (
                <DataTable caption="Quality level changes">
                  <thead><tr><Th>When</Th><Th>Change</Th><Th>Reasons</Th><Th>Scores</Th><Th>Runs</Th></tr></thead>
                  <tbody>
                    {events.map((e) => (
                      <tr key={e.ts}>
                        <Td>{formatDateTime(e.ts)}</Td><Td>{e.from_level} to {e.to_level}</Td>
                        <Td className="max-w-xs text-xs">{e.reasons.join("; ") || "none"}</Td>
                        <Td className="text-xs">{metrics(e.metrics)}</Td><Td className="tabular-nums">{e.runs_considered}</Td>
                      </tr>
                    ))}
                  </tbody>
                </DataTable>
              )}
            </Section>
          </div>
        );
      }}
    </Query>
  );
}
