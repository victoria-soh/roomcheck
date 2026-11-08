// The Results page's UI/UX and wording pass: could-mean vs observed, Coverage and limits, page
// order, one counting rule, compact Low/Info rows, card order, network cards, evidence, copy.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { DiscoveryResult } from "../api/types";
import { headline, pageCounts, shortPhrase } from "../results/summary";
import en from "../strings/en.json";
import { withBackend } from "../test/backend";
import { BASELINE_NONE, NOTHING_FOUND, NOTHING_FOUND_COMPLETE, RESULT } from "../test/fixtures";
import i18n from "../i18n";
import { Results } from "./Results";

function show(result: DiscoveryResult = RESULT) {
  const handlers = { onOpenNearby: vi.fn(), onOpenCompare: vi.fn(), onOpenHandover: vi.fn(), onOpenHelp: vi.fn() };
  withBackend(<Results result={result} {...handlers} />, { "GET /api/baseline": BASELINE_NONE });
  return handlers;
}
const part = (card: HTMLElement, name: string) => within(card).getByRole("group", { name });

describe("A1. What it could mean never repeats What we observed", () => {
  it("on every card, the two parts say different things", async () => {
    show();
    // Open the compact rows so every card's parts are there.
    for (const summary of document.querySelectorAll<HTMLElement>("details[data-compact] > summary")) await userEvent.click(summary);
    const cards = screen.getAllByRole("article");
    expect(cards.length).toBeGreaterThanOrEqual(3);
    for (const card of cards) {
      // What we observed: the clue list, or the rule's one sentence.
      const observed = part(card, "What we observed").textContent!.replace("What we observed", "").trim();
      const meaning = part(card, "What it could mean").textContent!.replace("What it could mean", "").trim();
      expect(meaning).not.toBe("");
      expect(meaning.toLowerCase()).not.toBe(observed.toLowerCase());
    }
    const wps = screen.getByRole("article", { name: "Router advertises WPS" });
    expect(part(wps, "What it could mean")).toHaveTextContent("Someone nearby could use WPS to get onto this Wi-Fi without the password.");
  });
});

