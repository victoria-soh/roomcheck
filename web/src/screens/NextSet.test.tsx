// This set: the logo in the header, "Recheck this" and the two task labels, and "Help
// identify this" on Unknown device and nearby cards.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { DiscoveryResult, HandoverState, Task } from "../api/types";
import { App } from "../App";
import { withBackend, type Call } from "../test/backend";
import { CAM_FINDING, HANDOVER, RESULT } from "../test/fixtures";
import { Handover } from "./Handover";
import { Nearby } from "./Nearby";
import { Results } from "./Results";

const CAM_TASK = HANDOVER.tasks.find((t) => t.rule_id === "R-CAM")!;
const WPS_TASK = HANDOVER.tasks.find((t) => t.rule_id === "R-WPS")!;
const CAM_SUBJECT = CAM_TASK.subject;

function handoverWith(tasks: Task[]): HandoverState {
  return { ...HANDOVER, tasks };
}

describe("The logo", () => {
  it("shows the mark (hidden from screen readers) next to the Saira wordmark", () => {
    withBackend(<App />);
    const header = screen.getByRole("banner");
    const mark = header.querySelector("svg[data-logo='mark']")!;
    expect(mark).toHaveAttribute("aria-hidden", "true");
    expect(mark).toHaveAttribute("width", "28");
    expect(mark.querySelector("path")).toHaveAttribute("fill", "#1BA9A6");
    const word = within(header).getByText("RoomCheck");
    expect(word).toHaveClass("font-wordmark", "font-semibold", "text-wordmark");
    expect(header).toHaveTextContent("Room privacy & device checks");
    // No inline styles anywhere in it: the CSP forbids them.
    expect(header.querySelector("[style]")).toBeNull();
  });
});

describe("Recheck this", () => {
  const wpsDone: Task = { ...WPS_TASK, status: "resolved", recheck_offer: "available" };

  it("is offered once a task is Resolved or Host confirmed, where RoomCheck can see the fix", async () => {
    const { calls } = withBackend(<Handover />, {
      "GET /api/handover": handoverWith([CAM_TASK, wpsDone]),
      "POST /api/tasks/*": handoverWith([
        CAM_TASK,
        {
          ...wpsDone,
          observed: true,
          recheck: { outcome: "fixed", text: "WPS is now off on that router.", checked_at: "2026-11-21T10:00:00Z" },
        },
      ]),
    });
    const wps = await screen.findByRole("article", { name: "Ask for WPS to be turned off on the router" });
    const button = within(wps).getByRole("button", { name: "Recheck this" });
    expect(button).toHaveAccessibleDescription(/Runs only the check that can see this fix/);
    // The camera task is still To do: nothing to recheck yet.
    const cam = screen.getByRole("article", { name: CAM_TASK.title });
    expect(within(cam).queryByRole("button", { name: "Recheck this" })).toBeNull();
    await userEvent.click(button);
    expect(calls.find((c) => c.method === "POST")?.url).toBe(`/api/tasks/${encodeURIComponent(wpsDone.id)}/recheck`);
    expect(await within(wps).findByText("Observed by RoomCheck")).toBeInTheDocument();
    expect(wps).toHaveTextContent(/Rechecked .*2026.*: WPS is now off on that router\./);
  });

  it("appears as soon as the status is set to Resolved", async () => {
    withBackend(<Handover />, {
      "GET /api/handover": handoverWith([{ ...WPS_TASK, status: "asked", recheck_offer: "needs_status" }]),
      "PATCH /api/tasks/*": (call: Call) =>
        handoverWith([{ ...WPS_TASK, status: (call.body as { status: Task["status"] }).status, recheck_offer: "available" }]),
    });
    const wps = await screen.findByRole("article", { name: WPS_TASK.title });
    expect(within(wps).queryByRole("button", { name: "Recheck this" })).toBeNull();
    await userEvent.click(within(wps).getByRole("radio", { name: "Resolved" }));
    expect(await within(wps).findByRole("button", { name: "Recheck this" })).toBeInTheDocument();
  });

  it("keeps Host confirmed and Observed by RoomCheck as two labels", async () => {
    withBackend(<Handover />, {
      "GET /api/handover": handoverWith([{ ...wpsDone, status: "asked", host_confirmed: true, observed: true }]),
    });
    const wps = await screen.findByRole("article", { name: WPS_TASK.title });
    expect(within(wps).getAllByText("Host confirmed").length).toBeGreaterThan(0);
    expect(within(wps).getByText("Observed by RoomCheck")).toBeInTheDocument();
  });

  it("says RoomCheck can't check a fix it can never observe, with no button", async () => {
    const lock: Task = { ...CAM_TASK, id: "R-LOCK|device:x", rule_id: "R-LOCK", title: "Ask who can open the smart lock", status: "asked", host_confirmed: true, recheck_offer: "unobservable" };
    withBackend(<Handover />, { "GET /api/handover": handoverWith([lock]) });
    const card = await screen.findByRole("article", { name: lock.title });
    expect(card).toHaveTextContent("RoomCheck can't check this. It relies on the host's confirmation.");
    expect(within(card).queryByRole("button", { name: "Recheck this" })).toBeNull();
    expect(within(card).queryByText("Observed by RoomCheck")).toBeNull();
  });

  it("shows the backend's reason when a recheck can't run", async () => {
    withBackend(<Handover />, {
      "GET /api/handover": handoverWith([wpsDone]),
      // Not mocked: the backend answers with a plain message (here, the test's 500).
    });
    const wps = await screen.findByRole("article", { name: WPS_TASK.title });
    await userEvent.click(within(wps).getByRole("button", { name: "Recheck this" }));
    expect(await within(wps).findByText("not mocked")).toBeInTheDocument();
  });
});

