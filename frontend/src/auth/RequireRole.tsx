import type { ReactNode } from "react";
import { useMe } from "@/api/hooks";
import { ErrorState, LoadingState } from "@/components/states/states";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

/**
 * Route guard. Roles come from the server's `/me`, not from local state. This only decides what the
 * UI shows: every protected action is enforced again by the API, so hiding a screen is a convenience.
 */
export function RequireRole({ roles, children }: { roles: string[]; children: ReactNode }) {
  const me = useMe();
  if (me.isPending) return <LoadingState label="Checking your access" lines={2} />;
  if (me.isError) return <ErrorState error={me.error} onRetry={() => void me.refetch()} />;
  if (!roles.some((r) => me.data.roles.includes(r))) {
    return (
      <Alert variant="warning">
        <AlertTitle>You do not have access to this page</AlertTitle>
        <AlertDescription>It needs one of these roles: {roles.join(", ")}.</AlertDescription>
      </Alert>
    );
  }
  return <>{children}</>;
}
