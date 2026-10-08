import { Link, useParams } from "react-router-dom";
import { useCost, useEngagement, useTrace } from "@/api/hooks";
import { ErrorState, LoadingState } from "@/components/states/states";
import { Badge } from "@/components/ui/badge";
import { Tabs } from "@/components/ui/tabs";
import { StatusBadge } from "@/features/engagements/StatusBadge";
import { CostPanel } from "./panels/CostPanel";
import { GuardianPanel } from "./panels/GuardianPanel";
import { QualityPanel } from "./panels/QualityPanel";
import { RetrievalsPanel } from "./panels/RetrievalsPanel";
import { RunSummary } from "./panels/RunSummary";
import { ToolsPanel } from "./panels/ToolsPanel";
import { TracePanel } from "./panels/TracePanel";
import { retrievalSpans, toolSpans } from "./spans";

/** One run, inspected: the trace, every tool call, what was retrieved, the Guardian's decisions, cost and quality. */
export function RunPage() {
  const { id = "" } = useParams();
  const engagement = useEngagement(id);
  const trace = useTrace(id);
  const cost = useCost(id);

  if (engagement.isPending || trace.isPending) return <LoadingState label="Loading the run" lines={4} />;
  if (engagement.isError) return <ErrorState error={engagement.error} onRetry={() => void engagement.refetch()} />;
  if (trace.isError) return <ErrorState error={trace.error} onRetry={() => void trace.refetch()} />;
  const e = engagement.data;
  const t = trace.data;

  const tabs = [
    { id: "overview", label: "Overview", content: <RunSummary engagement={e} trace={t} cost={cost.data} /> },
    { id: "trace", label: "Trace", badge: t.span_count, content: <TracePanel trace={t} /> },
    { id: "tools", label: "Tool calls", badge: toolSpans(t.spans).length, content: <ToolsPanel trace={t} /> },
    { id: "retrievals", label: "Retrievals", badge: retrievalSpans(t.spans).length, content: <RetrievalsPanel trace={t} /> },
    { id: "guardian", label: "Guardian", badge: e.guardian_decisions.length, content: <GuardianPanel workflowId={id} /> },
    { id: "cost", label: "Cost", content: <CostPanel workflowId={id} /> },
    { id: "quality", label: "Quality", content: <QualityPanel engagement={e} /> },
  ];

  return (
    <div className="space-y-6">
      <div>
        <Link to="/control-center" className="text-sm text-muted-foreground hover:underline">&larr; Control Center</Link>
        <div className="mt-1 flex flex-wrap items-start justify-between gap-3">
          <h1 className="max-w-3xl text-2xl font-semibold">{e.state.business_problem ?? "Run"}</h1>
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={e.status} />
            {e.state.risk_level && <Badge variant="outline">{e.state.risk_level} risk</Badge>}
          </div>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          <span className="font-mono">{e.workflow_id}</span> ·{" "}
          <Link className="underline" to={`/engagements/${e.workflow_id}`}>Open the engagement</Link>
        </p>
      </div>
      <Tabs label="Run inspector" items={tabs} />
    </div>
  );
}