describe("Help identify this", () => {
  // The camera, as an Unknown device: no maker and no type.
  const UNKNOWN: DiscoveryResult = {
    ...RESULT,
    devices: RESULT.devices.map((d) =>
      d.id === CAM_FINDING.device_ref ? { ...d, vendor: null, fingerprint: null, notes: ["Private address, probably a phone or laptop."] } : d,
    ),
  };

  function showResults(result: DiscoveryResult, routes = {}) {
    return withBackend(
      <Results result={result} onOpenNearby={() => {}} onOpenCompare={() => {}} onOpenHandover={() => {}} />,
      routes,
    );
  }

  it("guides an Unknown device: clues, why it can't be located, name and note, then the answer", async () => {
    const { calls } = showResults(UNKNOWN, {
      "POST /api/names": (call: Call) => {
        const body = call.body as { name: string; note: string };
        return { ...HANDOVER, names: { [CAM_SUBJECT]: body.name }, notes: { [CAM_SUBJECT]: body.note } };
      },
      "POST /api/answers": { ...HANDOVER, answers: { [CAM_SUBJECT]: "landlord" } },
    });
    const card = screen.getByRole("article", { name: /^Likely camera/ });
    const summary = within(card).getByText("Help identify this");
    expect(summary.closest("details")).not.toHaveAttribute("open");
    await userEvent.click(summary);
    const steps = within(card).getAllByRole("heading", { level: 4 }).map((h) => h.textContent);
    expect(steps).toEqual(expect.arrayContaining(["1. Its clues", "2. Locate signal", "3. Name it and add a note (optional)", "4. Do you recognise it now?"]));
    expect(card).toHaveTextContent("Its maker is unknown.");
    expect(card).toHaveTextContent("Calls itself “cam-hallway”");
    expect(card).toHaveTextContent("Private address, probably a phone or laptop.");
    expect(card).toHaveTextContent("Devices on the network can't be located by signal.");
    await userEvent.type(within(card).getByRole("textbox", { name: "Your name for it (optional)" }), "Hallway box");
    await userEvent.type(within(card).getByRole("textbox", { name: "Note (optional)" }), "Above the door");
    await userEvent.click(within(card).getByRole("button", { name: "Save name and note" }));
    expect(calls.find((c) => c.url === "/api/names")?.body).toEqual({ subject: CAM_SUBJECT, name: "Hallway box", note: "Above the door" });
    // Then the existing recognition flow, with the host follow-up.
    await userEvent.click(within(card).getByRole("radio", { name: "Host's" }));
    expect(await within(card).findByRole("group", { name: "Has the host confirmed this?" })).toBeInTheDocument();
  });

  it("isn't shown on an identified device until it's answered Unknown", async () => {
    showResults(RESULT, {
      "POST /api/answers": { ...HANDOVER, answers: { [CAM_SUBJECT]: "unknown" } },
    });
    const card = screen.getByRole("article", { name: /^Likely camera/ });
    expect(within(card).queryByText("Help identify this")).toBeNull();
    await userEvent.click(within(card).getByRole("radio", { name: "Unknown" }));
    expect(await within(card).findByText("Help identify this")).toBeInTheDocument();
  });

  it("on a nearby card, step 2 is Locate signal, under the locator's own rules", async () => {
    const onFind = vi.fn();
    withBackend(<Nearby result={RESULT} onFind={onFind} />);
    const tracker = screen.getByRole("article", { name: "Item tracker nearby" });
    await userEvent.click(within(tracker).getByText("Help identify this"));
    const panel = within(tracker).getByText("Help identify this").closest("details")!;
    expect(panel).toHaveTextContent("Heard nearby as: Tile tracker");
    await userEvent.click(within(panel).getByRole("button", { name: "Locate signal" }));
    await waitFor(() => expect(onFind).toHaveBeenCalled());
  });
});
