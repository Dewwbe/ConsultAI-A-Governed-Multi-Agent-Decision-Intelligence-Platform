import { AlertTriangle, Inbox, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";
import { describeError } from "@/api/errors";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

/** Loading placeholder. Announced to screen readers, hidden visually from the tab order. */
export function LoadingState({ label = "Loading", lines = 3 }: { label?: string; lines?: number }) {
  return (
    <div role="status" aria-live="polite" aria-busy="true" className="space-y-2">
      <span className="sr-only">{label}…</span>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={i === 0 ? "h-5 w-1/2" : "h-4 w-full"} />
      ))}
    </div>
  );
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed p-8 text-center">
      <Inbox aria-hidden="true" className="size-8 text-muted-foreground" />
      <p className="font-medium">{title}</p>
      {description && <p className="max-w-md text-sm text-muted-foreground">{description}</p>}
      {action}
    </div>
  );
}

/** Typed-error aware: a 404, a 409 and a dead API each get their own wording. */
export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { title, message } = describeError(error);
  return (
    <Alert variant="destructive">
      <div className="flex items-start gap-3">
        <AlertTriangle aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-destructive" />
        <div className="flex-1">
          <AlertTitle>{title}</AlertTitle>
          <AlertDescription>{message}</AlertDescription>
          {onRetry && (
            <Button variant="outline" size="sm" className="mt-3" onClick={onRetry}>
              <RefreshCw /> Try again
            </Button>
          )}
        </div>
      </div>
    </Alert>
  );
}
