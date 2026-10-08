import { TriangleAlert } from "lucide-react";
import { useState } from "react";
import { usePolicy, usePolicyVersion, usePolicyVersions } from "@/api/hooks";
import type { PolicyOut } from "@/api/types";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DataTable, Section, Td, Th } from "@/features/engagements/panels/common";
import { formatDateTime } from "@/lib/format";
import { Query } from "./Query";

const list = (items: string[]) => (items.length ? items.join(", ") : "none");

function Agents({ policy }: { policy: PolicyOut }) {
  return (
    <DataTable caption="What each agent may do">
      <thead>
        <tr><Th>Agent</Th><Th>Allowed tools</Th><Th>Blocked tools</Th><Th>Needs approval</Th><Th>Tables</Th></tr>
      </thead>
      <tbody>
        {policy.agents.map((a) => (
          <tr key={a.name}>
            <Td className="font-medium">{a.name}</Td>
            <Td>{list(a.allowed_tools)}</Td>
            <Td>{list(a.blocked_tools)}</Td>
            <Td>{list(a.requires_approval)}</Td>
            <Td>{list(a.allowed_tables)}</Td>
          </tr>
        ))}
      </tbody>
    </DataTable>
  );
}

function Versions() {
  const versions = usePolicyVersions();
  const [selected, setSelected] = useState<string | null>(null);
  const content = usePolicyVersion(selected);
  return (
    <Section title="Version history" description="Every policy the platform has run under. A drift flag means the file changed without its version being bumped.">
      <Query q={versions} what="policy versions">
        {(rows) => (
          <>
            {rows.some((v) => v.drift) && (
              <Alert variant="warning">
                <div className="flex gap-3">
                  <TriangleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-warning" />
                  <div>
                    <AlertTitle>Policy drift detected</AlertTitle>
                    <AlertDescription>The policy text changed but its version number did not, so past runs cannot be tied to what was enforced.</AlertDescription>
                  </div>
                </div>
              </Alert>
            )}
            <DataTable caption="Policy versions">
              <thead><tr><Th>Version</Th><Th>First loaded</Th><Th>Hash</Th><Th>State</Th><Th><span className="sr-only">Actions</span></Th></tr></thead>
              <tbody>
                {rows.map((v) => (
                  <tr key={`${v.version}-${v.sha256}`}>
                    <Td className="font-medium">{v.version}</Td>
                    <Td>{formatDateTime(v.loaded_at)}</Td>
                    <Td className="font-mono text-xs">{v.sha256.slice(0, 12)}</Td>
                    <Td>{v.drift ? <Badge variant="warning">Drift</Badge> : <Badge variant="outline">Consistent</Badge>}</Td>
                    <Td>
                      <Button size="sm" variant="outline" onClick={() => setSelected(selected === v.version ? null : v.version)}>
                        {selected === v.version ? "Hide text" : `View text of ${v.version}`}
                      </Button>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </DataTable>
          </>
        )}
      </Query>
      {selected !== null && (
        <Query q={content} what="policy text">
          {(c) => (
            <pre className="max-h-96 overflow-auto rounded-lg border bg-muted/40 p-3 text-xs" tabIndex={0} aria-label={`Policy ${c.version} text`}>
              {c.content}
            </pre>
          )}
        </Query>
      )}
    </Section>
  );
}

export function PolicyTab() {
  const policy = usePolicy();
  return (
    <div className="space-y-8">
      <Query q={policy} what="policy">
        {(p) => (
          <>
            <p className="text-sm">
              In force: <strong>{p.version}</strong> <span className="font-mono text-xs text-muted-foreground">({p.sha256.slice(0, 12)})</span>
            </p>
            <Section title="Agent permissions" description="Default deny: an agent can only use the tools listed for it.">
              <Agents policy={p} />
            </Section>
            <Section title="Quality thresholds" description="Below these scores the Guardian blocks or escalates.">
              <DataTable caption="Quality thresholds">
                <thead><tr><Th>Rule</Th><Th>Value</Th></tr></thead>
                <tbody>{Object.entries(p.thresholds).map(([k, v]) => <tr key={k}><Td>{k}</Td><Td className="tabular-nums">{v}</Td></tr>)}</tbody>
              </DataTable>
            </Section>
            <Section title="Data classification" description="Which model providers may see data of each class, and how personal data is handled before it leaves.">
              <DataTable caption="Provider rules by data classification">
                <thead><tr><Th>Classification</Th><Th>Allowed providers</Th><Th>PII</Th></tr></thead>
                <tbody>
                  {Object.entries(p.data_classification).map(([k, v]) => (
                    <tr key={k}><Td className="font-medium">{k}</Td><Td>{list(v)}</Td><Td>{p.pii[k] ?? "not set"}</Td></tr>
                  ))}
                </tbody>
              </DataTable>
            </Section>
            <Section title="Roles" description="Who may do what. * means any signed-in user.">
              <DataTable caption="Permissions by role">
                <thead><tr><Th>Permission</Th><Th>Roles</Th></tr></thead>
                <tbody>{Object.entries(p.rbac).map(([k, v]) => <tr key={k}><Td>{k}</Td><Td>{list(v)}</Td></tr>)}</tbody>
              </DataTable>
            </Section>
            <Section title="Risk tiers" description="Actions are classified so high-risk ones can require a human.">
              <DataTable caption="Risk tiers">
                <thead><tr><Th>Tier</Th><Th>Actions</Th></tr></thead>
                <tbody>{Object.entries(p.risk_tiers).map(([k, v]) => <tr key={k}><Td className="font-medium">{k}</Td><Td>{list(v)}</Td></tr>)}</tbody>
              </DataTable>
            </Section>
          </>
        )}
      </Query>
      <Versions />
    </div>
  );
}
