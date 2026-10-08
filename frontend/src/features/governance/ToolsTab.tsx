import { useTools } from "@/api/hooks";
import { Badge } from "@/components/ui/badge";
import { DataTable, Td, Th } from "@/features/engagements/panels/common";
import { Query } from "./Query";

const RISK = { low: "outline", medium: "warning", high: "destructive" } as const;
const list = (items: string[]) => (items.length ? items.join(", ") : "none");

export function ToolsTab() {
  const tools = useTools();
  return (
    <Query q={tools} what="tools">
      {(rows) => (
        <div className="space-y-3">
          <p className="text-sm text-muted-foreground">{rows.length} registered tools. Agents can call only what policy lists for them.</p>
          <DataTable caption="Tool registry">
            <thead>
              <tr><Th>Tool</Th><Th>Risk</Th><Th>Timeouts (connect / read / total)</Th><Th>Retries</Th><Th>Approval</Th><Th>Allowed agents</Th><Th>Blocked agents</Th></tr>
            </thead>
            <tbody>
              {rows.map((t) => (
                <tr key={t.name}>
                  <Td>
                    <div className="font-medium">{t.name}</div>
                    <div className="max-w-xs text-xs text-muted-foreground">{t.description}</div>
                  </Td>
                  <Td><Badge variant={RISK[t.risk_level as keyof typeof RISK] ?? "outline"}>{t.risk_level}</Badge></Td>
                  <Td className="tabular-nums">{t.timeouts.connect_ms} / {t.timeouts.read_ms} / {t.timeouts.total_ms} ms</Td>
                  <Td className="tabular-nums">{t.max_retries}</Td>
                  <Td>{t.requires_approval ? "Required" : "No"}</Td>
                  <Td>{list(t.allowed_agents)}</Td>
                  <Td>{list(t.blocked_agents)}</Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </div>
      )}
    </Query>
  );
}
