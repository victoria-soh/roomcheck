import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { DiscoveryResult, Finding, HandoverState } from "../api/types";
import { withBackend, type Call } from "../test/backend";
import { CAM_FINDING, CAM_SUBJECT, COMPARE_READY, HANDOVER, HANDOVER_CAMERA_MINE, NOTHING_FOUND, NOTHING_FOUND_COMPLETE, RESULT } from "../test/fixtures";
import { Handover } from "./Handover";
import { Results } from "./Results";

const CAM = /^Likely camera/;
const OBSERVED = "A device on this network gave camera-like clues, such as how it answers on the network.";

function show(result: DiscoveryResult = RESULT, routes = {}) {
  const handlers = { onOpenNearby: vi.fn(), onOpenCompare: vi.fn(), onOpenHandover: vi.fn(), onOpenHelp: vi.fn() };
  const backend = withBackend(<Results result={result} {...handlers} />, routes);
  return { ...backend, ...handlers };
}

function question(name: string) {
  return screen.getByRole("region", { name });
}

function banner() {
  return screen.getByRole("region", { name: screen.getAllByRole("heading", { level: 2 })[0]!.textContent! });
}

// A made-up finding: its question comes from its rule, and it has no clues of its own.
const finding = (over: Partial<Finding>): Finding => ({ ...RESULT.findings[0]!, question: undefined, clues: [], ...over });
// RESULT with only the camera's findings: one device, nothing on the network or nearby.
const ONE: DiscoveryResult = { ...RESULT, findings: RESULT.findings.filter((f) => f.device_ref === CAM_FINDING.device_ref && f.scope === "device") };

/** The handover state after an answer, as the backend would send it back. */
function answered(call: Call): HandoverState {
  const body = call.body as { subject: string; answer: "mine" | "landlord" | "unknown"; confirmed: boolean | null };
  const base = body.answer === "mine" ? HANDOVER_CAMERA_MINE : HANDOVER;
  return {
    ...base,
    answers: { [body.subject]: body.answer },
    confirmed: body.answer === "landlord" && body.confirmed != null ? { [body.subject]: body.confirmed } : {},
  };
}

