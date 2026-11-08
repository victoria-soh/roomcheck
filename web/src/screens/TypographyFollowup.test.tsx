// Follow-up to the typography pass: the tracker card's buttons, R-UPNP's next step, timeout
// reasons that name the check, and device counts that add up on a quiet page.
import { screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { DiscoveryResult } from "../api/types";
import { withBackend } from "../test/backend";
import { NOTHING_FOUND, NOTHING_FOUND_COMPLETE, RESULT } from "../test/fixtures";
import { Results } from "./Results";

function results(result: DiscoveryResult = RESULT) {
  const handlers = { onOpenNearby: vi.fn(), onOpenCompare: vi.fn(), onOpenHandover: vi.fn(), onOpenHelp: vi.fn() };
  return { ...withBackend(<Results result={result} {...handlers} />), ...handlers };
}

describe("Card buttons", () => {
  it("the tracker card's two buttons share one row, like other cards (stacked only on phones)", async () => {
    results();
    const tracker = screen.getByRole("article", { name: /^Item tracker nearby/ });
    const nearby = within(tracker).getByRole("button", { name: "Find it on Nearby" });
    const handover = await within(tracker).findByRole("button", { name: "View in handover" });
    const row = nearby.parentElement!;
    expect(handover.parentElement).toBe(row);
    expect(row).toHaveClass("flex", "flex-col", "sm:flex-row");
  });

  it("a camera card's buttons share that row too", async () => {
    results();
    const cam = screen.getByRole("article", { name: /^Likely camera/ });
    const find = within(cam).getByRole("button", { name: "Find it physically" });
    expect((await within(cam).findByRole("button", { name: "View in handover" })).parentElement).toBe(find.parentElement);
  });
});

describe("Wording", () => {
  it("R-UPNP's next step is the one ask", () => {
    results();
    const upnp = screen.getByRole("article", { name: /^Router offers UPnP controls/ });
    expect(upnp).toHaveTextContent("Next step: Ask the host whether UPnP can be turned off.");
    expect(upnp).not.toHaveTextContent("without asking");
  });

  it("a timed-out check is named, lowercase after the colon", () => {
    results();
    const limits = document.getElementById("coverage-limits")!;
    expect(limits).toHaveTextContent("Not checked: the second-address-server check took too long and was stopped");
    expect(limits).not.toHaveTextContent("it took too long");
  });
});

describe("Device counts add up", () => {
  it.each([
    ["with permission", NOTHING_FOUND_COMPLETE],
    ["listening only", NOTHING_FOUND],
  ])("on a quiet page (%s): one total row, the summary's number, after the device checks", (_, result) => {
    results(result);
    const n = result.devices.length;
    expect(document.body).toHaveTextContent(`Heard ${n} devices:`);
    const total = screen.getByTestId("devices-total");
    expect(total).toHaveTextContent(`Devices heard in all${n} devices, each counted once however many checks heard it`);
    expect(total.previousElementSibling).toHaveTextContent(/^Sending a camera discovery request \(ONVIF\)/);
    // It isn't a check: the coverage line still counts checks only.
    const limits = document.getElementById("coverage-limits")!;
    expect(limits.querySelector("summary")).toHaveTextContent(new RegExp(`${result.checks.filter((c) => c.status === "ran").length}`));
  });
});
