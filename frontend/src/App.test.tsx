import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { API } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { renderApp } from "@/test/utils";

describe("dashboard", () => {
  it("lists the health status of the API", async () => {
    renderApp("/");
    expect(await screen.findByText("stub")).toBeInTheDocument(); // model provider row
    const card = screen.getByRole("heading", { name: "API status" }).closest("div")!.parentElement!;
    expect(within(card).getByText("ok")).toBeInTheDocument();
    // the header pill reports it too
    expect(await screen.findByText(/API ok · stub/)).toBeInTheDocument();
  });

  it("shows loading before the answer arrives", () => {
    renderApp("/");
    expect(screen.getAllByRole("status").length).toBeGreaterThan(0);
  });

  it("explains an unreachable API and recovers on retry", async () => {
    server.use(http.get(`${API}/health`, () => HttpResponse.error()));
    renderApp("/");
    expect(await screen.findByText("Cannot reach the API")).toBeInTheDocument();
    expect(await screen.findByText("API unreachable")).toBeInTheDocument();

    server.resetHandlers(); // the backend comes back
    await userEvent.click(screen.getAllByRole("button", { name: /try again/i })[0]!);
    expect(await screen.findByText("stub")).toBeInTheDocument();
  });

  it("shows the server's view of the user, including the approver capability", async () => {
    renderApp("/", { user: "pat", roles: ["Partner"] });
    expect(await screen.findByText("pat", { selector: "dd" })).toBeInTheDocument();
    expect(screen.getByText("Partner", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByText("Yes")).toBeInTheDocument();
  });

  it("says 'No' when the user cannot approve", async () => {
    renderApp("/", { user: "ann", roles: ["Analyst"] });
    expect(await screen.findByText("No")).toBeInTheDocument();
  });
});

describe("shell and role-aware routing", () => {
  it("hides the Governance link from users without the Admin role", async () => {
    renderApp("/", { user: "ann", roles: ["Analyst"] });
    await screen.findByText("Analyst", { selector: "span" });
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getByRole("link", { name: "Engagements" })).toBeInTheDocument();
    expect(within(nav).queryByRole("link", { name: "Governance" })).not.toBeInTheDocument();
  });

  it("shows it to Admins", async () => {
    renderApp("/", { user: "ada", roles: ["Admin"] });
    expect(await within(screen.getByRole("navigation", { name: "Main" })).findByRole("link", { name: "Governance" })).toBeInTheDocument();
  });

  it("blocks the Governance page for a user without the role, even by URL", async () => {
    renderApp("/governance", { user: "ann", roles: ["Analyst"] });
    expect(await screen.findByText("You do not have access to this page")).toBeInTheDocument();
    expect(screen.getByText(/needs one of these roles: Admin/)).toBeInTheDocument();
    expect(screen.queryByText("Arrives in F4")).not.toBeInTheDocument();
  });

  it("lets an Admin in", async () => {
    renderApp("/governance", { user: "ada", roles: ["Admin"] });
    expect(await screen.findByText("Arrives in F4")).toBeInTheDocument();
  });

  it("does not guess when the access check itself fails", async () => {
    server.use(http.get(`${API}/me`, () => HttpResponse.json({ detail: "boom" }, { status: 500 })));
    renderApp("/governance", { user: "ada", roles: ["Admin"] });
    expect(await screen.findByText("The server had a problem")).toBeInTheDocument();
    expect(screen.queryByText("Arrives in F4")).not.toBeInTheDocument();
  });

  it("shows a not-found page for unknown addresses", async () => {
    renderApp("/nowhere");
    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /back to the dashboard/i })).toHaveAttribute("href", "/");
  });

  it("renders engagement pages as planned screens with the id", async () => {
    renderApp("/engagements/wf_123");
    expect(await screen.findByRole("heading", { name: "Engagement wf_123" })).toBeInTheDocument();
  });

  it("offers a skip link and a labelled main landmark", async () => {
    renderApp("/");
    expect(screen.getByRole("link", { name: "Skip to content" })).toHaveAttribute("href", "#main");
    expect(screen.getByRole("main")).toHaveAttribute("id", "main");
    await screen.findByText("stub");
  });
});

describe("dev identity switcher", () => {
  it("changes the identity the API sees and refetches", async () => {
    renderApp("/", { user: "ann", roles: [] });
    expect(await screen.findByText("No")).toBeInTheDocument();
    await userEvent.click(screen.getByText("ann", { selector: "summary span" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Partner" }));
    await waitFor(() => expect(screen.getByText("Yes")).toBeInTheDocument());
    expect(window.localStorage.getItem("consultai.devIdentity")).toContain("Partner");
  });

  it("is not shown in entra mode", async () => {
    const { Providers, AppRoutes } = await import("@/App");
    const { MemoryRouter } = await import("react-router-dom");
    const { render } = await import("@testing-library/react");
    const { testQueryClient } = await import("@/test/utils");
    server.use(http.get(`${API}/me`, () => HttpResponse.json({ detail: "missing bearer token" }, { status: 401 })));
    render(
      <Providers queryClient={testQueryClient()} authMode="entra">
        <MemoryRouter>
          <AppRoutes />
        </MemoryRouter>
      </Providers>,
    );
    expect(await screen.findByText("Sign-in required")).toBeInTheDocument();
    expect(screen.queryByText(/Development sign-in/)).not.toBeInTheDocument();
  });
});

describe("theme", () => {
  it("cycles system, light, dark and remembers the choice", async () => {
    renderApp("/");
    const button = () => screen.getByRole("button", { name: /^Theme:/ });
    expect(button()).toHaveAccessibleName(/Theme: system/);
    await userEvent.click(button()); // -> light
    expect(button()).toHaveAccessibleName(/Theme: light/);
    expect(document.documentElement).not.toHaveClass("dark");
    await userEvent.click(button()); // -> dark
    expect(button()).toHaveAccessibleName(/Theme: dark/);
    expect(document.documentElement).toHaveClass("dark");
    expect(window.localStorage.getItem("consultai.theme")).toBe("dark");
    await screen.findByText("stub");
  });
});
