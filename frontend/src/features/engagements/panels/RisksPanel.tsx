import { CircleAlert, TriangleAlert, Info } from "lucide-react";
import type { Engagement } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { formatPct, riskLevel } from "@/lib/format";
import { DataTable, Num, Pending, Td, Th } from "./common";

const LEVEL = {
  High: { variant: "destructive", Icon: CircleAlert },
  Medium: { variant: "warning", Icon: TriangleAlert },
  Low: { variant: "outline", Icon: Info },
} as const;

/** Risks sorted by score (probability x impact). The label comes from the same thresholds as the backend. */
export function RisksPanel({ engagement }: { engagement: Engagement }) {
  const risks = engagement.state.risks;
  if (!risks || risks.length === 0) return <Pending running={engagement.status === "running"} what="risks" />;
  const sorted = [...risks].sort((a, b) => b.risk_score - a.risk_score);

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        Ratings outside a category&apos;s guidance band are adjusted and flagged. Scores are probability &times; impact, computed by the
        system.
      </p>
      <DataTable caption="Risks with probability, impact, score and mitigation">
        <thead>
          <tr>
            <Th>Risk</Th>
            <Th>Category</Th>
            <Th className="text-right">Probability</Th>
            <Th className="text-right">Impact</Th>
            <Th>Score</Th>
            <Th>Mitigation</Th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r) => {
            const level = riskLevel(r.risk_score);
            const { variant, Icon } = LEVEL[level];
            return (
              <tr key={`${r.category}-${r.risk}`}>
                <Td className="max-w-xs">
                  {r.risk}
                  {r.requires_human_review && <span className="ml-2 text-xs text-warning">needs review</span>}
                  {r.calibration && <p className="mt-1 text-xs text-muted-foreground">{r.calibration}</p>}
                  {r.precedents && r.precedents.length > 0 && (
                    <p className="mt-1 text-xs text-muted-foreground">Precedents: {r.precedents.join(", ")}</p>
                  )}
                </Td>
                <Td>{r.category}</Td>
                <Td className="text-right"><Num>{formatPct(r.probability)}</Num></Td>
                <Td className="text-right"><Num>{formatPct(r.impact)}</Num></Td>
                <Td>
                  <Badge variant={variant}>
                    <Icon aria-hidden="true" className="size-3.5" />
                    {level} · {r.risk_score.toFixed(2)}
                  </Badge>
                </Td>
                <Td className="max-w-sm">{r.mitigation}</Td>
              </tr>
            );
          })}
        </tbody>
      </DataTable>
    </div>
  );
}
