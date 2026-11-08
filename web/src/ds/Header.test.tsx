// The one header: what each stage shows, the "New check" confirmation, and the open-task count.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AppHeader, type Page, type Stage } from "./AppHeader";

function header(over: Partial<Parameters<typeof AppHeader>[0]> & { stage: Stage }) {
  const props = {
    current: (over.stage === "results" ? "results" : "check") as Page,
    onNavigate: vi.fn(),
    hasResults: over.stage === "results",
    baselineSaved: false,
    openTasks: 0,
    onNewCheck: vi.fn(),
    onSaveBaseline: vi.fn(() => Promise.resolve()),
    ...over,
  };
  render(<AppHeader {...props} />);
  return props;
}

const tools = () => screen.getByRole("navigation", { name: "Help and tools" });
const main = () => screen.queryByRole("navigation", { name: "Main" });

describe("Header stages", () => {
  it("start: Help and Verify only; no main navigation and no New check", () => {
    header({ stage: "start" });
    expect(main()).toBeNull();
    const names = within(tools())
      .getAllByRole("button")
      .map((b) => b.textContent);
    expect(names).toEqual(["Verify a report", "Help"]);
    expect(screen.queryByRole("button", { name: "New check" })).toBeNull();
  });

  it("start with a saved move-in scan also offers Compare", () => {
    header({ stage: "start", baselineSaved: true });
    expect(within(tools()).getByRole("button", { name: "Compare" })).toBeInTheDocument();
  });

  it("scanning: 'Check in progress' and Help, nothing else", async () => {
    const p = header({ stage: "scanning", current: "help" });
    expect(main()).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Check in progress" }));
    expect(p.onNavigate).toHaveBeenCalledWith("check");
    expect(within(tools()).getAllByRole("button").map((b) => b.textContent)).toEqual(["Help"]);
    expect(screen.queryByRole("button", { name: "New check" })).toBeNull();
  });

  it("scanning, on the check itself: the indicator isn't a link to where you are", () => {
    header({ stage: "scanning", current: "check" });
    expect(screen.getByText("Check in progress").closest("button")).toBeNull();
  });

  it("after a check: the full navigation, Verify at the far right, and New check", () => {
    header({ stage: "results" });
    const nav = main()!;
    const names = within(nav)
      .getAllByRole("button")
      .map((b) => b.textContent);
    expect(names).toEqual(["Results", "Nearby", "Handover", "Compare", "Report", "Verify a report"]);
    // Verify moves out of the brand row into the nav row.
    expect(within(tools()).queryByRole("button", { name: "Verify a report" })).toBeNull();
    expect(screen.getByRole("button", { name: "New check" })).toBeInTheDocument();
  });

  it("exactly one page is current, shown by an underline and bold text, never a fill", () => {
    header({ stage: "results", current: "nearby" });
    const current = screen.getAllByRole("button").filter((b) => b.getAttribute("aria-current") === "page");
    expect(current).toHaveLength(1);
    expect(current[0]).toHaveTextContent("Nearby");
    expect(current[0]).toHaveClass("border-accent", "font-bold");
    expect(current[0]!.className).not.toMatch(/\bbg-/);
  });

  it("navigates, and the current page doesn't navigate to itself", async () => {
    const p = header({ stage: "results", current: "results" });
    await userEvent.click(screen.getByRole("button", { name: "Results" }));
    expect(p.onNavigate).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Report" }));
    expect(p.onNavigate).toHaveBeenCalledWith("report");
  });
});

describe("Handover open-task count", () => {
  it("shows '· 2', read out as '2 open tasks'; no other tab gets a count", () => {
    header({ stage: "results", openTasks: 2 });
    const tab = screen.getByRole("button", { name: /^Handover\s*,\s*2 open tasks$/ });
    expect(within(tab).getByText("· 2")).toHaveAttribute("aria-hidden", "true");
    for (const other of ["Results", "Nearby", "Compare", "Report", "Verify a report"]) {
      expect(screen.getByRole("button", { name: other })).toHaveTextContent(new RegExp(`^${other}$`));
    }
  });

  it("uses the singular for one task, and shows nothing for none", () => {
    const { unmount } = render(
      <AppHeader stage="results" current="results" onNavigate={() => {}} hasResults baselineSaved openTasks={1} onNewCheck={() => {}} onSaveBaseline={() => Promise.resolve()} />,
    );
    expect(screen.getByRole("button", { name: /^Handover\s*,\s*1 open task$/ })).toBeInTheDocument();
    unmount();
    header({ stage: "results", openTasks: 0 });
    expect(screen.getByRole("button", { name: "Handover" })).toHaveTextContent(/^Handover$/);
  });
});

