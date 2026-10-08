import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import { Suspense, lazy, type ReactNode } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { ApiProvider } from "@/api/ApiProvider";
import type { Api, DevIdentity } from "@/api/client";
import { createQueryClient } from "@/api/queryClient";
import { AuthGate } from "@/auth/AuthGate";
import { AuthProvider, type AuthMode } from "@/auth/AuthProvider";
import type { EntraSession } from "@/auth/entra";
import { RequireRole } from "@/auth/RequireRole";
import { AppShell } from "@/components/layout/AppShell";
import { LoadingState } from "@/components/states/states";
import { ThemeProvider } from "@/lib/theme";
import { Dashboard } from "@/pages/Dashboard";
import { NotFound } from "@/pages/NotFound";
import { ReviewPage } from "@/features/approval/ReviewPage";
import { EngagementDetailPage } from "@/features/engagements/EngagementDetailPage";
import { EngagementsPage } from "@/features/engagements/EngagementsPage";
import { NewEngagementPage } from "@/features/engagements/NewEngagementPage";

// The Control Center pulls in the chart library, so it loads only when someone opens it.
const ControlCenterPage = lazy(() => import("@/features/control-center/OverviewPage").then((m) => ({ default: m.ControlCenterPage })));
const GovernancePage = lazy(() => import("@/features/governance/GovernancePage").then((m) => ({ default: m.GovernancePage })));
const RunPage = lazy(() => import("@/features/control-center/RunPage").then((m) => ({ default: m.RunPage })));
const lazyPage = (page: ReactNode) => <Suspense fallback={<LoadingState label="Loading" lines={4} />}>{page}</Suspense>;

/** The route table. Role-gated routes wrap their page in <RequireRole>. */
export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Dashboard />} />
        <Route path="engagements" element={<EngagementsPage />} />
        <Route path="engagements/new" element={<NewEngagementPage />} />
        <Route path="engagements/:id" element={<EngagementDetailPage />} />
        <Route path="engagements/:id/review" element={<ReviewPage />} />
        <Route path="control-center" element={lazyPage(<ControlCenterPage />)} />
        <Route path="control-center/:id" element={lazyPage(<RunPage />)} />
        <Route
          path="governance"
          element={
            <RequireRole roles={["Admin", "Auditor"]}>
              {lazyPage(<GovernancePage />)}
            </RequireRole>
          }
        />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  );
}

export interface ProvidersProps {
  children: ReactNode;
  queryClient?: QueryClient;
  api?: Api;
  authMode?: AuthMode;
  initialIdentity?: DevIdentity;
  entraSession?: EntraSession;
}

/** Every provider the app needs, in one place, so tests render with the same wiring as production. */
export function Providers({ children, queryClient, api, authMode, initialIdentity, entraSession }: ProvidersProps) {
  const client = queryClient ?? createQueryClient();
  return (
    <ThemeProvider>
      <AuthProvider
        {...(authMode ? { mode: authMode } : {})}
        {...(initialIdentity ? { initialIdentity } : {})}
        {...(entraSession ? { entraSession } : {})}
      >
        <QueryClientProvider client={client}>
          <ApiProvider {...(api ? { api } : {})}>
            <AuthGate>{children}</AuthGate>
          </ApiProvider>
        </QueryClientProvider>
      </AuthProvider>
    </ThemeProvider>
  );
}

export default function App() {
  return (
    <Providers>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </Providers>
  );
}
