import { CircleCheck, CircleX } from "lucide-react";
import type { Engagement } from "@/api/types";
import { formatMonths, formatPct, formatUsd, formatYears } from "@/lib/format";
import { DataTable, Num, Pending, Td, Th } from "./common";

/** Options side by side. Constraint compliance is judged by code, and any violation is spelled out. */
export function OptionsPanel({ engagement }: { engagement: Engagement }) {
  const options = engagement.state.options;
  if (!options || options.length === 0) return <Pending running={engagement.status === "running"} what="options" />;
  const recId = engagement.state.recommendation?.id;

  return (
    <DataTable caption="Options compared on cost, return, risk and the client's constraints">
      <thead>
        <tr>
          <Th>Option</Th>
          <Th className="text-right">Cost</Th>
          <Th className="text-right">ROI</Th>
          <Th className="text-right">NPV</Th>
          <Th className="text-right">Payback</Th>
          <Th className="text-right">Launch</Th>
          <Th>Risk</Th>
          <Th>Constraints</Th>
        </tr>
      </thead>
      <tbody>
        {options.map((o) => (
          <tr key={o.id} className={o.id === recId ? "bg-primary/5" : undefined}>
            <Td>
              <span className="font-medium">{o.id}</span> {o.name}
              {o.id === recId && <span className="ml-2 rounded-full bg-primary px-2 py-0.5 text-xs text-primary-foreground">Recommended</span>}
            </Td>
            <Td className="text-right"><Num>{formatUsd(o.cost_usd)}</Num></Td>
            <Td className="text-right"><Num>{formatPct(o.roi)}</Num></Td>
            <Td className="text-right"><Num>{formatUsd(o.npv)}</Num></Td>
            <Td className="text-right"><Num>{formatYears(o.payback_years)}</Num></Td>
            <Td className="text-right"><Num>{formatMonths(o.launch_months)}</Num></Td>
            <Td>{o.risk} <span className="text-muted-foreground">({o.risk_score.toFixed(2)})</span></Td>
            <Td>
              {o.within_constraints === false ? (
                <div className="max-w-xs text-destructive">
                  <span className="flex items-center gap-1 font-medium"><CircleX aria-hidden="true" className="size-4" /> Breaks constraints</span>
                  <ul className="mt-1 list-disc pl-5 text-xs">
                    {(o.constraint_violations ?? []).map((v) => <li key={v}>{v}</li>)}
                  </ul>
                </div>
              ) : (
                <span className="flex items-center gap-1 text-success"><CircleCheck aria-hidden="true" className="size-4" /> Within constraints</span>
              )}
            </Td>
          </tr>
        ))}
      </tbody>
    </DataTable>
  );
}