describe("Summary banner", () => {
  it("one finding: a specific headline and the observed sentence, from fixed templates", () => {
    show(ONE);
    const b = banner();
    // One counting rule: things to look at. The camera's Info item isn't counted.
    expect(within(b).getByRole("heading", { level: 2 })).toHaveTextContent("1 thing to look at");
    // One sentence under the headline: the top finding and its strongest clue.
    expect(within(b).getByText("Likely camera: it offers a live video stream, the kind security cameras use.")).toBeInTheDocument();
    expect(b).not.toHaveTextContent(OBSERVED);
    expect(b).not.toHaveTextContent("listed below");
    // Never the AI's words in the banner.
    expect(b).not.toHaveTextContent("may be a camera");
  });

  it("several findings: counted, with the top one described", () => {
    const result: DiscoveryResult = {
      ...RESULT,
      devices: [...RESULT.devices, { ...RESULT.devices[0]!, id: "dev-2", hostnames: ["lock-door"], vendor: "Example Locks" }],
      findings: [
        ...RESULT.findings,
        finding({ id: "R-LOCK:dev-2", rule_id: "R-LOCK", severity: "Medium", device_ref: "dev-2", title: "Smart lock or doorbell", observed: "A device on this network looks like a smart lock or video doorbell.", subject: "device:mac:2" }),
        finding({ id: "R-ARP:network", rule_id: "R-ARP", scope: "network", severity: "High", device_ref: null, title: "More than one device answers for the router", observed: "More than one device answered for the router's address during the check.", subject: "network:R-ARP" }),
      ],
    };
    show(result);
    const b = banner();
    // One counting rule across every question: cards with a High, Medium or Low finding.
    expect(within(b).getByRole("heading", { level: 2 })).toHaveTextContent("7 things to look at");
    expect(question("Is anything watching?")).toHaveTextContent("2 things to look at");
    expect(question("Can someone else control things here?")).toHaveTextContent("1 thing to look at");
    expect(question("Can you trust this Wi-Fi?")).toHaveTextContent("4 things to look at");
    // The surest High finding first: the camera (Likely) before the router (Likely, network).
    expect(b).toHaveTextContent("Likely camera: it offers a live video stream, the kind security cameras use.");
    expect(b).not.toHaveTextContent("more are listed below"); // the tiles below count the rest
  });

  it("nothing found, everything ran: no claim beyond the checks that ran", () => {
    show(NOTHING_FOUND_COMPLETE);
    const b = banner();
    expect(within(b).getByRole("heading", { level: 2 })).toHaveTextContent("Not detected by the checks that ran");
    expect(within(b).queryByRole("button", { name: "Review finding" })).toBeNull();
    expect(b).not.toHaveTextContent(/checks ran ·/);
    expect(document.body).not.toHaveTextContent(/\bsafe\b/i);
  });

  it("nearby findings sit under their question on Results, with a way to Nearby", async () => {
    const { onOpenNearby } = show({ ...RESULT, findings: RESULT.findings.filter((f) => f.shown_on === "nearby") });
    const b = banner();
    // The tracker and the hidden network; the open networks are Info, not counted.
    expect(within(b).getByRole("heading", { level: 2 })).toHaveTextContent("2 things to look at");
    const tracker = within(question("Is anything watching?")).getByRole("article", { name: /^Item tracker nearby/ });
    await userEvent.click(within(tracker).getByRole("button", { name: "Find it on Nearby" }));
    expect(onOpenNearby).toHaveBeenCalled();
  });

  it("only low-priority findings: no urgent headline, and still a way to review them", () => {
    show({ ...RESULT, findings: RESULT.findings.filter((f) => f.id === "R-UPNP:network") });
    const b = banner();
    // Low counts as a thing to look at; only Info doesn't.
    expect(within(b).getByRole("heading", { level: 2 })).toHaveTextContent("1 thing to look at");
    // Named from the top finding's rule: the UPnP finding here.
    expect(within(b).getByRole("button", { name: "Review router's UPnP setting" })).toBeInTheDocument();
  });

  it("Review finding jumps to, focuses and briefly highlights the top finding's card", async () => {
    show();
    await userEvent.click(within(banner()).getByRole("button", { name: "Review camera-like device" }));
    const cardEl = screen.getByRole("article", { name: CAM });
    await waitFor(() => expect(cardEl).toHaveFocus());
    expect(cardEl).toHaveClass("review-highlight");
    await waitFor(() => expect(cardEl).not.toHaveClass("review-highlight"), { timeout: 3000 });
    expect(cardEl).toHaveFocus(); // the highlight goes; focus stays
  });

  it("has no new-check button of its own: the header's New check is the only way", () => {
    show();
    expect(screen.queryByRole("button", { name: /new check/i })).toBeNull();
  });

  it("offers Save as my move-in scan under What's changed since move-in?", async () => {
    show();
    const changes = question("What's changed since move-in?");
    const baseline = await within(changes).findByRole("region", { name: "Move-in scan" });
    // The card says what to do: no second status line repeating it.
    expect(within(changes).queryByText("Save a move-in scan to see changes later.")).toBeNull();
    expect(baseline).toHaveTextContent(
      "Save this check so RoomCheck can show you anything new that appears later." +
        "Save as my move-in scan" +
        "Saved only on this laptop, encrypted for your Windows account.",
    );
    // Outlined: the summary's Review button is the page's only filled one.
    expect(within(baseline).getByRole("button", { name: "Save as my move-in scan" }).className).toContain("bg-surface");
  });

  it("with a move-in scan, summarises Compare and links to it", async () => {
    const { onOpenCompare } = show(RESULT, { "GET /api/compare": COMPARE_READY });
    const changes = question("What's changed since move-in?");
    expect(await within(changes).findByText("3 differences since your move-in scan")).toBeInTheDocument();
    expect(changes).toHaveTextContent("These checks ran differently, so some differences may come from that.");
    await userEvent.click(within(changes).getByRole("button", { name: "Open Compare" }));
    expect(onOpenCompare).toHaveBeenCalled();
  });

  it("says once that AI explains and fixed rules set every priority, linking to how", () => {
    show();
    expect(screen.getAllByText(/AI explains findings in plain words\./)).toHaveLength(1);
    expect(screen.getAllByRole("button", { name: "Fixed rules set every priority." })).toHaveLength(1);
    expect(screen.queryByText(/The risk level comes from fixed rules/)).toBeNull();
  });
});

