import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";
import { API, fixtures } from "@/mocks/handlers";
import { server } from "@/mocks/server";
import { renderApp } from "@/test/utils";

const ID = fixtures.detail.workflow_id;
const REC = fixtures.detail.state.recommendation;
const PARTNER = { user: "pat", roles: ["Partner"] };
const ANALYST = { user: "ann", roles: ["Analyst"] };

interface Posted {
  decision: string;
  changes: Record<string, unknown>;
  reason: string;
}

/** Capture the decision the UI sends, and answer like the server would. */
function captureApproval(respond: () => Response | Promise<Response> = () => HttpResponse.json({ ...fixtures.completed, workflow_id: ID })) {
  const posted: Posted[] = [];
  server.use(
    http.post(`${API}/engagements/:id/approval`, async ({ request }) => {
      posted.push((await request.json()) as Posted);
      return respond();
    }),
  );
  return posted;
}

const review = (identity = PARTNER) => renderApp(`/engagements/${ID}/review`, identity);
const choose = async (name: RegExp) => userEvent.click(await screen.findByRole("radio", { name }));
const reviewDecision = () => userEvent.click(screen.getByRole("button", { name: /review decision/i }));
const dialog = () => screen.findByRole("dialog");

describe("review screen content (from the specification)", () => {
  it("shows the recommendation, evidence score, financial confidence, risk level, groundedness, constraint match and cost", async () => {
    review();
    expect(await screen.findByRole("heading", { level: 1, name: /Review: Should we expand/ })).toBeInTheDocument();
    for (const label of ["Recommendation", "Evidence score", "Financial confidence", "Risk level", "Groundedness", "Constraint match", "Cost so far"]) {
      expect(screen.getByText(label, { selector: "dt" })).toBeInTheDocument();
    }
    expect(screen.getByText("Pilot", { selector: "dd" })).toBeInTheDocument();
    expect(screen.getByText("high", { selector: "dd span" })).toBeInTheDocument();
  });

  it("gives the Guardian's reasons for escalation, the rationale, assumptions and top risks", async () => {
    review();
    expect(await screen.findByRole("heading", { name: "Why this needs a partner" })).toBeInTheDocument();
    expect(screen.getByText(/client-facing recommendation is a high-risk action/)).toBeInTheDocument();
    expect(screen.getByText(REC.rationale)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Top risks" })).toBeInTheDocument();
    expect(screen.getByText(/operating margin, from the data warehouse/)).toBeInTheDocument();
  });

  it("is reached from the engagement page", async () => {
    renderApp(`/engagements/${ID}`, PARTNER);
    const link = await screen.findByRole("link", { name: /review and decide/i });
    await userEvent.click(link);
    expect(await screen.findByRole("heading", { level: 1, name: /^Review:/ })).toBeInTheDocument();
  });
});

describe("who may decide", () => {
  it("lets a user without the Partner role read the review but offers no decision controls", async () => {
    review(ANALYST);
    expect(await screen.findByText("You can review this, but not decide it")).toBeInTheDocument();
    expect(screen.getByText(/needs the Partner role/)).toHaveTextContent("You have: Analyst");
    expect(screen.queryByRole("radio", { name: /approve/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /review decision/i })).not.toBeInTheDocument();
    expect(screen.getByText(REC.rationale)).toBeInTheDocument(); // still readable
  });

  it("explains when the engagement is no longer waiting, and offers no decision", async () => {
    server.use(http.get(`${API}/engagements/:id`, () => HttpResponse.json({ ...fixtures.completed, workflow_id: ID })));
    review();
    expect(await screen.findByText("This engagement is not waiting for a decision")).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: /approve/i })).not.toBeInTheDocument();
  });

  it("shows the server's refusal if the role changed since the page loaded", async () => {
    captureApproval(() => HttpResponse.json({ detail: "approving requires the 'Partner' role" }, { status: 403 }));
    review();
    await choose(/^approve/i);
    await reviewDecision();
    await userEvent.click(within(await dialog()).getByRole("button", { name: "Approve" }));
    expect(await screen.findByText("The server refused your decision")).toBeInTheDocument();
    expect(screen.getByText(/requires the 'Partner' role/)).toBeInTheDocument();
  });
});

