// Real-world features: the physical check, asking for permission, the stay type, hidden-camera
// guidance, and the Results fixes that came with them.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { DiscoveryResult, HandoverState } from "../api/types";
import en from "../strings/en.json";
import { withBackend, type Call } from "../test/backend";
import { CAM_FINDING, CAM_SUBJECT, HANDOVER, NOTHING_FOUND, NOTHING_FOUND_COMPLETE, RESULT } from "../test/fixtures";
import { Help } from "./Help";
import { Results } from "./Results";
import { Start } from "./Start";

function results(result: DiscoveryResult = RESULT, routes = {}) {
  const handlers = { onOpenNearby: vi.fn(), onOpenCompare: vi.fn(), onOpenHandover: vi.fn(), onOpenHelp: vi.fn() };
  return { ...withBackend(<Results result={result} {...handlers} />, routes), ...handlers };
}
const statusIcon = (id: string) => document.getElementById(`question-${id}`)!.parentElement!.querySelector("p svg")!;

describe("Results fixes", () => {
  it("the summary sentence is the top finding and its strongest clue", () => {
    results();
    const banner = screen.getByRole("region", { name: "5 things to look at" });
    expect(banner).toHaveTextContent("Likely camera: it offers a live video stream, the kind security cameras use.");
  });

  it("a question with things to look at shows its highest priority's icon; the dot is for the rest", () => {
    results();
    expect(statusIcon("watching")).toHaveClass("lucide-octagon-alert"); // High: the camera
    expect(statusIcon("wifi")).toHaveClass("lucide-triangle-alert"); // Medium: WPS
    expect(statusIcon("control")).toHaveClass("lucide-circle-dot"); // Not detected
    for (const id of ["watching", "control", "wifi"]) expect(statusIcon(id)).not.toHaveClass("lucide-check");
  });

  it("one line under the summary says how findings are explained and that types are unconfirmed", () => {
    results();
    const line = screen.getByText(/^AI explains findings in plain words\. Device types are unconfirmed: clues, not proof\./);
    expect(within(line.closest("p")!).getByRole("button", { name: "Fixed rules set every priority." })).toBeInTheDocument();
  });

  it("without AI, the same line uses the standard-words wording", () => {
    results({ ...RESULT, explanations: { ai_status: "off", items: [], landlord_message: null } });
    expect(screen.getByText(/^Findings are explained in standard words\. Device types are unconfirmed: clues, not proof\./)).toBeInTheDocument();
  });

  it("the tracker card asks Do you recognise this device?, sharing the answer with Nearby", async () => {
    const { calls } = results(RESULT, {
      "POST /api/answers": (call: Call) => ({ ...HANDOVER, answers: { [(call.body as { subject: string }).subject]: "mine" } }),
    });
    const tracker = screen.getByRole("article", { name: /^Item tracker nearby/ });
    const group = within(tracker).getByRole("group", { name: "Do you recognise this device?" });
    await userEvent.click(within(group).getByRole("radio", { name: "Mine" }));
    const tracked = RESULT.findings.find((f) => f.rule_id === "R-TRACKER")!;
    await waitFor(() => expect(calls.find((c) => c.url === "/api/answers")?.body).toMatchObject({ subject: tracked.subject, answer: "mine" }));
  });
});

