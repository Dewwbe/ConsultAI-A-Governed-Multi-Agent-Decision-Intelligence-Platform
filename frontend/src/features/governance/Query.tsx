import type { ReactNode } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { ErrorState, LoadingState } from "@/components/states/states";

/** The loading, error and ready states every governance tab shares. */
export function Query<T>({ q, what, children }: { q: UseQueryResult<T>; what: string; children: (data: T) => ReactNode }) {
  if (q.isPending) return <LoadingState label={`Loading ${what}`} lines={3} />;
  if (q.isError) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  return <>{children(q.data)}</>;
}
