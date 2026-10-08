import { QueryClientProvider, type QueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { ApiProvider } from "@/api/ApiProvider";
import type { Api, DevIdentity } from "@/api/client";
import { createQueryClient } from "@/api/queryClient";
import { AuthProvider, type AuthMode } from "@/auth/AuthProvider";
import { RequireRole } from "@/auth/RequireRole";
import { AppShell } from "@/components/layout/AppShell";
import { ThemeProvider } from "@/lib/theme";
import { Dashboard } from "@/pages/Dashboard";
import { NotFound } from "@/pages/NotFound";
import { ControlCenter, EngagementDetail, Engagements, Governance } from "@/pages/Placeholders";

/** The route table. Role-gated routes wrap their page in <RequireRole>. */
export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Dashboard />} />
        <Route path="engagements" element={<Engagements />} />
        <Route path="engagements/:id" element={<EngagementDetail />} />
        <Route path="control-center" element={<ControlCenter />} />
        <Route
          path="governance"
          element={
            <RequireRole roles={["Admin"]}>
              <Governance />
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
}

/** Every provider the app needs, in one place, so tests render with the same wiring as production. */
export function Providers({ children, queryClient, api, authMode, initialIdentity }: ProvidersProps) {
  const client = queryClient ?? createQueryClient();
  return (
    <ThemeProvider>
      <AuthProvider {...(authMode ? { mode: authMode } : {})} {...(initialIdentity ? { initialIdentity } : {})}>
        <QueryClientProvider client={client}>
          <ApiProvider {...(api ? { api } : {})}>{children}</ApiProvider>
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
