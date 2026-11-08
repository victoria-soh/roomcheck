// Things that must say the same everywhere (the Python half is tests/unit/test_consistency.py):
// the demo check's numbers on Results and in the Report summary, and the outside-calls list on
// Start and in Help.
import { screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import en from "../strings/en.json";
import { withBackend } from "../test/backend";
import { BASELINE_NONE, RESULT } from "../test/fixtures";
import { Help } from "./Help";
import { Report } from "./Report";
import { Results } from "./Results";
import { Start } from "./Start";

// The same expectations as the PDF test (tests/unit/test_consistency.py).
const THINGS = 5;
const PER_QUESTION = "Watching 2 · Control 0 · Wi-Fi 3";
const STATUS: Record<string, [string, string | null]> = {
  "Is anything watching?": ["2 things to look at", null],
  "Can someone else control things here?": ["Not detected by the checks that ran", null],
  "Can you trust this Wi-Fi?": ["3 things to look at", "Not checked: the second-address-server check took too long and was stopped"],
};
const COVERAGE = "17 of 18 checks ran";

describe("the demo check counts the same on Results and in the Report summary", () => {
  it("Results: the headline, each question's status and cards, and the coverage line", () => {
    withBackend(<Results result={RESULT} onOpenNearby={vi.fn()} onOpenCompare={vi.fn()} onOpenHandover={vi.fn()} />, {
      "GET /api/baseline": BASELINE_NONE,
    });
    expect(screen.getByRole("heading", { level: 2, name: `${THINGS} things to look at` })).toBeInTheDocument();
    let cards = 0;
    for (const [name, [status, partly]] of Object.entries(STATUS)) {
      const region = screen.getByRole("region", { name });
      const head = document.getElementById(region.getAttribute("aria-labelledby")!)!.parentElement!;
      expect(head).toHaveTextContent(status);
      if (partly) expect(head).toHaveTextContent(partly);
      else expect(head).not.toHaveTextContent("Not checked");
      // The status line's number is the cards shown under it.
      const n = within(region).queryAllByRole("article").length;
      if (status.endsWith("to look at")) expect(status.startsWith(`${n} `)).toBe(true);
      cards += n;
    }
    expect(cards).toBe(THINGS);
    expect(document.body).toHaveTextContent(COVERAGE);
    expect(document.getElementById("coverage-limits")).toHaveTextContent(COVERAGE);
  });

  it("the Report summary: the same things to look at per question, and the same coverage", async () => {
    withBackend(<Report result={RESULT} onOpenHandover={vi.fn()} />, { "GET /api/report/defaults": { room_label: null } });
    const summary = await screen.findByRole("region", { name: "This report will contain" });
    expect(summary).toHaveTextContent(`Things to look at${THINGS}: ${PER_QUESTION}`);
    expect(summary).toHaveTextContent(`Coverage${COVERAGE}`);
  });
});

describe("the outside-calls list: in full in Help (and the README), never on Start", () => {
  // Each call as the README says it: "<call> (<when>): <what's sent>".
  const readmeLine = (c: { call: string; when: string; sent: string }) => `${c.call} (${c.when}): ${c.sent}`;
  const README = [en.privacy.calls.ai, en.privacy.calls.nvd, en.privacy.calls.tsa].map(readmeLine);

  it("word for word, every call in Help's table; Start only links to it", async () => {
    withBackend(<Help />);
    await screen.findByText(en.privacy.intro);
    const table = within(screen.getByRole("region", { name: "What's sent" })).getByRole("table");
    expect(within(table).getAllByRole("columnheader").map((c) => c.textContent)).toEqual(["Call", "When", "What's sent"]);
    const rows = within(table)
      .getAllByRole("row")
      .slice(1)
      .map((r) => [...r.children].map((c) => c.textContent ?? ""));
    expect(rows.map(([call, when, sent]) => readmeLine({ call: call!, when: when!, sent: sent! }))).toEqual(README);
  });

  it("Start has one line and a link, not a second copy of the list", () => {
    withBackend(<Start onStart={vi.fn()} starting={false} error={null} />);
    expect(screen.getByRole("button", { name: "what's sent" })).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
    expect(document.body).not.toHaveTextContent(en.privacy.calls.nvd.sent);
  });
});
