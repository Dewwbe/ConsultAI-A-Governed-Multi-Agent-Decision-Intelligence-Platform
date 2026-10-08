import { QueryClient } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AppRoutes, Providers } from "@/App";
import type { DevIdentity } from "@/api/client";

export function testQueryClient(): QueryClient {
  return new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 0 } } });
}

/** Render the whole app at `route`, as `identity`, with the same providers as production. */
export function renderApp(route = "/", identity: DevIdentity = { user: "dev-user", roles: [] }) {
  return render(
    <Providers queryClient={testQueryClient()} initialIdentity={identity}>
      <MemoryRouter initialEntries={[route]}>
        <AppRoutes />
      </MemoryRouter>
    </Providers>,
  );
}