describe("New check", () => {
  const BODY = /results replace the current ones on Results, Nearby and Report.*handover tasks, statuses and notes are saved on this laptop and kept/;

  it("with a saved move-in scan: says what's replaced and what's kept, then starts", async () => {
    const p = header({ stage: "results", baselineSaved: true });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "New check" }));
    const panel = screen.getByRole("group", { name: "Start a new check?" });
    expect(panel).toHaveTextContent(BODY);
    expect(within(panel).queryByRole("button", { name: "Save as my move-in scan first" })).toBeNull();
    expect(within(panel).getByRole("button", { name: "Keep these results" })).toHaveFocus();
    await user.click(within(panel).getByRole("button", { name: "Start a new check" }));
    expect(p.onNewCheck).toHaveBeenCalledTimes(1);
    expect(p.onSaveBaseline).not.toHaveBeenCalled();
  });

  it("without one: offers to save it first, then starts", async () => {
    const p = header({ stage: "results", baselineSaved: false });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "New check" }));
    const panel = screen.getByRole("group", { name: "Start a new check?" });
    expect(panel).toHaveTextContent(BODY);
    expect(panel).toHaveTextContent("You haven't saved a move-in scan yet.");
    await user.click(within(panel).getByRole("button", { name: "Save as my move-in scan first" }));
    await waitFor(() => expect(p.onNewCheck).toHaveBeenCalledTimes(1));
    expect(p.onSaveBaseline).toHaveBeenCalledTimes(1);
  });

  it("without one: can also start without saving", async () => {
    const p = header({ stage: "results", baselineSaved: false });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "New check" }));
    await user.click(screen.getByRole("button", { name: "Start without saving" }));
    expect(p.onNewCheck).toHaveBeenCalledTimes(1);
    expect(p.onSaveBaseline).not.toHaveBeenCalled();
  });

  it("if saving fails, it says so and doesn't start", async () => {
    const p = header({ stage: "results", onSaveBaseline: vi.fn(() => Promise.reject(new Error("x"))) });
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "New check" }));
    await user.click(screen.getByRole("button", { name: "Save as my move-in scan first" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("couldn't be saved");
    expect(p.onNewCheck).not.toHaveBeenCalled();
  });

  it("'Keep these results' and Escape close it, and focus returns to New check", async () => {
    const p = header({ stage: "results", baselineSaved: true });
    const user = userEvent.setup();
    const opener = screen.getByRole("button", { name: "New check" });
    await user.click(opener);
    expect(opener).toHaveAttribute("aria-expanded", "true");
    await user.click(screen.getByRole("button", { name: "Keep these results" }));
    expect(screen.queryByRole("group", { name: "Start a new check?" })).toBeNull();
    expect(opener).toHaveFocus();
    await user.click(opener);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("group", { name: "Start a new check?" })).toBeNull();
    expect(opener).toHaveFocus();
    expect(p.onNewCheck).not.toHaveBeenCalled();
  });
});

describe("Sticky header", () => {
  it("is sticky, and gets its light shadow only once content scrolls under it", async () => {
    header({ stage: "results" });
    const banner = screen.getByRole("banner");
    expect(banner).toHaveClass("sticky", "top-0", "bg-surface", "border-b");
    expect(banner).not.toHaveClass("shadow-soft");
    Object.defineProperty(window, "scrollY", { value: 200, configurable: true });
    window.dispatchEvent(new Event("scroll"));
    await waitFor(() => expect(banner).toHaveClass("shadow-soft"));
    Object.defineProperty(window, "scrollY", { value: 0, configurable: true });
  });

  it("the page reserves room under it, so focus and targets aren't hidden (Playwright checks positions)", async () => {
    const { readFileSync } = await import("node:fs");
    const css = readFileSync("src/styles/index.css", "utf8");
    expect(css).toMatch(/scroll-padding-top:\s*calc\(var\(--header-height-compact\)/);
    expect(css).toMatch(/html:has\(header nav\[aria-label="Main"\]\)[^{]*\{[^}]*--header-height\)/);
  });
});