describe("The physical check", () => {
  it("is offered after the questions when there are things to look at, collapsed", () => {
    results();
    const details = document.getElementById("physical-check") as HTMLDetailsElement;
    expect(details).toHaveTextContent("Do a 3-minute physical check");
    expect(details.open).toBe(false);
  });

  it("is prominent and open on the nothing-found page, straight after the summary", () => {
    results(NOTHING_FOUND_COMPLETE);
    const details = document.getElementById("physical-check") as HTMLDetailsElement;
    expect(details.open).toBe(true);
    const order = [...document.querySelectorAll("div.space-y-4 > *")].map((el) => el.id || el.getAttribute("aria-labelledby"));
    expect(order.indexOf("physical-check")).toBeLessThan(order.indexOf("question-watching"));
  });

  it("lists every place with a tick box and an optional note, saved on this laptop", async () => {
    const after: HandoverState = { ...HANDOVER, physical: { items: { smoke_detector: { looked: true, note: "" } }, done_at: null } };
    const { calls } = results(NOTHING_FOUND_COMPLETE, { "POST /api/physical": after });
    const details = document.getElementById("physical-check")!;
    expect(within(details).getAllByRole("checkbox")).toHaveLength(8);
    for (const label of Object.values(en.physical.items)) {
      expect(within(details).getByRole("checkbox", { name: (name) => name.startsWith(label) })).not.toBeChecked();
    }
    await userEvent.click(within(details).getByRole("checkbox", { name: /^Smoke detector/ }));
    expect(calls.find((c) => c.url === "/api/physical")?.body).toEqual({ item: "smoke_detector", looked: true });
    expect(await within(details).findByText("1 of 8 looked at")).toBeInTheDocument();
    // A note box only for the places ticked.
    const notes = within(details).getAllByRole("textbox", { name: "Note (optional)" });
    expect(notes).toHaveLength(1);
    await userEvent.type(notes[0]!, "Small light on the side");
    await userEvent.tab();
    await waitFor(() =>
      expect(calls.filter((c) => c.url === "/api/physical").map((c) => c.body)).toContainEqual({ item: "smoke_detector", note: "Small light on the side" }),
    );
  });

  it("Done ends with a note to record doubts, never that the room is clear", async () => {
    const done: HandoverState = { ...HANDOVER, physical: { items: {}, done_at: "2026-11-03T06:00:00Z" } };
    const { calls } = results(NOTHING_FOUND_COMPLETE, { "POST /api/physical/done": done });
    const details = document.getElementById("physical-check")!;
    await userEvent.click(within(details).getByRole("button", { name: "Done" }));
    expect(calls.find((c) => c.url === "/api/physical/done")?.body).toEqual({ done: true });
    expect(await within(details).findByText("Done. Note anything you weren't sure about.")).toBeInTheDocument();
    expect(details).not.toHaveTextContent(/\b(safe|clear|harmless|nothing there)\b/i);
  });
});