describe("approve", () => {
  it("asks for confirmation, then sends the decision and lands on the engagement with a confirmation", async () => {
    const posted = captureApproval();
    review();
    await choose(/^approve/i);
    await reviewDecision();
    const d = await dialog();
    expect(d).toHaveTextContent("cannot be undone");
    expect(posted).toHaveLength(0); // nothing sent before the user confirms
    await userEvent.click(within(d).getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(posted).toEqual([{ decision: "approve", changes: {}, reason: "" }]));
    expect(await screen.findByText("Decision recorded")).toBeInTheDocument();
    expect(screen.getByText(/Approved\. The report is being written/)).toBeInTheDocument();
  });

  it("sends an optional reason when given", async () => {
    const posted = captureApproval();
    review();
    await choose(/^approve/i);
    await userEvent.type(screen.getByLabelText(/reason/i), "Numbers check out");
    await reviewDecision();
    await userEvent.click(within(await dialog()).getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(posted[0]?.reason).toBe("Numbers check out"));
  });
});

describe("reject", () => {
  it("needs a reason, and does not open the confirmation without one", async () => {
    const posted = captureApproval();
    review();
    await choose(/^reject/i);
    await reviewDecision();
    expect(await screen.findByText("Give a reason for rejecting.")).toBeInTheDocument();
    expect(screen.getByLabelText(/reason/i)).toHaveAttribute("aria-invalid", "true");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(posted).toHaveLength(0);
  });

  it("confirms with a clearly destructive action, then sends the reason", async () => {
    const posted = captureApproval(() => HttpResponse.json({ ...fixtures.detail, status: "rejected" }));
    review();
    await choose(/^reject/i);
    await userEvent.type(screen.getByLabelText(/reason/i), "Assumptions too optimistic");
    await reviewDecision();
    const d = await dialog();
    expect(d).toHaveTextContent("ends without a report");
    expect(d).toHaveTextContent("Assumptions too optimistic");
    await userEvent.click(within(d).getByRole("button", { name: "Reject" }));
    await waitFor(() => expect(posted).toEqual([{ decision: "reject", changes: {}, reason: "Assumptions too optimistic" }]));
    expect(await screen.findByText(/Rejected\. The engagement ended without a report/)).toBeInTheDocument();
  });
});

describe("modify", () => {
  it("starts with the current text, and requires a real change plus a reason", async () => {
    const posted = captureApproval();
    review();
    await choose(/^modify/i);
    expect(screen.getByLabelText("Rationale")).toHaveValue(REC.rationale);
    expect(screen.getByLabelText("Assumptions")).toHaveValue(REC.assumptions.join("\n"));
    await reviewDecision();
    expect(await screen.findByText("Give a reason for the change.")).toBeInTheDocument();
    expect(screen.getByText("Change the rationale or the assumptions first.")).toBeInTheDocument();
    expect(posted).toHaveLength(0);
  });

  it("sends only what changed: a new rationale alone leaves the assumptions out", async () => {
    const posted = captureApproval();
    review();
    await choose(/^modify/i);
    const rationale = screen.getByLabelText("Rationale");
    await userEvent.clear(rationale);
    await userEvent.type(rationale, "Start small and prove demand first.");
    await userEvent.type(screen.getByLabelText(/reason/i), "Tone down the claim");
    await reviewDecision();
    const d = await dialog();
    expect(d).toHaveTextContent("Your edits to Rationale");
    await userEvent.click(within(d).getByRole("button", { name: "Approve with changes" }));
    await waitFor(() => expect(posted).toEqual([{ decision: "modify", changes: { rationale: "Start small and prove demand first." }, reason: "Tone down the claim" }]));
  });

  it("sends edited assumptions as a list, one per line, ignoring blank lines", async () => {
    const posted = captureApproval();
    review();
    await choose(/^modify/i);
    const box = screen.getByLabelText("Assumptions");
    await userEvent.clear(box);
    await userEvent.type(box, "First{enter}{enter}Second");
    await userEvent.type(screen.getByLabelText(/reason/i), "Clarify assumptions");
    await reviewDecision();
    await userEvent.click(within(await dialog()).getByRole("button", { name: "Approve with changes" }));
    await waitFor(() => expect(posted[0]?.changes).toEqual({ assumptions: ["First", "Second"] }));
  });

  it("offers no way to edit the numbers", async () => {
    review();
    await choose(/^modify/i);
    const form = screen.getByRole("form", { name: "Your decision" });
    expect(within(form).getAllByRole("textbox").map((t) => t.id).sort()).toEqual(["assumptions", "rationale", "reason"]);
  });
});

