import type { TraceOut } from "@/api/types";
import { BarList } from "@/components/charts/charts";
import { EmptyState } from "@/components/states/states";
import { Badge } from "@/components/ui/badge";
import { humanize } from "@/lib/format";
import { attr, isRedacted, retrievalSpans } from "../spans";

interface RetrievalPayload {
  retrieval_id: string;
  index: string;
  embedding_model: string;
  reranker?: string;
  index_version?: string;
  k?: number;
  filters?: Record<string, unknown>;
  redacted?: boolean;
  documents: { doc_id: string; chunk_id: string; source: string; score: number; text?: string }[];
}

/** "What did the agent actually see?" for every search: the query, the filters, the passages and their scores. */
export function RetrievalsPanel({ trace }: { trace: TraceOut }) {
  const searches = retrievalSpans(trace.spans);
  if (searches.length === 0) return <EmptyState title="No retrievals" description="The research agent has not searched yet." />;
  return (
    <ol aria-label="Retrievals" className="space-y-4">
      {searches.map((span, i) => {
        const payload = attr<RetrievalPayload | string>(span, "consultai.retrieval");
        const query = attr<string>(span, "consultai.query");
        const data = typeof payload === "object" ? payload : undefined;
        return (
          <li key={span.span_id} className="space-y-3 rounded-lg border bg-card p-4">
            <div>
              <p className="text-xs text-muted-foreground">Search {i + 1}</p>
              {isRedacted(query) ? (
                <p className="text-sm italic text-muted-foreground">The query text is hidden for your role.</p>
              ) : (
                <p className="text-sm font-medium">{query}</p>
              )}
            </div>
            {data ? (
              <>
                <dl className="grid gap-x-6 gap-y-1 text-xs sm:grid-cols-2 lg:grid-cols-4">
                  <div><dt className="text-muted-foreground">Index</dt><dd>{data.index}{data.index_version ? ` (${data.index_version})` : ""}</dd></div>
                  <div><dt className="text-muted-foreground">Embedding model</dt><dd>{data.embedding_model}</dd></div>
                  <div><dt className="text-muted-foreground">Reranker</dt><dd>{data.reranker ?? "none"}</dd></div>
                  <div><dt className="text-muted-foreground">Passages returned</dt><dd>{data.documents.length}{data.k ? ` of up to ${data.k}` : ""}</dd></div>
                </dl>
                {data.filters && Object.keys(data.filters).length > 0 && (
                  <p className="flex flex-wrap items-center gap-1.5 text-xs">
                    <span className="text-muted-foreground">Filters:</span>
                    {Object.entries(data.filters).map(([k, v]) => (
                      <Badge key={k} variant="outline">{humanize(k)}: {Array.isArray(v) ? v.join(", ") : String(v)}</Badge>
                    ))}
                  </p>
                )}
                {data.documents.length > 0 && (
                  <BarList
                    ariaLabel={`Relevance of the passages for search ${i + 1}`}
                    items={data.documents.map((d) => ({ label: d.chunk_id, value: d.score, hint: d.source }))}
                    format={(v) => v.toFixed(2)}
                  />
                )}
                <ul className="space-y-2">
                  {data.documents.map((d) => (
                    <li key={d.chunk_id} className="rounded border p-2 text-xs">
                      <p className="font-medium">{d.source}</p>
                      {d.text !== undefined ? <p className="mt-1 text-muted-foreground">{d.text}</p> : <p className="mt-1 italic text-muted-foreground">Passage text hidden for your role.</p>}
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="text-sm text-muted-foreground">The details of this search are hidden for your role.</p>
            )}
          </li>
        );
      })}
    </ol>
  );
}
