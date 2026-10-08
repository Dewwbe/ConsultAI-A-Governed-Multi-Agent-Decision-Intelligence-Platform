import type { Engagement } from "@/api/types";
import { formatMonths, formatPct, formatUsd, formatYears, humanize } from "@/lib/format";
import { DataTable, Num, Pending, Section, Td, Th } from "./common";

/** Every figure here was computed by a tool from warehouse data; the model only proposed the inputs. */
export function FinancialPanel({ engagement }: { engagement: Engagement }) {
  const models = engagement.state.financial_models;
  if (!models || models.length === 0) return <Pending running={engagement.status === "running"} what="financial models" />;
  const first = models[0];
  const a = first?.assumptions;
  const recId = engagement.state.recommendation?.id;

  return (
    <div className="space-y-8">
      {a?.baseline_revenue !== undefined && (
        <p className="rounded-lg border bg-card p-3 text-sm">
          Baseline: <strong>{a.baseline_year}</strong> revenue of <strong>{formatUsd(a.baseline_revenue, true)}</strong> at a{" "}
          <strong>{formatPct(a.baseline_margin ?? 0, 1)}</strong> operating margin, from the data warehouse. Discount rate{" "}
          {formatPct(a.discount_rate)}.
        </p>
      )}

      <Section title="Cases compared" description="The recommended case is marked.">
        <DataTable caption="Financial cases: investment, benefit, ROI, NPV, payback and launch time">
          <thead>
            <tr>
              <Th>Case</Th>
              <Th className="text-right">Investment</Th>
              <Th className="text-right">Revenue uplift</Th>
              <Th className="text-right">Annual benefit</Th>
              <Th className="text-right">ROI</Th>
              <Th className="text-right">NPV</Th>
              <Th className="text-right">Payback</Th>
              <Th className="text-right">Launch</Th>
            </tr>
          </thead>
          <tbody>
            {models.map((m) => (
              <tr key={m.id}>
                <Td>
                  <span className="font-medium">{m.id}</span> {m.label}
                  {m.id === recId && <span className="ml-2 rounded-full bg-primary px-2 py-0.5 text-xs text-primary-foreground">Recommended</span>}
                </Td>
                <Td className="text-right"><Num>{formatUsd(m.investment)}</Num></Td>
                <Td className="text-right"><Num>{m.uplift_pct !== undefined ? formatPct(m.uplift_pct, 1) : "n/a"}</Num></Td>
                <Td className="text-right"><Num>{formatUsd(m.annual_benefit)}</Num></Td>
                <Td className="text-right"><Num>{formatPct(m.roi)}</Num></Td>
                <Td className="text-right"><Num>{formatUsd(m.npv)}</Num></Td>
                <Td className="text-right"><Num>{formatYears(m.payback_years)}</Num></Td>
                <Td className="text-right"><Num>{formatMonths(m.launch_months)}</Num></Td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      </Section>

      <Section title="Scenarios" description="ROI if the benefit comes in lower or higher than planned.">
        <DataTable caption="ROI by scenario for each case">
          <thead>
            <tr>
              <Th>Case</Th>
              {Object.keys(first?.scenarios ?? {}).map((s) => <Th key={s} className="text-right">{humanize(s)}</Th>)}
            </tr>
          </thead>
          <tbody>
            {models.map((m) => (
              <tr key={m.id}>
                <Td><span className="font-medium">{m.id}</span> {m.label}</Td>
                {Object.entries(m.scenarios).map(([s, roi]) => <Td key={s} className="text-right"><Num>{formatPct(roi)}</Num></Td>)}
              </tr>
            ))}
          </tbody>
        </DataTable>
      </Section>

      <Section title="Sensitivity" description="ROI as the annual benefit moves from its planned value.">
        <DataTable caption="ROI sensitivity to the annual benefit for each case">
          <thead>
            <tr>
              <Th>Case</Th>
              {(first?.sensitivity ?? []).map((p) => <Th key={p.benefit_delta} className="text-right">{p.benefit_delta > 0 ? "+" : ""}{formatPct(p.benefit_delta)}</Th>)}
            </tr>
          </thead>
          <tbody>
            {models.map((m) => (
              <tr key={m.id}>
                <Td><span className="font-medium">{m.id}</span> {m.label}</Td>
                {m.sensitivity.map((p) => <Td key={p.benefit_delta} className="text-right"><Num>{formatPct(p.roi)}</Num></Td>)}
              </tr>
            ))}
          </tbody>
        </DataTable>
      </Section>

      <Section title="Why each uplift">
        <ul className="space-y-2 text-sm">
          {models.map((m) => (
            <li key={m.id}>
              <span className="font-medium">{m.id}.</span> {m.benefit_assumption ?? "No justification recorded."}
            </li>
          ))}
        </ul>
      </Section>
    </div>
  );
}