describe("the confirmation dialog", () => {
  async function open() {
    review();
    await choose(/^approve/i);
    await reviewDecision();
    return dialog();
  }

  it("puts focus on the safe choice, so Enter cannot approve by accident", async () => {
    const d = await open();
    expect(within(d).getByRole("button", { name: "Go back" })).toHaveFocus();
    expect(d).toHaveAttribute("aria-modal", "true");
    expect(d).toHaveAccessibleName("Approve this recommendation?");
  });

  it("closes on Escape or Go back without sending anything, and returns focus to the opener", async () => {
    const posted = captureApproval();
    await open();
    await userEvent.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: /review decision/i })).toHaveFocus();
    await reviewDecision();
    await userEvent.click(within(await dialog()).getByRole("button", { name: "Go back" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(posted).toHaveLength(0);
  });

  it("keeps Tab inside the dialog", async () => {
    const d = await open();
    const [back, confirm] = within(d).getAllByRole("button");
    await userEvent.tab();
    expect(confirm).toHaveFocus();
    await userEvent.tab();
    expect(back).toHaveFocus(); // wrapped to the start, not out to the page
    await userEvent.tab({ shift: true });
    expect(confirm).toHaveFocus();
  });

  it("cannot be confirmed twice: the button is disabled while the request is in flight", async () => {
    let calls = 0;
    captureApproval(async () => {
      calls += 1;
      await new Promise((r) => setTimeout(r, 150));
      return HttpResponse.json({ ...fixtures.completed, workflow_id: ID });
    });
    const d = await open();
    const confirm = within(d).getByRole("button", { name: "Approve" });
    await userEvent.dblClick(confirm);
    expect(await within(d).findByRole("button", { name: "Working…" })).toBeDisabled();
    await screen.findByText("Decision recorded");
    expect(calls).toBe(1);
  });
});

describe("when the server says no", () => {
  it("409: explains someone else may have decided, and the dialog closes", async () => {
    captureApproval(() => HttpResponse.json({ detail: "engagement is completed, not awaiting approval" }, { status: 409 }));
    review();
    await choose(/^approve/i);
    await reviewDecision();
    await userEvent.click(within(await dialog()).getByRole("button", { name: "Approve" }));
    expect(await screen.findByText("This engagement is no longer waiting for a decision")).toBeInTheDocument();
    expect(screen.getByText(/engagement is completed, not awaiting approval/)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("422: shows the server's validation message", async () => {
    captureApproval(() => HttpResponse.json({ detail: "fields not editable: ['cost_usd']" }, { status: 422 }));
    review();
    await choose(/^approve/i);
    await reviewDecision();
    await userEvent.click(within(await dialog()).getByRole("button", { name: "Approve" }));
    expect(await screen.findByText("The decision was not accepted")).toBeInTheDocument();
    expect(screen.getByText(/fields not editable/)).toBeInTheDocument();
  });

  it("500: shows a retryable error and keeps the page usable", async () => {
    captureApproval(() => HttpResponse.json({ detail: "boom" }, { status: 500 }));
    review();
    await choose(/^approve/i);
    await reviewDecision();
    await userEvent.click(within(await dialog()).getByRole("button", { name: "Approve" }));
    expect(await screen.findByText("The server had a problem")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /review decision/i })).toBeEnabled();
  });
});

describe("approval history", () => {
  it("lists who decided, when, what and why, including edits", async () => {
    server.use(
      http.get(`${API}/engagements/:id/approvals`, () =>
        HttpResponse.json([
          {
            decided_at: "2026-10-08T09:30:00+00:00",
            approver_id: "oid-1",
            approver_name: "Pat Partner",
            approver_roles: ["Partner"],
            decision: "modify",
            reason: "Tone down the claim",
            changes: { rationale: "Start small.", assumptions: ["A", "B"] },
            resulting_status: "completed",
          },
        ]),
      ),
    );
    renderApp(`/engagements/${ID}/review`, PARTNER);
    const history = await screen.findByRole("list", { name: "Approval history" });
    expect(history).toHaveTextContent("Modified");
    expect(history).toHaveTextContent("Pat Partner");
    expect(history).toHaveTextContent("(Partner)");
    expect(history).toHaveTextContent("“Tone down the claim”");
    expect(history).toHaveTextContent("Changed: Rationale, Assumptions");
    expect(history).toHaveTextContent("Start small.");
    expect(history).toHaveTextContent("Result: Completed");
  });

  it("says so when nothing has been decided", async () => {
    review();
    expect(await screen.findByText("No decisions yet")).toBeInTheDocument();
  });

  it("is also a tab on the engagement page", async () => {
    renderApp(`/engagements/${ID}`, PARTNER);
    await userEvent.click(await screen.findByRole("tab", { name: "Approvals" }));
    expect(await screen.findByText("No decisions yet")).toBeInTheDocument();
  });
});
