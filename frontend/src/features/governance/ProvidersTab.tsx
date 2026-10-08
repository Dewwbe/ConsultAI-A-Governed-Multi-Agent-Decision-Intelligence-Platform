import { useProviders } from "@/api/hooks";
import { Badge } from "@/components/ui/badge";
import { DataTable, Section, Stat, Td, Th } from "@/features/engagements/panels/common";
import { formatDateTime } from "@/lib/format";
import { Query } from "./Query";

const BREAKER = {
  closed: { label: "Healthy", variant: "success" },
  half_open: { label: "Probing", variant: "warning" },
  open: { label: "Tripped", variant: "destructive" },
} as const;

const share = (available: number, capacity: number) => (capacity > 0 ? `${Math.round(((capacity - available) / capacity) * 100)}%` : "n/a");

export function ProvidersTab() {
  const providers = useProviders();
  return (
    <Query q={providers} what="providers">
      {(p) => (
        <div className="space-y-8">
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Runs executing" value={`${p.scheduler.running} / ${p.scheduler.max_concurrent}`} />
            <Stat label="Runs queued" value={`${p.scheduler.queued} / ${p.scheduler.max_queued}`} hint="New runs get a 429 when full" />
          </dl>
          <Section title="Providers" description="A tripped breaker stops calls to a failing provider; failover only goes to providers the data class allows.">
            <DataTable caption="Provider health and limits">
              <thead>
                <tr><Th>Provider</Th><Th>Breaker</Th><Th>May see</Th><Th>Request use</Th><Th>Token use</Th><Th>In flight</Th><Th>Last error</Th></tr>
              </thead>
              <tbody>
                {p.providers.map((v) => {
                  const b = BREAKER[v.breaker.state];
                  return (
                    <tr key={v.name}>
                      <Td>
                        <span className="font-medium">{v.name}</span>
                        {v.primary && <Badge variant="default" className="ml-2">Primary</Badge>}
                        {!v.configured && <span className="ml-2 text-xs text-muted-foreground">not configured</span>}
                      </Td>
                      <Td>
                        <Badge variant={b.variant}>{b.label}</Badge>
                        {v.breaker.state === "open" && v.breaker.retry_in_sec !== null && (
                          <span className="ml-2 text-xs text-muted-foreground">retry in {Math.ceil(v.breaker.retry_in_sec)} s</span>
                        )}
                        <div className="text-xs text-muted-foreground">{v.breaker.trips} trips</div>
                      </Td>
                      <Td>{v.allowed_classifications.length ? v.allowed_classifications.join(", ") : "nothing"}</Td>
                      <Td className="tabular-nums">{v.limits ? share(v.limits.requests_available, v.limits.requests_capacity) : "n/a"}</Td>
                      <Td className="tabular-nums">{v.limits ? share(v.limits.tokens_available, v.limits.tokens_capacity) : "n/a"}</Td>
                      <Td className="tabular-nums">{v.limits ? `${v.limits.in_flight} / ${v.limits.max_concurrent}` : "n/a"}</Td>
                      <Td className="max-w-xs text-xs">{v.breaker.last_error ?? "none"}</Td>
                    </tr>
                  );
                })}
              </tbody>
            </DataTable>
          </Section>
          <Section title="Model routing" description="Each task picks the cheapest tier that can do it; quality problems raise the tier.">
            <DataTable caption="Model tiers">
              <thead><tr><Th>Tier</Th><Th>Deployment</Th><Th>Price per 1k tokens</Th></tr></thead>
              <tbody>
                {p.routing.map((r) => (
                  <tr key={r.tier}><Td className="font-medium">{r.tier}</Td><Td>{r.deployment}</Td><Td className="tabular-nums">${r.price_per_1k_usd}</Td></tr>
                ))}
              </tbody>
            </DataTable>
          </Section>
          <Section title="Recent fallbacks" description="Times a call moved to another provider, newest first.">
            {p.fallbacks.length === 0 ? (
              <p className="text-sm text-muted-foreground">No fallbacks. Every call stayed on its first-choice provider.</p>
            ) : (
              <DataTable caption="Recent provider fallbacks">
                <thead><tr><Th>When</Th><Th>Task</Th><Th>From</Th><Th>To</Th><Th>Data</Th><Th>Why</Th></tr></thead>
                <tbody>
                  {p.fallbacks.map((f) => (
                    <tr key={`${f.ts}-${f.task}-${f.from_provider}`}>
                      <Td>{formatDateTime(f.ts)}</Td><Td>{f.task}</Td><Td>{f.from_provider}</Td>
                      <Td>{f.to_provider ?? "none allowed"}</Td><Td>{f.data_classification}</Td><Td className="max-w-xs text-xs">{f.reason}</Td>
                    </tr>
                  ))}
                </tbody>
              </DataTable>
            )}
          </Section>
        </div>
      )}
    </Query>
  );
}
