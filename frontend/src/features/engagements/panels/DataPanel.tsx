import { useTables } from "@/api/hooks";
import type { Engagement } from "@/api/types";
import { ErrorState, LoadingState } from "@/components/states/states";
import { Badge } from "@/components/ui/badge";
import { DataTable, Num, Pending, Section, Td, Th } from "./common";

const PREVIEW_ROWS = 8;

/** The tables the Data Agent used, the semantic layer it saw, and the SQL it ran (read-only). */
export function DataPanel({ engagement }: { engagement: Engagement }) {
  const running = engagement.status === "running";
  const tables = useTables(engagement.workflow_id);
  if (tables.isPending) return <LoadingState label="Loading data lineage" />;
  if (tables.isError) return <ErrorState error={tables.error} onRetry={() => void tables.refetch()} />;
  const { datasets, table_context: context, queries } = tables.data;
  if (datasets.length === 0 && queries.length === 0) return <Pending running={running} what="data analysis" />;
  const results = engagement.state.analysis_results ?? [];

  return (
    <div className="space-y-8">
      <Section title="Tables used" description="Only tables the Data Agent is permitted to read appear here.">
        <ul className="space-y-3">
          {datasets.map((name) => {
            const t = context[name];
            return (
              <li key={name} className="rounded-lg border bg-card p-4">
                <div className="flex flex-wrap items-center gap-2">
                  <code className="rounded bg-muted px-1.5 py-0.5 text-sm">{name}</code>
                  {t?.owner && <Badge variant="outline">owner: {t.owner}</Badge>}
                  {t?.sensitivity && <Badge variant="outline">{t.sensitivity}</Badge>}
                </div>
                {t?.description && <p className="mt-2 text-sm">{t.description}</p>}
                {t?.columns && (
                  <dl className="mt-3 grid gap-x-6 gap-y-1 text-sm md:grid-cols-2">
                    {Object.entries(t.columns).map(([col, meaning]) => (
                      <div key={col} className="flex gap-2">
                        <dt className="font-mono text-xs">{col}</dt>
                        <dd className="text-muted-foreground">{meaning}</dd>
                      </div>
                    ))}
                  </dl>
                )}
              </li>
            );
          })}
        </ul>
      </Section>

      <Section title="Queries" description="Validated as read-only and permission-checked before they ran.">
        <ul className="space-y-4">
          {queries.map((q, i) => {
            const rows = results.find((r) => r.query === q.query)?.rows ?? [];
            const cols = rows[0] ? Object.keys(rows[0]) : [];
            const purpose = results.find((r) => r.query === q.query)?.purpose;
            return (
              <li key={`${i}-${q.query}`} className="space-y-2">
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  {purpose && <Badge variant="outline">{purpose.replace("_", " ")}</Badge>}
                  <span>{q.row_count} rows</span>
                </div>
                <pre className="overflow-x-auto rounded-lg border bg-muted/50 p-3 text-xs"><code>{q.query}</code></pre>
                {rows.length > 0 && (
                  <DataTable caption={`First rows of query ${i + 1}`}>
                    <thead>
                      <tr>{cols.map((c) => <Th key={c}>{c}</Th>)}</tr>
                    </thead>
                    <tbody>
                      {rows.slice(0, PREVIEW_ROWS).map((row, r) => (
                        <tr key={r}>
                          {cols.map((c) => (
                            <Td key={c}><Num>{typeof row[c] === "number" ? (row[c] as number).toLocaleString(undefined, { maximumFractionDigits: 2 }) : String(row[c])}</Num></Td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </DataTable>
                )}
              </li>
            );
          })}
        </ul>
      </Section>
    </div>
  );
}
