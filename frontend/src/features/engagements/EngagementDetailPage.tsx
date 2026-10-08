import { CircleCheck, OctagonAlert, UserCheck, Wifi, WifiOff } from "lucide-react";
import { useMemo } from "react";
import { Link, useLocation, useParams } from "react-router-dom";
import { useEngagement, useTrace } from "@/api/hooks";
import { ErrorState, LoadingState } from "@/components/states/states";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Tabs } from "@/components/ui/tabs";
import { ApprovalHistory } from "@/features/approval/ApprovalHistory";
import type { Engagement } from "@/api/types";
import { PipelineView } from "./PipelineView";
import { StatusBadge } from "./StatusBadge";
import { derivePipeline, eventsFromTrace } from "./pipeline";
import { DataPanel } from "./panels/DataPanel";
import { EvidencePanel } from "./panels/EvidencePanel";
import { FinancialPanel } from "./panels/FinancialPanel";
import { OptionsPanel } from "./panels/OptionsPanel";
import { ReportPanel } from "./panels/ReportPanel";
import { RisksPanel } from "./panels/RisksPanel";
import { SpecPanel } from "./panels/SpecPanel";
import { SummaryPanel } from "./panels/SummaryPanel";
import { useEngagementLive, type Connection } from "./useEngagementLive";

function ConnectionNote({ connection }: { connection: Connection }) {
  if (connection === "live")
    return (
      <Badge variant="success">
        <Wifi aria-hidden="true" className="size-3.5" /> Live
      </Badge>
    );
  if (connection === "connecting")
    return (
      <Badge variant="outline" aria-live="polite">
        Connecting…
      </Badge>
    );
  if (connection === "polling")
    return (
      <Badge variant="warning" aria-live="polite">
        <WifiOff aria-hidden="true" className="size-3.5" /> Live updates unavailable, checking every 2 s
      </Badge>
    );
  return <Badge variant="outline">Up to date</Badge>;
}

function StatusNotice({ engagement }: { engagement: Engagement }) {
  const lastDecision = [...engagement.guardian_decisions].reverse().find((g) => g.subject === "workflow");
  switch (engagement.status) {
    case "queued":
      return (
        <Alert>
          <AlertTitle>Queued</AlertTitle>
          <AlertDescription>The platform is at its run limit. This engagement starts automatically when a slot frees up.</AlertDescription>
        </Alert>
      );
    case "awaiting_approval":
      return (
        <Alert variant="warning">
          <div className="flex gap-3">
            <UserCheck aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-warning" />
            <div>
              <AlertTitle>Waiting for a partner&apos;s decision</AlertTitle>
              <AlertDescription>
                {lastDecision?.reasons.length ? `Why: ${lastDecision.reasons.join("; ")}.` : "The Guardian requires human approval."}
              </AlertDescription>
              <Button asChild size="sm" className="mt-3">
                <Link to={`/engagements/${engagement.workflow_id}/review`}>Review and decide</Link>
              </Button>
            </div>
          </div>
        </Alert>
      );
    case "escalated":
      return (
        <Alert variant="destructive">
          <div className="flex gap-3">
            <OctagonAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-destructive" />
            <div>
              <AlertTitle>Stopped for human investigation</AlertTitle>
              <AlertDescription>{engagement.halted_reason ?? "An agent could not produce trustworthy output."}</AlertDescription>
            </div>
          </div>
        </Alert>
      );
    case "failed":
      return (
        <Alert variant="destructive">
          <AlertTitle>The run failed</AlertTitle>
          <AlertDescription>{engagement.error ?? "An unexpected error stopped the run."}</AlertDescription>
        </Alert>
      );
    case "rejected":
      return (
        <Alert>
          <AlertTitle>Rejected by a partner</AlertTitle>
          <AlertDescription>No report was produced. The analysis stays available for review.</AlertDescription>
        </Alert>
      );
    default:
      return null;
  }
}

