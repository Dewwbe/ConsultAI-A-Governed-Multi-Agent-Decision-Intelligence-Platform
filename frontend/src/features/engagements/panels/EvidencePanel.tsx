import { BadgeCheck, RotateCcw, ShieldQuestion } from "lucide-react";
import { useEvidence, useReplayRetrieval } from "@/api/hooks";
import type { RetrievalRecord } from "@/api/types";
import { ErrorState, LoadingState } from "@/components/states/states";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { formatPct, humanize } from "@/lib/format";
import { DataTable, Num, Pending, Section, Td, Th } from "./common";

const REJECTION_REASON: Record<string, string> = {
  unverified_citation: "the quote was not found in the cited source",
  unsupported_claim: "it cited a document that was never retrieved",
};

function ReplayButton({ workflowId, record }: { workflowId: string; record: RetrievalRecord }) {
  const replay = useReplayRetrieval(workflowId);
  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button variant="outline" size="sm" disabled={replay.isPending} onClick={() => replay.mutate(record.retrieval_id)}>
        <RotateCcw /> Replay
      </Button>
      {replay.isSuccess && (
        <Badge variant={replay.data.reproduced ? "success" : "destructive"}>
          {replay.data.reproduced ? `Reproduced exactly (${replay.data.evidence.length} passages)` : "Could not reproduce"}
        </Badge>
      )}
      {replay.isError && <span className="text-xs text-destructive">Replay failed</span>}
      {replay.isSuccess && replay.data.error && <span className="text-xs text-muted-foreground">{replay.data.error}</span>}
    </div>
  );
}

/** Claims, the exact sources they cite, and what the agent actually retrieved ("what did it see?"). */
export function EvidencePanel({ workflowId, running }: { workflowId: string; running: boolean }) {
  const evidence = useEvidence(workflowId);
  if (evidence.isPending) return <LoadingState label="Loading evidence" />;
  if (evidence.isError) return <ErrorState error={evidence.error} onRetry={() => void evidence.refetch()} />;
  const { claims, sources, retrievals, rejected_claims: rejected } = evidence.data;
  if (claims.length === 0 && retrievals.length === 0) return <Pending running={running} what="evidence" />;

  return (
    <div className="space-y-8">
      {rejected.length > 0 && (
        <Alert variant="warning">
          <AlertTitle>
            {rejected.length} claim{rejected.length === 1 ? " was" : "s were"} dropped
          </AlertTitle>
          <AlertDescription>
            {rejected.map((r) => `${r.doc_ref}: ${REJECTION_REASON[r.reason] ?? r.reason}`).join("; ")}. Claims are kept only when their quote
            appears verbatim in the cited source.
          </AlertDescription>
        </Alert>
      )}

      <Section title={`Claims (${claims.length})`} description="Each claim carries the quote it rests on and where it came from.">
        <ul className="space-y-3">
          {claims.map((c, i) => (
            <li key={`${c.chunk_id ?? i}-${i}`} className="rounded-lg border bg-card p-4">
              <p className="text-sm font-medium">{c.claim}</p>
              {c.quote && (
                <blockquote className="mt-2 border-l-2 pl-3 text-sm italic text-muted-foreground">&ldquo;{c.quote}&rdquo;</blockquote>
              )}
              <div className="mt-3 flex flex-wrap items-center gap-2 text-xs">
                <Badge variant={c.verified ? "success" : "warning"}>
                  {c.verified ? <BadgeCheck aria-hidden="true" className="size-3.5" /> : <ShieldQuestion aria-hidden="true" className="size-3.5" />}
                  {c.verified ? "Quote verified" : "Not verified"}
                </Badge>
                <span className="text-muted-foreground">{c.source}</span>
                <span className="text-muted-foreground">· {c.publication_date}</span>
                <span className="text-muted-foreground">· confidence {formatPct(c.confidence)}</span>
              </div>
            </li>
          ))}
        </ul>
      </Section>

      {sources.length > 0 && (
        <Section title="Sources">
          <DataTable caption="Sources and how many claims each supports">
            <thead>
              <tr>
                <Th>Source</Th>
                <Th>Documents</Th>
                <Th className="text-right">Claims</Th>
              </tr>
            </thead>
            <tbody>
              {sources.map((s) => (
                <tr key={s.source}>
                  <Td>{s.source}</Td>
                  <Td>{s.doc_ids.join(", ")}</Td>
                  <Td className="text-right"><Num>{s.claims}</Num></Td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </Section>
      )}

      {retrievals.length > 0 && (
        <Section title={`What the agent saw (${retrievals.length} searches)`} description="Each stored search can be replayed from its record to confirm the same passages come back.">
          <ul className="space-y-3">
            {retrievals.map((r) => (
              <li key={r.retrieval_id} className="rounded-lg border bg-card p-4 text-sm">
                <p className="font-medium">{r.query}</p>
                <p className="mt-1 text-xs text-muted-foreground">
                  {r.document_ids.length} passages · {r.embedding_model} · scores {r.scores.map((s) => s.toFixed(2)).join(", ") || "none"}
                </p>
                {Object.keys(r.filters).length > 0 && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    Filters: {Object.entries(r.filters).map(([k, v]) => `${humanize(k)} = ${Array.isArray(v) ? v.join("/") : String(v)}`).join(", ")}
                  </p>
                )}
                <div className="mt-3">
                  <ReplayButton workflowId={workflowId} record={r} />
                </div>
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}
