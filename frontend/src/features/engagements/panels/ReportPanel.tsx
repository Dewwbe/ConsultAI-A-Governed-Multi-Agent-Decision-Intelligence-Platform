import { Suspense, lazy } from "react";
import type { Engagement } from "@/api/types";
import { EmptyState, LoadingState } from "@/components/states/states";

// the Markdown renderer is large and only the Report tab needs it
const Markdown = lazy(() => import("react-markdown"));

/** The client-facing report. react-markdown renders it without raw HTML, so report text cannot inject markup. */
export function ReportPanel({ engagement }: { engagement: Engagement }) {
  const report = engagement.state.report;
  if (!report) {
    const reason =
      engagement.status === "awaiting_approval"
        ? "The report is written after a partner approves the recommendation."
        : engagement.status === "rejected"
          ? "The recommendation was rejected, so no report was produced."
          : engagement.status === "running"
            ? "It is written once the analysis and any approval are done."
            : "This run ended before a report was produced.";
    return <EmptyState title="No report yet" description={reason} />;
  }
  return (
    <article className="max-w-3xl space-y-3 text-sm leading-relaxed [&_h1]:text-xl [&_h1]:font-semibold [&_h2]:mt-6 [&_h2]:text-base [&_h2]:font-semibold [&_li]:ml-5 [&_li]:list-disc [&_strong]:font-semibold">
      <Suspense fallback={<LoadingState label="Loading the report" lines={4} />}>
        <Markdown>{report.markdown}</Markdown>
      </Suspense>
    </article>
  );
}
