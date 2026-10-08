import { CheckCircle2, XCircle } from "lucide-react";
import { DEFAULT_API_BASE_URL } from "@/api/client";
import { useHealth, useMe } from "@/api/hooks";
import { ErrorState, LoadingState } from "@/components/states/states";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

function HealthCard() {
  const health = useHealth();
  return (
    <Card>
      <CardHeader>
        <CardTitle>API status</CardTitle>
        <CardDescription>{import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL}</CardDescription>
      </CardHeader>
      <CardContent>
        {health.isPending && <LoadingState label="Checking the API" lines={2} />}
        {health.isError && <ErrorState error={health.error} onRetry={() => void health.refetch()} />}
        {health.isSuccess && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
            <dt className="text-muted-foreground">Status</dt>
            <dd className="flex items-center gap-1.5 font-medium">
              <CheckCircle2 aria-hidden="true" className="size-4 text-success" /> {health.data.status}
            </dd>
            <dt className="text-muted-foreground">Model provider</dt>
            <dd className="font-medium">{health.data.llm_provider}</dd>
          </dl>
        )}
      </CardContent>
    </Card>
  );
}

function IdentityCard() {
  const me = useMe();
  return (
    <Card>
      <CardHeader>
        <CardTitle>Your access</CardTitle>
        <CardDescription>As the server sees you</CardDescription>
      </CardHeader>
      <CardContent>
        {me.isPending && <LoadingState label="Loading your profile" lines={2} />}
        {me.isError && <ErrorState error={me.error} onRetry={() => void me.refetch()} />}
        {me.isSuccess && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
            <dt className="text-muted-foreground">Name</dt>
            <dd className="font-medium">{me.data.name}</dd>
            <dt className="text-muted-foreground">Roles</dt>
            <dd className="flex flex-wrap gap-1.5">
              {me.data.roles.length === 0 ? (
                <span className="text-muted-foreground">none</span>
              ) : (
                me.data.roles.map((r) => (
                  <Badge key={r} variant="outline">
                    {r}
                  </Badge>
                ))
              )}
            </dd>
            <dt className="text-muted-foreground">Can approve</dt>
            <dd className="flex items-center gap-1.5 font-medium">
              {me.data.can_approve ? (
                <>
                  <CheckCircle2 aria-hidden="true" className="size-4 text-success" /> Yes
                </>
              ) : (
                <>
                  <XCircle aria-hidden="true" className="size-4 text-muted-foreground" /> No
                </>
              )}
            </dd>
          </dl>
        )}
      </CardContent>
    </Card>
  );
}

export function Dashboard() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Dashboard</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Governed multi-agent consulting delivery: agents do the work, the control plane decides what they may do.
        </p>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <HealthCard />
        <IdentityCard />
      </div>
    </div>
  );
}
