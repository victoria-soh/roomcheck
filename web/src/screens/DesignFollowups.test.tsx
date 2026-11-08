// Design follow-ups: weak camera clues, one scale per card, coverage wording, the physical
// check opened from a camera card, and listening-only said once.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { DiscoveryResult } from "../api/types";
import en from "../strings/en.json";
import { withBackend } from "../test/backend";
import { CAM_SUBJECT, HANDOVER, NOTHING_FOUND, NOTHING_FOUND_COMPLETE, RESULT } from "../test/fixtures";
import { Results } from "./Results";

function results(result: DiscoveryResult = RESULT, routes = {}) {
  const handlers = { onOpenNearby: vi.fn(), onOpenCompare: vi.fn(), onOpenHandover: vi.fn(), onOpenHelp: vi.fn() };
  return { ...withBackend(<Results result={result} {...handlers} />, routes), ...handlers };
}

describe("A weak camera clue stays visible", () => {
  it("is said under Is anything watching?, and never counted", () => {
    results(NOTHING_FOUND_COMPLETE);
    const watching = screen.getByRole("region", { name: "Is anything watching?" });
    expect(watching).toHaveTextContent(
      "1 device gave a weak camera clue. Not enough to flag it, but worth a look during the physical check.",
    );
    expect(watching).toHaveTextContent("Not detected by the checks that ran");
    expect(screen.getByRole("heading", { level: 2, name: "Not detected by the checks that ran" })).toBeInTheDocument();
  });

  it("isn't said when there's no such device", () => {
    results();
    expect(document.body).not.toHaveTextContent(/weak camera clue/);
  });
});

describe("One scale per card", () => {
  it("the card says the urgency word; confidence and the priority term only under Evidence and details", () => {
    results();
    const cam = screen.getByRole("article", { name: /^Likely camera/ });
    expect(cam).toHaveTextContent("Look at this first");
    const details = within(cam).getByText("Evidence and details").closest("details")!;
    const outside = cam.textContent!.replace(details.textContent!, "");
    expect(outside).not.toMatch(/Identification confidence|\bHigh\b/);
    expect(details).toHaveTextContent("Identification confidence: Likely · Priority: Look at this first");
    expect(Object.values(en.results.severity)).toEqual(["Look at this first", "Look at this soon", "Worth knowing", "For information"]);
  });
});

describe("Coverage rows in their own words", () => {
  it("say what each check heard or what nothing flagged means, never safe or passed", () => {
    results(NOTHING_FOUND_COMPLETE);
    const limits = document.getElementById("coverage-limits")!;
    for (const text of ["No copies of your Wi-Fi name", "No weak encryption found", "Address lookups looked normal", "WPS not advertised"]) {
      expect(limits).toHaveTextContent(text);
    }
    expect(limits).toHaveTextContent(/Heard \d+ nearby networks/);
    expect(limits).not.toHaveTextContent(/\b(safe|passed)\b/i);
  });
});

describe("Find it physically", () => {
  it("opens the physical check with the camera's places first and its Where is it? question", async () => {
    const { calls } = results(RESULT, { "POST /api/locations": { ...HANDOVER, locations: { [CAM_SUBJECT]: "outside" } } });
    const cam = screen.getByRole("article", { name: /^Likely camera/ });
    await userEvent.click(within(cam).getByRole("button", { name: "Find it physically" }));
    const check = document.getElementById("physical-check") as HTMLDetailsElement;
    await waitFor(() => expect(check.open).toBe(true));
    expect(check).toHaveTextContent("For the camera-like device: the places most likely to hide one are listed first.");
    const boxes = within(check).getAllByRole("checkbox");
    expect(boxes[0]).toHaveAccessibleName(/^Small holes or lenses/);
    // The same question as the card, sharing its answer.
    const where = within(check).getByRole("group", { name: "Where is it?" });
    await userEvent.click(within(where).getByRole("radio", { name: "Outside or a shared area" }));
    expect(calls.find((c) => c.url === "/api/locations")?.body).toEqual({ subject: CAM_SUBJECT, location: "outside" });
    await waitFor(() =>
      expect(within(within(cam).getByRole("group", { name: "Where is it?" })).getByRole("radio", { name: "Outside or a shared area" })).toBeChecked(),
    );
  });
});

describe("Listening only, said once", () => {
  it("the nothing-found page has the listening-only section and no next-time line", () => {
    results(NOTHING_FOUND);
    expect(screen.getByRole("region", { name: "This was a listening-only check" })).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent("To check more next time");
    expect(screen.getAllByText(en.results.listening.adds)).toHaveLength(1);
  });
});
