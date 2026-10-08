import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { BarList, ChartCard, Legend, Meter, TrendChart } from "./charts";

describe("Legend", () => {
  it("appears for two or more series and not for one (the title already names a single series)", () => {
    const { rerender } = render(<Legend items={[{ label: "A", color: "red" }, { label: "B", color: "blue" }]} />);
    expect(screen.getByRole("list", { name: "Legend" })).toHaveTextContent("A");
    rerender(<Legend items={[{ label: "Only", color: "red" }]} />);
    expect(screen.queryByRole("list", { name: "Legend" })).not.toBeInTheDocument();
  });

  it("puts the series name in text ink, with the colour only on a swatch", () => {
    render(<Legend items={[{ label: "Groundedness", color: "rgb(1, 2, 3)" }, { label: "Cost", color: "red" }]} />);
    const name = screen.getByText("Groundedness");
    expect(name).not.toHaveStyle({ color: "rgb(1, 2, 3)" });
    expect(name.previousElementSibling).toHaveStyle({ background: "rgb(1, 2, 3)" });
  });
});

describe("ChartCard", () => {
  const table = { columns: ["Period", "Cost"], rows: [["Oct 1", "$1.00"], ["Oct 2", null]] };

  it("shows the chart first and the same data as a table on request", async () => {
    render(<ChartCard title="Cost" table={table}><p>the chart</p></ChartCard>);
    expect(screen.getByText("the chart")).toBeInTheDocument();
    const toggle = screen.getByRole("button", { name: "View as table" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(toggle);
    const grid = screen.getByRole("table", { name: "Cost" });
    expect(within(grid).getAllByRole("columnheader").map((c) => c.textContent)).toEqual(["Period", "Cost"]);
    expect(within(grid).getByText("$1.00")).toBeInTheDocument();
    expect(within(grid).getByText("n/a")).toBeInTheDocument(); // a missing value is stated, not left blank
    expect(screen.queryByText("the chart")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "View chart" }));
    expect(screen.getByText("the chart")).toBeInTheDocument();
  });

  it("hides the legend in table view, where the column headers do its job", async () => {
    render(<ChartCard title="Q" table={table} legend={[{ label: "A", color: "red" }, { label: "B", color: "blue" }]}><p>c</p></ChartCard>);
    expect(screen.getByRole("list", { name: "Legend" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "View as table" }));
    expect(screen.queryByRole("list", { name: "Legend" })).not.toBeInTheDocument();
  });
});

describe("TrendChart", () => {
  it("renders with an accessible name that points to the table view", () => {
    render(<TrendChart data={[{ label: "Oct 1", a: 0.5 }, { label: "Oct 2", a: 0.7 }]} series={[{ key: "a", label: "Groundedness", color: "var(--series-1)" }]} />);
    expect(screen.getByRole("img", { name: /Groundedness over time\. A table view is available/ })).toBeInTheDocument();
  });
});

describe("BarList", () => {
  const items = [{ label: "financial_agent", value: 0.04, hint: "3 calls" }, { label: "risk_agent", value: 0.02 }];
  it("draws bars in proportion to the largest, with the value at the tip", () => {
    render(<BarList ariaLabel="Cost by agent" items={items} format={(v) => `$${v.toFixed(2)}`} />);
    const rows = within(screen.getByRole("list", { name: "Cost by agent" })).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("$0.04");
    const widths = rows.map((r) => (r.querySelector("span.block") as HTMLElement).style.width);
    expect(widths).toEqual(["100%", "50%"]);
  });

  it("keeps bars thin with a rounded data end, and shows a tiny value as a visible sliver", () => {
    render(<BarList ariaLabel="x" items={[{ label: "big", value: 1000 }, { label: "tiny", value: 0.001 }]} format={String} />);
    const bars = [...document.querySelectorAll("span.block")] as HTMLElement[];
    expect(bars[0]).toHaveClass("h-4"); // 16px, under the 24px cap
    expect(bars[0]?.style.borderRadius).toMatch(/^0(px)? 4px 4px 0(px)?$/); // square at the baseline, 4px at the data end
    expect(parseFloat(bars[1]!.style.width)).toBeGreaterThanOrEqual(1.5);
  });

  it("copes with all-zero values", () => {
    render(<BarList ariaLabel="z" items={[{ label: "a", value: 0 }]} format={String} />);
    expect(screen.getByRole("list", { name: "z" })).toHaveTextContent("0");
  });
});

describe("Meter", () => {
  const fmt = (v: number) => String(v);
  it.each([
    [10, 100, "within budget"],
    [85, 100, "nearly used"],
    [100, 100, "over budget"],
    [150, 100, "over budget"],
  ])("%i of %i reads as %s, in words as well as colour", (used, limit, words) => {
    render(<Meter label="Cost" used={used} limit={limit} format={fmt} />);
    const meter = screen.getByRole("meter", { name: "Cost" });
    expect(meter).toHaveAttribute("aria-valuetext", expect.stringContaining(words));
    expect(meter).toHaveAttribute("aria-valuenow", String(Math.min(used, limit)));
    expect(screen.getByText(words)).toBeInTheDocument();
  });

  it("does not divide by a zero limit", () => {
    render(<Meter label="Tools" used={0} limit={0} format={fmt} />);
    expect(screen.getByRole("meter")).toHaveAttribute("aria-valuenow", "0");
  });
});