describe("Listening only, as its own path", () => {
  it("Results says what a listening-only check covered and what permission adds", async () => {
    results(NOTHING_FOUND);
    const section = screen.getByRole("region", { name: "This was a listening-only check" });
    expect(section).toHaveTextContent(en.results.listening.covered);
    expect(section).toHaveTextContent(en.results.listening.adds);
    await userEvent.click(within(section).getByText("Ask your host for permission"));
    expect(within(section).getByRole("textbox", { name: "Message" })).toHaveValue(en.permission.message);
  });

  it("a check with permission has no such section", () => {
    results();
    expect(screen.queryByRole("region", { name: "This was a listening-only check" })).toBeNull();
  });

  it("Start offers the permission message on No, or I'm not sure, only, ready to copy", async () => {
    withBackend(<Start onStart={vi.fn()} />);
    expect(screen.queryByText("Ask your host for permission")).toBeNull();
    await userEvent.click(screen.getByRole("radio", { name: /^Yes, I have permission/ }));
    expect(screen.queryByText("Ask your host for permission")).toBeNull();
    await userEvent.click(screen.getByRole("radio", { name: /^No, or I'm not sure/ }));
    await userEvent.click(screen.getByText("Ask your host for permission"));
    const box = screen.getByRole("textbox", { name: "Message" });
    expect(box).toHaveValue(en.permission.message);
    expect(en.permission.message).toMatch(/doesn't log in to anything/);
    const write = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText: write }, configurable: true });
    await userEvent.click(screen.getByRole("button", { name: "Copy message" }));
    expect(write).toHaveBeenCalledWith(en.permission.message);
    expect(await screen.findByText(/^Copied\./)).toBeInTheDocument();
  });
});

describe("Where are you staying?", () => {
  it("one optional question; the choice goes with the check", async () => {
    const onStart = vi.fn();
    withBackend(<Start onStart={onStart} />);
    const group = screen.getByRole("group", { name: "Where are you staying? Optional" });
    expect(within(group).getAllByRole("radio").map((r) => r.closest("label")?.textContent)).toEqual([
      "Short stay",
      "Room or flat rental",
      "Hostel",
      "Other",
    ]);
    await userEvent.click(within(group).getByRole("radio", { name: "Short stay" }));
    await userEvent.click(screen.getByRole("radio", { name: /^Yes, I have permission/ }));
    await userEvent.click(screen.getByRole("button", { name: "Start full check" }));
    expect(onStart).toHaveBeenCalledWith(true, "short_stay");
  });
});

describe("Hidden-camera guidance in Help", () => {
  it("the general steps, and that laws differ: no country-specific law", () => {
    withBackend(<Help />);
    const section = screen.getByRole("region", { name: "If you find a hidden camera" });
    for (const line of Object.values(en.help.camera)) expect(section).toHaveTextContent(line);
    expect(section).not.toHaveTextContent(/Singapore|Penal Code|section \d/);
    expect(section).toHaveTextContent("This isn't legal advice.");
  });

  it("matches the camera card's steps word for word", () => {
    // The same steps; Help says who to report to for every stay type in one line.
    const card = RESULT.findings.find((f) => f.rule_id === "R-CAM")!.guidance;
    expect([card[0], card[1]]).toEqual((["touch", "leave"] as const).map((k) => en.help.camera[k]));
    expect(card[2]).toBe("Report it to the platform and the police."); // the demo is a short stay
    expect(en.help.camera.report).toMatch(/the platform, the host or landlord's agent, or the management/);
    // The card's last step is in Help's note, word for word.
    expect(en.help.camera.note).toContain(card[3]);
  });
});

describe("Where is the camera?", () => {
  const cam = () => screen.getByRole("article", { name: /^Likely camera/ });

  it("asks after Find it physically, and saves the answer like the others", async () => {
    const after: HandoverState = {
      ...HANDOVER,
      locations: { [CAM_SUBJECT]: "inside" },
      adjusted: {
        [CAM_FINDING.id]: {
          next_step: "Many platforms don't allow indoor cameras. Report it to the platform and keep your evidence.",
          guidance: CAM_FINDING.guidance,
          draft: "platform",
        },
      },
    };
    const { calls } = results(RESULT, { "POST /api/locations": after });
    expect(cam()).toHaveTextContent("Next step: Find it physically, then say where it is.");
    const where = within(cam()).getByRole("group", { name: "Where is it?" });
    expect(within(where).getAllByRole("radio").map((r) => r.closest("label")?.textContent)).toEqual([
      "Inside the room or unit",
      "Outside or a shared area",
      "Can't find it",
    ]);
    // Before an answer: a message to the host.
    expect(await within(cam()).findByRole("button", { name: "Draft a message to the host" })).toBeInTheDocument();
    await userEvent.click(within(where).getByRole("radio", { name: "Inside the room or unit" }));
    expect(calls.find((c) => c.url === "/api/locations")?.body).toEqual({ subject: CAM_SUBJECT, location: "inside" });
    // Inside a short stay: report it to the platform, and the button matches.
    await waitFor(() => expect(cam()).toHaveTextContent("Report it to the platform and keep your evidence."));
    expect(within(cam()).queryByRole("button", { name: "Draft a message to the host" })).toBeNull();
    await userEvent.click(within(cam()).getByText("Draft a report to the platform"));
    const box = within(cam()).getByRole("textbox", { name: "Message" });
    expect(box).toHaveValue(en.platformReport.message);
    expect(en.platformReport.message).toMatch(/may be a camera/); // never states it is one
  });

  it("names who to report a hidden camera to, for the stay", async () => {
    results();
    await userEvent.click(within(cam()).getByText("Found a hidden camera? See what to do"));
    expect(cam()).toHaveTextContent("Report it to the platform and the police."); // the demo is a short stay
    expect(cam()).not.toHaveTextContent(/Singapore|Penal Code/);
  });
});