describe("Quiet results", () => {
  it("say what was heard, by device type only", () => {
    show(NOTHING_FOUND_COMPLETE);
    const b = banner();
    expect(b).toHaveTextContent(
      "Heard 9 devices: a router, 3 phones or computers, a TV, a smart speaker and 3 unidentified devices.",
    );
    // No names, makers or addresses; an Unclear guess is never named as its type.
    expect(b).not.toHaveTextContent(/192\.0\.2|Example|camera/i);
  });

  it("never put a tick next to Not detected, or on a page with nothing found", async () => {
    show(NOTHING_FOUND_COMPLETE);
    expect(banner().querySelector(".lucide-check")).toBeNull();
    const limits = document.getElementById("coverage-limits")!;
    // Checks that ran and flagged nothing say so in their own words, with the neutral mark.
    const rows = within(limits).getAllByRole("row").filter((r) => /No weak encryption found|No copies of your Wi-Fi name|Address lookups looked normal/.test(r.textContent ?? ""));
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) {
      expect(row.querySelector(".lucide-check")).toBeNull();
      expect(row.querySelector(".lucide-circle-dot")).not.toBeNull();
    }
  });

  it("no heard line when there are findings to review", () => {
    show();
    expect(banner()).not.toHaveTextContent(/^Heard \d+ device/);
    expect(document.body).not.toHaveTextContent(/Heard \d+ devices?:/);
  });
});

