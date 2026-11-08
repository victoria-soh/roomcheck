// The design system's components, in each state.
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { DiscoveryResult } from "../api/types";
import { ConfidenceBadge, EvidenceBadge, PriorityBadge, SourceBadge, StatusBadge } from "./Badge";
import { Button } from "./Button";
import { chipClass } from "./classes";
import { Accordion, Disclosure, EmptyState, Hint, Notice, UndoToast } from "./Feedback";
import { Card, Checkbox, FileInput, RadioRow, StatTile, TextInput, Textarea } from "./Fields";
import { PageHeader } from "./PageHeader";
import { ScanContext } from "./scanContext";

describe("Button", () => {
  it.each([
    ["primary", "bg-lagoon", "text-ink"],
    ["secondary", "border-accent", "text-accent"],
    ["text", "underline", "text-accent"],
    ["destructive", "border-danger", "text-danger"],
    ["destructive-confirm", "bg-danger", "text-on-danger"],
  ] as const)("%s uses the shared tokens", (variant, a, b) => {
    render(<Button variant={variant}>Go</Button>);
    expect(screen.getByRole("button", { name: "Go" })).toHaveClass(a, b, "rounded-control");
  });

  it("unavailable: aria-disabled, still focusable, described by its hint, and inert", async () => {
    const onClick = vi.fn();
    render(
      <>
        <Button variant="primary" unavailable aria-describedby="why" onClick={onClick}>
          Start
        </Button>
        <Hint id="why">Choose an answer first.</Hint>
      </>,
    );
    const b = screen.getByRole("button", { name: "Start" });
    expect(b).toHaveAttribute("aria-disabled", "true");
    expect(b).not.toBeDisabled();
    expect(b).toHaveAccessibleDescription("Choose an answer first.");
    expect(b).toHaveClass("bg-lagoon", "opacity-55"); // the primary look, only paler
    await userEvent.click(b);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("loading: aria-busy with a spinner, and inert", async () => {
    const onClick = vi.fn();
    render(
      <Button variant="primary" loading onClick={onClick}>
        Saving…
      </Button>,
    );
    const b = screen.getByRole("button", { name: "Saving…" });
    expect(b).toHaveAttribute("aria-busy", "true");
    expect(b.querySelector("svg.motion-safe\\:animate-spin")).not.toBeNull();
    await userEvent.click(b);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("comes in two sizes", () => {
    render(
      <>
        <Button size="md">Big</Button>
        <Button size="sm">Small</Button>
      </>,
    );
    expect(screen.getByRole("button", { name: "Big" })).toHaveClass("min-h-5");
    expect(screen.getByRole("button", { name: "Small" })).toHaveClass("min-h-4", "text-sm");
  });
});

describe("Badges", () => {
  it("look different for each kind", () => {
    render(
      <>
        <PriorityBadge level="High" />
        <ConfidenceBadge band="Likely" />
        <StatusBadge status="asked" />
        <EvidenceBadge>Host confirmed</EvidenceBadge>
        <SourceBadge source="network" />
        <SourceBadge source="nearby" />
      </>,
    );
    const priority = screen.getByText("Priority: Look at this first").parentElement!;
    expect(priority).toHaveClass("bg-sev-high-tint", "text-sev-high", "rounded-full");
    expect(priority.querySelector("svg")).not.toBeNull(); // its own icon shape
    expect(screen.getByText("Identification confidence: Likely")).toHaveClass("border-line-strong", "text-muted");
    expect(screen.getByText("Asked")).toHaveClass("rounded-control", "bg-raised");
    expect(screen.getByText("Host confirmed")).toHaveClass("bg-aqua");
    expect(screen.getByText("This network")).toHaveClass("border-accent", "text-accent");
    expect(screen.getByText("Nearby")).toHaveClass("border-accent");
    // Filled teal is only for selected chips.
    expect(chipClass(true)).toContain("bg-lagoon");
    expect(chipClass(false)).not.toContain("bg-lagoon");
  });
});

describe("Feedback", () => {
  it.each([
    ["info", "bg-info-tint"],
    ["warning", "bg-notice"],
    ["error", "bg-error-tint"],
  ] as const)("a %s notice", (tone, cls) => {
    render(<Notice tone={tone} title="Something to know" />);
    expect(screen.getByText("Something to know").closest("div")).toHaveClass(cls);
  });

  it("an empty state says what to do next", () => {
    render(<EmptyState title="Nothing here yet">Run a check first.</EmptyState>);
    expect(screen.getByText("Nothing here yet")).toBeInTheDocument();
    expect(screen.getByText("Run a check first.")).toBeInTheDocument();
  });

  it("disclosure and accordion: a focusable summary that opens the panel", async () => {
    // jsdom doesn't toggle <details> from Enter/Space; the browser does (covered in Playwright).
    render(
      <>
        <Disclosure summary="What does it mean?">Inside</Disclosure>
        <Accordion summary="More">Accordion body</Accordion>
      </>,
    );
    const user = userEvent.setup();
    await user.tab();
    expect(screen.getByText("What does it mean?").closest("summary")).toHaveFocus();
    for (const s of ["What does it mean?", "More"]) {
      await user.click(screen.getByText(s));
      expect(screen.getByText(s).closest("details")).toHaveAttribute("open");
    }
  });

  it("the Undo toast is announced and its button works", async () => {
    const onUndo = vi.fn();
    render(<UndoToast message="Status changed to Asked." onUndo={onUndo} onExpire={() => {}} />);
    const toast = screen.getByText("Status changed to Asked.");
    expect(toast.closest("[aria-live]")).toHaveAttribute("aria-live", "polite");
    await userEvent.click(screen.getByRole("button", { name: "Undo" }));
    expect(onUndo).toHaveBeenCalled();
  });
});

describe("Form controls", () => {
  it("a radio row: the whole row selects, with its hint as the description", async () => {
    const onChange = vi.fn();
    render(<RadioRow name="x" value="yes" checked={false} onChange={onChange} label="Yes" hint="The second line." />);
    const radio = screen.getByRole("radio", { name: "Yes" });
    expect(radio).toHaveAccessibleDescription("The second line.");
    await userEvent.click(screen.getByText("The second line."));
    expect(onChange).toHaveBeenCalled();
  });

  it("a checked radio row has the selected look", () => {
    render(<RadioRow name="x" value="yes" checked onChange={() => {}} label="Yes" />);
    expect(screen.getByRole("radio", { name: "Yes" }).closest("label")).toHaveClass("border-accent", "bg-aqua");
  });

  it("a checkbox: its name, and what it means as the description", async () => {
    const onChange = vi.fn();
    render(<Checkbox label="Handover notes" hint="Off unless you choose it." checked={false} onChange={onChange} />);
    const box = screen.getByRole("checkbox", { name: "Handover notes" });
    expect(box).toHaveAccessibleDescription("Off unless you choose it.");
    await userEvent.click(box);
    expect(onChange).toHaveBeenCalledWith(true);
  });

  it("text input, textarea and file input are labelled, hinted, and say when they're wrong", () => {
    render(
      <>
        <TextInput label="Room name" hint="On the first page." />
        <TextInput label="Name" error="Use up to 40 characters." />
        <Textarea label="Notes" hint="Saved automatically." />
        <FileInput label="Report PDF" hint="The .pdf file." accept=".pdf" onPick={() => {}} />
      </>,
    );
    expect(screen.getByRole("textbox", { name: "Room name" })).toHaveAccessibleDescription("On the first page.");
    const bad = screen.getByRole("textbox", { name: "Name" });
    expect(bad).toHaveAttribute("aria-invalid", "true");
    expect(bad).toHaveAccessibleDescription("Use up to 40 characters.");
    expect(screen.getByRole("textbox", { name: "Notes" })).toHaveAccessibleDescription("Saved automatically.");
    expect(screen.getByLabelText("Report PDF")).toHaveAttribute("type", "file");
  });
});

describe("Stat tile and card", () => {
  it("a static tile, and a filter tile that's filled teal only when pressed", async () => {
    const onClick = vi.fn();
    render(
      <>
        <StatTile label="Static" value="3" />
        <StatTile label="Off" value="2" pressed={false} onClick={onClick} />
        <StatTile label="On" value="5" pressed onClick={() => {}} />
      </>,
    );
    expect(screen.queryByRole("button", { name: /Static/ })).toBeNull();
    const off = screen.getByRole("button", { name: /^Off/ });
    expect(off).toHaveAttribute("aria-pressed", "false");
    expect(off).not.toHaveClass("bg-lagoon");
    expect(screen.getByRole("button", { name: /^On/ })).toHaveClass("bg-lagoon");
    await userEvent.click(off);
    expect(onClick).toHaveBeenCalled();
  });

  it("a card has the standard padding and radius", () => {
    render(
      <Card labelledBy="t">
        <h2 id="t">A group</h2>
      </Card>,
    );
    expect(screen.getByRole("region", { name: "A group" })).toHaveClass("rounded-card", "p-3", "shadow-soft");
  });
});

describe("Page header", () => {
  it("shows the scan-context line after a check, and not before", () => {
    const result = {
      finished_at: "2026-11-03T05:24:49Z",
      mode: "passive",
      room_network: "Example-Home",
      network: { cidr: "192.0.2.0/24" },
    } as unknown as DiscoveryResult;
    const { rerender } = render(<PageHeader focus={false}>Results</PageHeader>);
    expect(screen.queryByText(/Example-Home/)).toBeNull();
    rerender(
      <ScanContext.Provider value={result}>
        <PageHeader focus={false}>Results</PageHeader>
      </ScanContext.Provider>,
    );
    const line = screen.getByText(/Example-Home · .*2026.* · Listening only/);
    expect(within(line).getByText(/This check/)).toHaveClass("sr-only");
  });
});