const DECIDED_TEXT = {
  approve: "Approved. The report is being written.",
  modify: "Approved with your changes. The report is being written.",
  reject: "Rejected. The engagement ended without a report.",
} as const;

export function EngagementDetailPage() {
  const { id = "" } = useParams();
  const location = useLocation();
  const decided = (location.state as { decided?: keyof typeof DECIDED_TEXT } | null)?.decided;
  const live = useEngagementLive(id);
  const polling = live.connection === "polling";
  const query = useEngagement(id, { poll: polling });
  const engagement = query.data;
  const trace = useTrace(id, { enabled: polling, poll: polling && engagement?.status === "running" });

  // The stream is the source of truth; if it is unavailable, rebuild the same steps from the trace.
  const events = useMemo(
    () => (polling && trace.data ? eventsFromTrace(trace.data, engagement?.status) : live.events),
    [polling, trace.data, live.events, engagement?.status],
  );
  const groups = useMemo(() => derivePipeline(events, engagement?.status), [events, engagement?.status]);

  if (query.isPending) return <LoadingState label="Loading the engagement" lines={4} />;
  if (query.isError || !engagement) {
    return (
      <div className="space-y-4">
        <Link to="/engagements" className="text-sm text-muted-foreground hover:underline">
          &larr; Engagements
        </Link>
        <ErrorState error={query.error ?? live.error} onRetry={() => void query.refetch()} />
      </div>
    );
  }

  const { state } = engagement;
  const tabs = [
    { id: "summary", label: "Summary", content: <SummaryPanel engagement={engagement} /> },
    { id: "spec", label: "Specification", content: <SpecPanel engagement={engagement} /> },
    { id: "evidence", label: "Evidence", badge: state.research_results?.length, content: <EvidencePanel workflowId={id} running={engagement.status === "running"} /> },
    { id: "data", label: "Data", badge: state.datasets?.length, content: <DataPanel engagement={engagement} /> },
    { id: "financials", label: "Financials", badge: state.financial_models?.length, content: <FinancialPanel engagement={engagement} /> },
    { id: "risks", label: "Risks", badge: state.risks?.length, content: <RisksPanel engagement={engagement} /> },
    { id: "options", label: "Options", badge: state.options?.length, content: <OptionsPanel engagement={engagement} /> },
    { id: "report", label: "Report", content: <ReportPanel engagement={engagement} /> },
    { id: "approvals", label: "Approvals", content: <ApprovalHistory workflowId={id} /> },
  ];

  return (
    <div className="space-y-6">
      <div>
        <Link to="/engagements" className="text-sm text-muted-foreground hover:underline">
          &larr; Engagements
        </Link>
        <div className="mt-1 flex flex-wrap items-start justify-between gap-3">
          <h1 className="max-w-3xl text-2xl font-semibold">{state.business_problem ?? "Engagement"}</h1>
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={engagement.status} />
            {state.risk_level && <Badge variant="outline">{state.risk_level} risk</Badge>}
            {state.data_classification && <Badge variant="outline">{state.data_classification}</Badge>}
          </div>
        </div>
        <p className="mt-1 font-mono text-xs text-muted-foreground">{engagement.workflow_id}</p>
      </div>

      {decided && (
        <Alert>
          <div className="flex gap-3">
            <CircleCheck aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-success" />
            <div>
              <AlertTitle>Decision recorded</AlertTitle>
              <AlertDescription>{DECIDED_TEXT[decided]}</AlertDescription>
            </div>
          </div>
        </Alert>
      )}

      <StatusNotice engagement={engagement} />

      <Card>
        <CardHeader className="flex-row items-center justify-between gap-3">
          <CardTitle>Pipeline</CardTitle>
          <ConnectionNote connection={live.connection} />
        </CardHeader>
        <CardContent>
          <PipelineView groups={groups} />
        </CardContent>
      </Card>

      <Tabs label="Engagement results" items={tabs} />
    </div>
  );
}
