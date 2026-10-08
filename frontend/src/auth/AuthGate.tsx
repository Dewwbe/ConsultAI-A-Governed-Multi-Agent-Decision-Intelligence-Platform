import { LogIn } from "lucide-react";
import type { ReactNode } from "react";
import { LoadingState } from "@/components/states/states";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAuth } from "./AuthProvider";

/**
 * In Entra mode nothing may call the API before the user signs in (every call would be a 401), so the
 * app shows a sign-in screen instead. In dev mode this is a pass-through.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const { mode, ready, signedIn, error, signIn } = useAuth();
  if (mode === "dev" || (ready && signedIn)) return <>{children}</>;
  return (
    <main className="grid min-h-screen place-items-center p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle>Sign in to ConsultAI</CardTitle>
          <CardDescription>Use your organisation account. Your role decides what you can do.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {!ready && <LoadingState label="Starting sign-in" lines={2} />}
          {error && (
            <Alert variant="destructive">
              <AlertTitle>Sign-in is unavailable</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
          {ready && !error && (
            <Button onClick={() => void signIn()}>
              <LogIn /> Sign in with Microsoft
            </Button>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