describe("Scan coverage", () => {
  it("a partial check says so prominently and links to Coverage and limits, at the bottom", async () => {
    show();
    const b = banner();
    // A compact coverage line under the headline, counting checks as the list does.
    expect(b).toHaveTextContent(/17 of 18 checks ran\s*·\s*See what didn't/);
    const details = document.getElementById("coverage-limits") as HTMLDetailsElement;
    expect(details.open).toBe(false); // collapsed while there are findings to read
    await userEvent.click(within(b).getByRole("button", { name: "See what didn't" }));
    expect(details.open).toBe(true);
    expect(details.querySelector("summary")).toHaveFocus();
    expect(within(details).getByRole("heading", { level: 2, name: "Coverage and limits" })).toBeInTheDocument();
    const rows = within(within(details).getByRole("table")).getAllByRole("row").slice(1).map((r) => r.textContent);
    // One row per check: Checked, Not detected, or Not checked with a short reason. A flagged
    // check doesn't point at its card ("See the card above" is gone). Plus the devices total,
    // which isn't a check, so "17 of 18 checks ran" never counts it.
    expect(rows).toHaveLength(19);
    expect(rows).toEqual(
      expect.arrayContaining([
        "Listening for devicesHeard 3 devices",
        `Devices heard in all${RESULT.devices.length} devices, each counted once however many checks heard it`,
        "Checking how your Wi-Fi connection is encryptedNo weak encryption found",
        "Checking for a second device handing out network addressesNot checked: the second-address-server check took too long and was stopped",
        "Checking whether the router advertises UPnP controlsChecked",
        "Looking up known issues for identified modelsChecked",
        "Looking at nearby Wi-FiHeard 6 nearby networks",
        "Checking whether your Wi-Fi router advertises WPSChecked",
      ]),
    );
    expect(details).not.toHaveTextContent("See the card above");
    expect(within(details).getByRole("heading", { level: 3, name: "What this scan can't see" })).toBeInTheDocument();
    expect(details).toHaveTextContent("17 of 18 checks ran");
    // The last thing on the page.
    expect(document.querySelector("div.space-y-4 > :last-child")).toBe(details);
  });

  it("everything checked: a one-line note, and the table stays closed until asked", async () => {
    show(NOTHING_FOUND_COMPLETE);
    const b = banner();
    expect(b).toHaveTextContent(/All \d+ checks ran\s*·\s*See coverage/);
    // Nothing to read above: Coverage and limits is open from the start.
    const details = document.getElementById("coverage-limits") as HTMLDetailsElement;
    expect(details.open).toBe(true);
    await userEvent.click(within(b).getByRole("button", { name: "See coverage" }));
    expect(details.querySelector("summary")).toHaveFocus();
    // And there are no priority chips to show when every count is 0.
    expect(screen.queryByRole("button", { name: /^All findings/ })).toBeNull();
  });

  it("nothing found on a partial check never reads as a full all-clear", () => {
    show(NOTHING_FOUND);
    const b = banner();
    expect(within(b).getByRole("heading", { level: 2 })).toHaveTextContent("Not detected by the checks that ran");
    expect(b).toHaveTextContent(/\d+ of \d+ checks ran/);
  });
});

describe("The renter's questions", () => {
  it("four questions in order, each with a status line and its cards; no priority chips", () => {
    show();
    const ids = [...document.querySelectorAll("section[aria-labelledby^='question-']")].map((el) => el.getAttribute("aria-labelledby"));
    expect(ids).toEqual(["question-watching", "question-control", "question-wifi", "question-changes"]);
    const watching = question("Is anything watching?");
    expect(watching).toHaveTextContent("2 things to look at");
    expect(within(watching).getAllByRole("article").map((a) => a.getAttribute("aria-labelledby") && a.querySelector("h3")?.textContent)).toEqual([
      "Likely camera",
      "Item tracker nearby",
    ]);
    // Nothing to look at here; the lookup that didn't run is named.
    const control = question("Can someone else control things here?");
    expect(control).toHaveTextContent("Not detected by the checks that ran");
    expect(control).not.toHaveTextContent("Not checked"); // every check it depends on ran
    expect(within(control).queryAllByRole("article")).toHaveLength(0);
    const wifi = question("Can you trust this Wi-Fi?");
    expect(wifi).toHaveTextContent("3 things to look at");
    expect(wifi).toHaveTextContent("Not checked: the second-address-server check took too long and was stopped");
    expect(within(wifi).getByRole("article", { name: "Router advertises WPS" })).toBeInTheDocument();
    // The chips and the Nearby chip are gone: priority is a label on each card.
    expect(screen.queryByRole("region", { name: "Findings by priority" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Nearby signals/ })).toBeNull();
    expect(screen.queryByText("Choose a priority to filter.")).toBeNull();
  });

  it("Info is shown inside its device's card as Also found, and never counted", () => {
    show();
    expect(within(banner()).getByRole("heading", { level: 2 })).toHaveTextContent("5 things to look at");
    const cam = screen.getByRole("article", { name: CAM });
    expect(within(cam).getByRole("heading", { level: 5, name: "Also found on this device" }).nextElementSibling).toHaveTextContent(
      "Known issues reported for this model",
    );
  });

  it("an Info item with no card is listed at the end of its question, not counted", () => {
    show({ ...RESULT, findings: RESULT.findings.filter((f) => f.rule_id === "R-CVE") });
    const b = banner();
    expect(within(b).getByRole("heading", { level: 2 })).toHaveTextContent("Not detected by the checks that ran");
    expect(b).toHaveTextContent("1 item for information is listed below.");
    const control = question("Can someone else control things here?");
    expect(control).toHaveTextContent("1 item for information only");
    expect(within(control).getByRole("group", { name: "Also found" })).toHaveTextContent("Known issues reported for this model");
  });

  it("a question none of whose checks ran says Not checked, with the reason", () => {
    const wifiChecks = new Set(["wifi_encryption", "dns", "arp", "dhcp", "upnp", "nearby_wifi", "lookalike", "wps"]);
    show({
      ...NOTHING_FOUND_COMPLETE,
      checks: NOTHING_FOUND_COMPLETE.checks.map((c) =>
        wifiChecks.has(c.name) ? { ...c, status: "skipped" as const, reason: "Not checked: you chose not to run the nearby check." } : c,
      ),
    });
    expect(question("Can you trust this Wi-Fi?")).toHaveTextContent("Not checked: you chose not to run the nearby check");
    expect(question("Is anything watching?")).toHaveTextContent("Not detected by the checks that ran");
  });

  it("status lines use a neutral mark, never a tick", () => {
    show(NOTHING_FOUND_COMPLETE);
    for (const id of ["watching", "control", "wifi"]) {
      const head = document.getElementById(`question-${id}`)!.parentElement!;
      expect(head.querySelector(".lucide-check")).toBeNull();
      expect(head.querySelector(".lucide-circle-dot")).not.toBeNull();
    }
  });

  it("says once, near the top, that device types are unconfirmed; no card repeats it", () => {
    show();
    // One line under the summary: how findings are explained, and that types are unconfirmed.
    expect(screen.getAllByText(/Device types are unconfirmed: clues, not proof\./)).toHaveLength(1);
    expect(screen.getByText(/^AI explains findings in plain words\. Device types are unconfirmed: clues, not proof\./)).toBeInTheDocument();
    for (const card of screen.getAllByRole("article")) {
      expect(card).not.toHaveTextContent(/not proof|clues agree/i);
    }
  });
});

describe("All discovered devices", () => {
  it("lists every device, including ones with no findings, collapsed, and never says safe", async () => {
    const quiet = { ...RESULT.devices[0]!, id: "dev-quiet", hostnames: ["speaker-lounge"], vendor: "Example Audio", fingerprint: { type: "speaker", label: "Speaker", band: "Possible" as const } };
    show({ ...RESULT, devices: [...RESULT.devices, quiet] });
    const summary = screen.getByText(`View all discovered devices (${RESULT.devices.length + 1})`);
    expect(summary.closest("details")).not.toHaveAttribute("open");
    await userEvent.click(summary);
    const rows = within(summary.closest("details")!).getAllByRole("row").slice(1).map((r) => r.textContent);
    expect(rows).toEqual(
      expect.arrayContaining([
        "cam-hallwayCameraLikelyExample Camera Co.2 findings",
        "speaker-loungeSpeakerPossibleExample AudioNone from these checks",
      ]),
    );
    expect(rows).toHaveLength(RESULT.devices.length + 1);
    expect(summary.closest("details")).not.toHaveTextContent(/\bsafe\b/i);
  });
});

describe("Device cards", () => {
  it("one card per device and question; WPS and UPnP sit under the Wi-Fi question", () => {
    show();
    const cam = within(question("Is anything watching?")).getByRole("article", { name: CAM });
    expect(cam).toHaveAccessibleName("Likely camera");
    expect(cam).toHaveTextContent("Priority: Look at this first");
    // One scale on the card: the urgency word. Identification confidence is under Evidence and details.
    expect(cam).toHaveTextContent("cam-hallway · Made by Example Camera Co.");
    expect(within(cam).getByText("Evidence and details").closest("details")).toHaveTextContent("Identification confidence: Likely · Priority: Look at this first");
    expect(within(cam).getAllByRole("group", { name: "Do you recognise this device?" })).toHaveLength(1);
    const wifi = question("Can you trust this Wi-Fi?");
    expect(within(wifi).getByRole("article", { name: "Router advertises WPS" })).toBeInTheDocument();
    const upnp = within(wifi).getByRole("article", { name: /^Router offers UPnP controls/ });
    expect(within(upnp).queryByRole("group", { name: "Do you recognise this device?" })).toBeNull();
  });

  it("is short by default: identity and priority, what was seen, one next step", () => {
    show();
    const cam = screen.getByRole("article", { name: CAM });
    expect(cam).toHaveTextContent("Priority: Look at this first");
    expect(cam).toHaveTextContent("Identification confidence: Likely");
    // What we observed: the specific clues, one plain sentence each.
    const observed = within(cam).getByRole("group", { name: "What we observed" });
    expect([...observed.querySelector("ul")!.children].map((li) => li.textContent)).toEqual([
      "It answers camera discovery requests (ONVIF).",
      "It offers a live video stream, the kind security cameras use.",
      "It has a port open that camera recorders often use (port 8000).",
      "It calls itself “cam-hallway”.",
    ]);
    expect(cam).toHaveTextContent("Next step: Find it physically, then say where it is.");
    const details = within(cam).getByText("Evidence and details").closest("details")!;
    expect(details).not.toHaveAttribute("open");
    expect(within(cam).getByText(/^Runs a video-streaming server/)).not.toBeVisible();
  });

  it("puts the explanation, why it matters, evidence and a small AI label under Evidence and details", async () => {
    show();
    const cam = screen.getByRole("article", { name: CAM });
    await userEvent.click(within(cam).getByText("Evidence and details"));
    expect(within(cam).getByText(/^Runs a video-streaming server/)).toBeVisible();
    expect(cam).toHaveTextContent("A device on this network may be a camera.");
    expect(cam).toHaveTextContent("Why it matters: A camera could record you.");
    expect(within(cam).getAllByText("AI").length).toBeGreaterThan(0);
    expect(within(cam).getAllByText("(Written by AI from the scan results)").length).toBeGreaterThan(0);
    // The second finding's details are there too, explained by AI as well (the demo has AI on).
    expect(cam).toHaveTextContent("Problems have been reported publicly for this camera's model.");
  });

  it("keeps one short camera line that opens the physical-device guidance", async () => {
    show();
    const cam = screen.getByRole("article", { name: CAM });
    const line = within(cam).getByText("Found a hidden camera? See what to do");
    expect(within(cam).getByText(/Don't touch or unplug it/)).not.toBeVisible();
    await userEvent.click(line);
    expect(within(cam).getByText(/Don't touch or unplug it/)).toBeVisible();
  });

  it("offers a message to the host and the handover task", async () => {
    const { onOpenHandover } = show();
    const cam = screen.getByRole("article", { name: CAM });
    await userEvent.click(await within(cam).findByRole("button", { name: "Draft a message to the host" }));
    expect(onOpenHandover).toHaveBeenCalledWith("message");
    await userEvent.click(within(cam).getByRole("button", { name: "View in handover" }));
    expect(onOpenHandover).toHaveBeenCalledWith({ task: HANDOVER.tasks[0]!.id });
  });
});

describe("Recognition", () => {
  it("Mine, Host's or Unknown, with nothing chosen", async () => {
    show();
    const cam = screen.getByRole("article", { name: CAM });
    const group = within(cam).getByRole("group", { name: "Do you recognise this device?" });
    const radios = within(group).getAllByRole("radio");
    expect(radios.map((r) => r.closest("label")?.textContent)).toEqual(["Mine", "Host's", "Unknown"]);
    expect(radios.every((r) => !(r as HTMLInputElement).checked)).toBe(true);
    expect(group).toHaveAccessibleDescription("Your answer changes the next steps, not the finding.");
    expect(within(group).queryByRole("group", { name: "Has the host confirmed this?" })).toBeNull();
  });

  it("Host's asks whether the host confirmed it, and the card's second line says so", async () => {
    const { calls } = show(RESULT, { "POST /api/answers": answered });
    const cam = screen.getByRole("article", { name: CAM });
    await userEvent.click(within(cam).getByRole("radio", { name: "Host's" }));
    const follow = await within(cam).findByRole("group", { name: "Has the host confirmed this?" });
    expect(cam).toHaveTextContent("Host's, not confirmed yet");
    await userEvent.click(within(follow).getByRole("radio", { name: "Yes" }));
    await waitFor(() => expect(cam).toHaveTextContent("cam-hallway · Made by Example Camera Co. · Host's, confirmed"));
    const posts = calls.filter((c) => c.method === "POST" && c.url === "/api/answers").map((c) => c.body);
    expect(posts).toEqual([
      { subject: CAM_SUBJECT, answer: "landlord", confirmed: null },
      { subject: CAM_SUBJECT, answer: "landlord", confirmed: true },
    ]);
  });

  it("Mine changes the second line and the next step, never removes the finding", async () => {
    show(RESULT, { "POST /api/answers": answered });
    const cam = screen.getByRole("article", { name: CAM });
    await userEvent.click(within(cam).getByRole("radio", { name: "Mine" }));
    await waitFor(() => expect(cam).toHaveTextContent("Identified by you as yours"));
    const still = screen.getByRole("article", { name: CAM }); // same place, same finding
    expect(still).toHaveTextContent("Priority: Look at this first");
    expect(still).toHaveTextContent("Next step: You said this is yours");
    expect(within(still).queryByText("Found a hidden camera? See what to do")).toBeNull();
    expect(question("Is anything watching?")).toContainElement(still);
  });

  it("an optional short name is saved and shown in the card's title", async () => {
    const { calls } = show(RESULT, {
      "POST /api/answers": answered,
      "POST /api/names": (call: Call) => ({ ...HANDOVER, names: { [CAM_SUBJECT]: (call.body as { name: string }).name } }),
    });
    const cam = screen.getByRole("article", { name: CAM });
    // The name box appears once it's known whose it is.
    expect(within(cam).queryByRole("textbox", { name: "Your name for it (optional)" })).toBeNull();
    await userEvent.click(within(cam).getByRole("radio", { name: "Host's" }));
    const box = await within(cam).findByRole("textbox", { name: "Your name for it (optional)" });
    expect(box).toHaveAttribute("maxLength", "40");
    await userEvent.type(box, "  Hallway camera ");
    await userEvent.click(within(cam).getByRole("button", { name: "Save name" }));
    expect(calls.find((c) => c.url === "/api/names")?.body).toEqual({ subject: CAM_SUBJECT, name: "Hallway camera" });
    await waitFor(() => expect(screen.getByRole("article", { name: "Likely camera" })).toHaveTextContent("Hallway cameraWhat we observed"));
  });

  it("a name is shown as plain text, never as markup", async () => {
    show(RESULT, { "GET /api/handover": { ...HANDOVER, names: { [CAM_SUBJECT]: "<img src=x onerror=alert(1)>" } } });
    const cam = await screen.findByRole("article", { name: "Likely camera" });
    await waitFor(() => expect(cam).toHaveTextContent("<img src=x onerror=alert(1)>What we observed"));
    expect(cam.querySelector("img")).toBeNull();
  });
});

describe("Handover links", () => {
  it("View in handover lands on that task", async () => {
    withBackend(<Handover focus={{ task: HANDOVER.tasks[0]!.id }} />);
    const task = await screen.findByRole("article", { name: "Ask about the device that looks like a camera" });
    await waitFor(() => expect(task).toHaveFocus());
  });

  it("Draft a message lands on the message, with this item's question in it", async () => {
    withBackend(<Handover focus="message" />);
    const draft = await screen.findByText("Draft message to host");
    await waitFor(() => expect(draft.closest("summary")).toHaveFocus());
    expect(draft.closest("details")).toHaveAttribute("open");
    const box = screen.getByRole("textbox", { name: "Message" }) as HTMLTextAreaElement;
    expect(box.value).toContain("looks like a camera");
  });

  it("shows the device's name on its task", async () => {
    withBackend(<Handover />, { "GET /api/handover": { ...HANDOVER, names: { [CAM_SUBJECT]: "Hallway camera" } } });
    const task = await screen.findByRole("article", { name: "Ask about the device that looks like a camera" });
    expect(task).toHaveTextContent("Your name for it: Hallway camera");
  });
});