describe("B. One section for coverage and limits, in the page's order", () => {
  it("summary, the four questions, all devices, then Coverage and limits; no Nearby card", async () => {
    show();
    await screen.findByRole("region", { name: "Move-in scan" });
    const order = Array.from(document.querySelectorAll("div.space-y-4 > *"))
      .map((el) => el.getAttribute("aria-labelledby") ?? el.id ?? el.tagName)
      .filter(Boolean);
    // (The page heading and the summary come first; they carry no id.)
    expect(order).toEqual([
      "question-watching",
      "question-control",
      "question-wifi",
      "question-changes",
      "physical-check",
      "all-devices",
      "coverage-limits",
    ]);
    // The move-in scan is under What's changed since move-in?
    expect(screen.getByRole("region", { name: "What's changed since move-in?" })).toContainElement(
      screen.getByRole("region", { name: "Move-in scan" }),
    );
    expect(screen.queryByRole("heading", { name: "Nearby Wi-Fi and Bluetooth" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Network health" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Scan coverage" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Not checked this time" })).toBeNull();
    // No chips: the Nearby chip and the priority filters are gone.
    expect(screen.queryByRole("button", { name: /Nearby signals/ })).toBeNull();
  });

  it("rows say in their own words what a check that ran found, never a generic result", async () => {
    show();
    await userEvent.click(screen.getByRole("button", { name: "See what didn't" }));
    const limits = document.getElementById("coverage-limits")!;
    expect(within(limits).getByRole("row", { name: /Checking how your Wi-Fi connection is encrypted/ })).toHaveTextContent(/encryptedNo weak encryption found$/);
    expect(limits).not.toHaveTextContent(/\b(safe|passed)\b/i);
    expect(limits).not.toHaveTextContent("This check ran and found nothing to look at");
  });
});

describe("Coverage rows never say Not checked twice", () => {
  const raw = (reason: string) => ({ ...RESULT.checks[3]!, status: "skipped" as const, reason, short_reason: undefined });
  for (const [name, result] of [
    ["the demo check", RESULT],
    ["the nothing-found check", NOTHING_FOUND],
    [
      "raw messages without a short reason",
      {
        ...RESULT,
        checks: [
          { ...raw("Not checked, because you chose a listen-only check."), name: "a", label: "A" },
          { ...raw("Not checked: no device answered the address request."), name: "b", label: "B" },
          { ...raw("Not checked, because you chose not to run the nearby check."), name: "c", label: "C" },
        ],
      } as DiscoveryResult,
    ],
  ] as const) {
    it(`${name}`, async () => {
      show(result);
      const limits = document.getElementById("coverage-limits") as HTMLDetailsElement;
      limits.open = true;
      const rows = within(limits).getAllByRole("row").slice(1).map((r) => r.textContent ?? "");
      expect(rows.length).toBeGreaterThan(0);
      for (const row of rows) expect(row.match(/not checked/gi)?.length ?? 0).toBeLessThanOrEqual(1);
    });
  }

  it("each reason is a short phrase after 'Not checked:'", () => {
    expect(shortPhrase("Not checked, because you chose a listen-only check.")).toBe("you chose a listen-only check");
    expect(shortPhrase("Not checked: no device answered the address request.")).toBe("no device answered the address request");
    expect(shortPhrase("Turn on Bluetooth to check for nearby trackers.")).toBe("Turn on Bluetooth to check for nearby trackers");
  });
});

describe("C7. One counting rule: the headline and every question agree", () => {
  it("the headline's number is the sum of the questions' numbers and of the cards shown", () => {
    const n = pageCounts(RESULT);
    expect(n).toEqual({
      things: 5,
      perQuestion: [
        { id: "watching", things: 2 },
        { id: "control", things: 0 },
        { id: "wifi", things: 3 },
      ],
    });
    expect(headline(RESULT, i18n.t).title).toBe("5 things to look at");
    show();
    const cards = ["Is anything watching?", "Can someone else control things here?", "Can you trust this Wi-Fi?"].map(
      (name) => within(screen.getByRole("region", { name })).queryAllByRole("article").length,
    );
    expect(cards).toEqual([2, 0, 3]);
  });

  it("singular form: 1 thing to look at", () => {
    const one: DiscoveryResult = { ...RESULT, findings: RESULT.findings.filter((f) => f.rule_id === "R-HIDDEN") };
    expect(headline(one, i18n.t).title).toBe("1 thing to look at");
  });
});

describe("D. Finding cards", () => {
  it("Low and Info are a compact row (icon, title, priority) that opens to the full card", async () => {
    show();
    const hidden = screen.getByRole("article", { name: /^Hidden Wi-Fi network with a strong signal/ });
    const row = hidden.querySelector("details[data-compact]") as HTMLDetailsElement;
    expect(row.open).toBe(false);
    expect(within(hidden).getByRole("heading", { level: 3 })).toHaveTextContent("Hidden Wi-Fi network with a strong signalWorth knowing");
    await userEvent.click(row.querySelector("summary")!);
    expect(row.open).toBe(true);
    expect(part(hidden, "What you can do")).toBeInTheDocument();
    // High and Medium are full cards.
    const cam = screen.getByRole("article", { name: /^Likely camera/ });
    expect(cam.querySelector("details[data-compact]")).toBeNull();
  });

  it("card order: observed, Do you recognise this device?, could mean, what you can do, camera, evidence", () => {
    show();
    const cam = screen.getByRole("article", { name: /^Likely camera/ });
    const marks = [
      part(cam, "What we observed"),
      within(cam).getByRole("group", { name: "Do you recognise this device?" }),
      part(cam, "What it could mean"),
      part(cam, "What you can do"),
      within(cam).getByText("Found a hidden camera? See what to do"),
      within(cam).getByText("Evidence and details"),
    ];
    for (let i = 1; i < marks.length; i++) {
      expect(marks[i - 1]!.compareDocumentPosition(marks[i]!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
    // The name box only after Mine or Host's.
    expect(within(cam).queryByRole("textbox", { name: "Your name for it (optional)" })).toBeNull();
    // The hidden-camera warning is inside its expander only.
    const expander = within(cam).getByText("Found a hidden camera? See what to do").closest("details")!;
    expect(expander).not.toHaveAttribute("open");
    expect(expander).toHaveTextContent(RESULT.findings[0]!.guidance[0]!);
  });

  it("network cards: no '· This network' suffix, no pill, no identification confidence; only Priority", () => {
    show();
    const wps = screen.getByRole("article", { name: "Router advertises WPS" });
    expect(wps).not.toHaveTextContent("Identification confidence");
    expect(wps).toHaveTextContent("Priority: Look at this soon");
    expect(within(wps).queryByText("This network")).toBeNull();
  });

  it("Evidence and details: no repeated badge or title for a one-finding card, no 'Why we think this'", async () => {
    show();
    const wps = screen.getByRole("article", { name: "Router advertises WPS" });
    await userEvent.click(within(wps).getByText("Evidence and details"));
    const details = within(wps).getByText("Evidence and details").closest("details")!;
    expect(within(details).queryByRole("heading")).toBeNull();
    expect(details).not.toHaveTextContent("Why we think this");
    expect(details).toHaveTextContent(RESULT.findings.find((f) => f.rule_id === "R-WPS")!.evidence[0]!);
  });

  it("card buttons stack full width on a phone (w-full below sm)", async () => {
    show();
    const cam = screen.getByRole("article", { name: /^Likely camera/ });
    const draft = await within(cam).findByRole("button", { name: "Draft a message to the host" });
    expect(draft.className).toMatch(/\bw-full\b/);
    expect(draft.parentElement!.className).toMatch(/\bflex-col\b/);
  });
});

describe("E and F. Wording, buttons and the nothing-found state", () => {
  it("host, never landlord, in any string", () => {
    const values: string[] = [];
    const walk = (v: unknown) => {
      if (typeof v === "string") values.push(v);
      else if (v && typeof v === "object") Object.values(v).forEach(walk);
    };
    walk(en);
    // Only "the landlord's agent", whom a renter reports a hidden camera to (Help).
    expect(values.filter((v) => /landlord(?!'s agent)/i.test(v))).toEqual([]);
  });

  it("the priority helper, and the rules link opens Help at how priorities are set", async () => {
    const { onOpenHelp } = show();
    // No priority filter any more: priority is a label on each card.
    expect(screen.queryByText("Choose a priority to filter.")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Fixed rules set every priority." }));
    expect(onOpenHelp).toHaveBeenCalledWith("help-priority");
  });

  it("only the Review button is filled; the move-in button is outlined", async () => {
    show();
    const review = screen.getByRole("button", { name: "Review camera-like device" });
    const save = await screen.findByRole("button", { name: "Save as my move-in scan" });
    expect(review.className).toContain("bg-lagoon");
    expect(save.className).not.toContain("bg-lagoon");
  });

  it("nothing found: the heading stays, chips hidden, Coverage and limits open", async () => {
    show(NOTHING_FOUND_COMPLETE);
    expect(screen.getByRole("heading", { level: 2, name: "Not detected by the checks that ran" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Findings by priority" })).toBeNull();
    await waitFor(() => expect((document.getElementById("coverage-limits") as HTMLDetailsElement).open).toBe(true));
  });
});
