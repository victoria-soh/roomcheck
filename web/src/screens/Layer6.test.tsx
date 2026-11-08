// Layer 6 component tests: "Do you recognise this device?", Handover, the move-in card, Compare.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { withBackend } from "../test/backend";
import {
  BASELINE_NONE,
  BASELINE_SAVED,
  BASELINE_UNREADABLE,
  COMPARE_READY,
  HANDOVER,
  RESULT,
} from "../test/fixtures";
import { Compare } from "./Compare";
import { Handover } from "./Handover";
import { Help } from "./Help";
import { Results } from "./Results";

function renderResults(routes = {}) {
  return withBackend(
    <Results result={RESULT} onOpenNearby={() => {}} onOpenCompare={() => {}} onOpenHandover={() => {}} />,
    routes,
  );
}

// Recognition on the Results cards is tested in Results.test.tsx.

describe("Handover screen", () => {
  it("lists a task per High or Medium finding with who and what to ask", async () => {
    // The maker's help link: none of the demo's made-up makers has one, so this task gets one.
    const support = { name: "Example Routers support", url: "https://support.example.com/routers" };
    const withSupport = { ...HANDOVER, tasks: HANDOVER.tasks.map((t) => (t.rule_id === "R-WPS" ? { ...t, support } : t)) };
    withBackend(<Handover />, { "GET /api/handover": withSupport });
    expect(await screen.findByRole("heading", { level: 2, name: "Tasks (4)" })).toBeInTheDocument();
    const cam = screen.getByRole("article", { name: "Ask about the device that looks like a camera" });
    expect(cam).toHaveTextContent("Your host");
    expect(cam).toHaveTextContent("who can view it");
    expect(within(cam).getByRole("radio", { name: "To do" })).toBeChecked();
    expect(cam).toHaveTextContent("Not changed yet");
    const wps = screen.getByRole("article", { name: "Ask for WPS to be turned off on the router" });
    // Secondary, and naming the topic it's about.
    const link = within(wps).getByRole("link", { name: "Maker's help on turning off WPS: Example Routers support" });
    expect(link).toHaveAttribute("href", "https://support.example.com/routers");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(wps).toHaveTextContent(/^.*Changed .*2026/);
    expect(screen.getByText(/saved on this laptop as you go, encrypted for your Windows account/)).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(/until you close RoomCheck/);
  });

  it("changes a status, records Host confirmed as evidence, and autosaves notes", async () => {
    const asked = {
      ...HANDOVER,
      tasks: HANDOVER.tasks.map((t, i) => (i === 0 ? { ...t, status: "asked" as const, changed_at: "2026-11-05T10:00:00Z" } : t)),
    };
    const { calls } = withBackend(<Handover />, { "PATCH /api/tasks/*": asked });
    const cam = await screen.findByRole("article", { name: "Ask about the device that looks like a camera" });
    expect(within(cam).getAllByRole("radio").map((r) => r.closest("label")?.textContent)).toEqual([
      "To do",
      "Asked",
      "Resolved",
    ]);
    await userEvent.click(within(cam).getByRole("radio", { name: "Asked" }));
    await waitFor(() => expect(within(cam).getByRole("radio", { name: "Asked" })).toBeChecked());
    const patch = calls.find((c) => c.method === "PATCH");
    expect(patch?.url).toBe(`/api/tasks/${encodeURIComponent(HANDOVER.tasks[0]!.id)}`);
    expect(patch?.body).toEqual({ status: "asked" });
    await userEvent.click(within(cam).getByRole("checkbox", { name: "Host confirmed" }));
    await waitFor(() => expect(calls.filter((c) => c.method === "PATCH")[1]?.body).toEqual({ host_confirmed: true }));
    // Notes save themselves once typing stops: no Save button.
    expect(within(cam).queryByRole("button", { name: "Save notes" })).toBeNull();
    await userEvent.type(within(cam).getByRole("textbox", { name: "Notes" }), "Asked by email");
    expect(await within(cam).findByText("Saved on this laptop", {}, { timeout: 3000 })).toBeInTheDocument();
    const notes = calls.filter((c) => c.method === "PATCH" && (c.body as { notes?: string }).notes !== undefined);
    expect(notes).toEqual([expect.objectContaining({ body: { notes: "Asked by email" } })]); // once, after typing
  });

  it("says when notes weren't saved, and why", async () => {
    withBackend(<Handover />, {
      "PATCH /api/tasks/*": { ...HANDOVER, storage: "not_saved", storage_reason: "RoomCheck couldn't write to its folder in your user profile." },
    });
    const cam = await screen.findByRole("article", { name: "Ask about the device that looks like a camera" });
    await userEvent.type(within(cam).getByRole("textbox", { name: "Notes" }), "x");
    expect(
      await within(cam).findByText("Not saved: RoomCheck couldn't write to its folder in your user profile.", {}, { timeout: 3000 }),
    ).toBeInTheDocument();
  });

  it("bundles the open tasks into a message you can edit and copy; it's never sent", async () => {
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const { calls } = withBackend(<Handover />);
    const box = await screen.findByRole("textbox", { name: "Message" });
    expect(box).toHaveValue(HANDOVER.message!.text);
    expect(box).toHaveAccessibleDescription(/RoomCheck never sends anything/);
    await userEvent.clear(box);
    await userEvent.type(box, "Hello, could you tell me what the camera is?");
    await userEvent.click(screen.getByRole("button", { name: "Copy message" }));
    expect(writeText).toHaveBeenCalledWith("Hello, could you tell me what the camera is?");
    expect(screen.getByText("Copied. Paste it into your email or chat.")).toBeInTheDocument();
    expect(calls.map((c) => c.url)).toEqual(["/api/handover"]); // nothing sent anywhere
  });

  it("explains when copying isn't allowed", async () => {
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: vi.fn(async () => Promise.reject(new Error("denied"))) },
      configurable: true,
    });
    withBackend(<Handover />);
    await userEvent.click(await screen.findByRole("button", { name: "Copy message" }));
    expect(await screen.findByText("Couldn't copy. Select the text and copy it yourself.")).toBeInTheDocument();
  });

  it("says when there are no tasks", async () => {
    withBackend(<Handover />, { "GET /api/handover": { ...HANDOVER, tasks: [], message: null } });
    expect(await screen.findByText(/There are no tasks/)).toBeInTheDocument();
  });
});

describe("Move-in scan", () => {
  it("saves this check as the move-in scan", async () => {
    const { calls } = renderResults({ "POST /api/baseline": BASELINE_SAVED });
    const card = await screen.findByRole("region", { name: "Move-in scan" });
    expect(card).toHaveTextContent("encrypted for your Windows account");
    await userEvent.click(within(card).getByRole("button", { name: "Save as my move-in scan" }));
    expect(await within(card).findByText(/^Your move-in scan from .*2026.* is saved\.$/)).toBeInTheDocument();
    expect(calls.some((c) => c.method === "POST" && c.url === "/api/baseline")).toBe(true);
  });

  it("shows the DPAPI failure message and offers a new baseline", async () => {
    renderResults({ "GET /api/baseline": BASELINE_UNREADABLE });
    const card = await screen.findByRole("region", { name: "Move-in scan" });
    expect(
      await within(card).findByText("This saved scan belongs to another account or install. Start a new move-in scan."),
    ).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Start a new move-in scan" })).toBeInTheDocument();
  });
});

describe("Compare screen", () => {
  it("shows the baseline date, then New, Changed and Not seen this time", async () => {
    withBackend(<Compare result={RESULT} />, { "GET /api/compare": COMPARE_READY });
    const versus = await screen.findByRole("region", { name: "Move-in scan vs this check" });
    // When and how each check ran.
    expect(versus).toHaveTextContent(/Move-in scan.*2026.*With permission/);
    expect(versus).toHaveTextContent(/This check.*2026.*Listening only/);
    const added = screen.getByRole("region", { name: "New (1)" });
    expect(within(added).getByRole("article", { name: "Camera" })).toHaveTextContent(
      "Camera-like device that appeared since your move-in scan",
    );
    const changed = screen.getByRole("region", { name: "Changed (1)" });
    const plug = within(changed).getByRole("article", { name: "Smart plug or switch" });
    expect(plug).not.toHaveTextContent("Possibly the same device"); // matched by its address
    expect(plug).toHaveTextContent("New finding: Cloud-linked smart device");
    // A listening-only check never reports a port difference.
    expect(document.body).not.toHaveTextContent(/open port|No longer open/i);
    const notSeen = screen.getByRole("region", { name: "Not seen this time (1)" });
    expect(notSeen).toHaveTextContent("Smart speaker");
    expect(notSeen).toHaveTextContent("Devices can be asleep or out of range");
    expect(document.body).not.toHaveTextContent(/\bGone\b/);
    expect(screen.getByText("3 items are the same as at move-in.")).toBeInTheDocument();
    expect(screen.getByText(/so it's possibly the same device\./)).toBeInTheDocument();
    expect(screen.getByText(/1 device couldn't be compared/)).toBeInTheDocument();
  });

  it("with nothing saved, one card offers the latest check as the starting point", async () => {
    const { calls } = withBackend(<Compare result={RESULT} />, { "POST /api/baseline": BASELINE_SAVED });
    const start = await screen.findByRole("region", { name: "Save a starting point to compare future checks" });
    expect(screen.getAllByRole("region", { name: /starting point|move-in scan/i })).toHaveLength(1);
    expect(start).toHaveTextContent("Save this check so RoomCheck can show you anything new that appears later.");
    expect(start).toHaveTextContent(/Latest check: Run .*2026/);
    expect(start).toHaveTextContent("Network: Example-Home");
    expect(start).toHaveTextContent("With permission");
    expect(screen.queryByRole("button", { name: "Delete move-in scan" })).toBeNull();
    await userEvent.click(within(start).getByRole("button", { name: "Save as my move-in scan" }));
    expect(calls.some((c) => c.method === "POST" && c.url === "/api/baseline")).toBe(true);
  });

  it("after saving, says when and to run another check", async () => {
    withBackend(<Compare result={null} />, {
      "GET /api/compare": { state: "no_check", baseline: BASELINE_SAVED, comparison: null },
    });
    expect(await screen.findByRole("heading", { level: 2, name: /^Starting point saved .*2026/ })).toBeInTheDocument();
    expect(screen.getByText("Run another check to compare.")).toBeInTheDocument();
  });

  it("says at the top, once, when the checks ran differently, and lists what wasn't checked", async () => {
    withBackend(<Compare result={RESULT} />, {
      "GET /api/compare": {
        ...COMPARE_READY,
        comparison: { ...COMPARE_READY.comparison!, not_checked: ["Router offers UPnP controls for opening internet ports"] },
      },
    });
    expect(await screen.findAllByText("These checks ran differently, so some differences may come from that.")).toHaveLength(1);
    expect(screen.queryByText("Some parts weren't checked this time")).toBeNull();
    const notChecked = screen.getByRole("region", { name: "Not checked this time" });
    expect(notChecked).toHaveTextContent("Router offers UPnP controls");
    expect(screen.getByRole("region", { name: "Not seen this time (1)" })).not.toHaveTextContent("UPnP");
  });

  it("lists coverage notes under their own title when both checks ran the same way", async () => {
    withBackend(<Compare result={RESULT} />, {
      "GET /api/compare": {
        ...COMPARE_READY,
        comparison: {
          ...COMPARE_READY.comparison!,
          ran_differently: false,
          scan_mode: "full",
          warnings: ["Bluetooth wasn't checked this time, so differences there may not show."],
        },
      },
    });
    const note = await screen.findByText(/Bluetooth wasn't checked this time/);
    expect(note.closest("div")?.parentElement).toHaveTextContent("Some parts weren't checked this time");
    expect(screen.queryByText(/These checks ran differently/)).toBeNull();
  });

  it("shows a device whose identification only varied with the higher band, not as Changed", async () => {
    withBackend(<Compare result={RESULT} />, { "GET /api/compare": COMPARE_READY });
    const varied = await screen.findByRole("region", { name: "Identification varied (1)" });
    const tv = within(varied).getByRole("article", { name: "TV or streaming stick" });
    expect(tv).toHaveTextContent("Likely");
    expect(tv).toHaveTextContent("Identification varied between checks");
    expect(within(screen.getByRole("region", { name: "Changed (1)" })).queryByText("TV or streaming stick")).toBeNull();
  });

  it("the header names the check being compared, not the move-in date", async () => {
    withBackend(<Compare result={RESULT} />, { "GET /api/compare": COMPARE_READY });
    await screen.findByRole("region", { name: "Move-in scan vs this check" });
    const line = screen.getByText(/Example-Home · .*2026.* · Listening only/);
    expect(line).toHaveTextContent(/20 Nov|Nov 20/);
  });

  it("deletes the baseline (in Help) only after confirming, from the keyboard", async () => {
    const { calls } = withBackend(<Help />, {
      "GET /api/baseline": BASELINE_SAVED,
      "DELETE /api/baseline": BASELINE_NONE,
    });
    const user = userEvent.setup();
    (await screen.findByRole("button", { name: "Delete move-in scan" })).focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("button", { name: "Keep it" })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("button", { name: "Delete move-in scan" })).toHaveFocus();
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    await user.keyboard("{Enter}");
    await user.tab();
    await user.keyboard("{Enter}"); // "Yes, delete it"
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE" && c.url === "/api/baseline")).toBe(true));
    expect(await screen.findByText("Your starting point was deleted from this laptop. Handover tasks and notes are still saved.")).toBeInTheDocument();
  });
});

describe("Handover: compact cards, filters and the message", () => {
  it("has the subtitle, and a summary with Open and Resolved filters", async () => {
    const one = { ...HANDOVER, tasks: HANDOVER.tasks.map((t) => (t.rule_id === "R-WPS" ? { ...t, status: "resolved" as const } : t)) };
    withBackend(<Handover />, { "GET /api/handover": one });
    expect(await screen.findByText("Track questions and follow-up actions for your host.")).toBeInTheDocument();
    expect(await screen.findByText("3 open · 1 resolved")).toBeInTheDocument();
    const filters = screen.getByRole("group", { name: "Show tasks" });
    const cam = screen.getByRole("article", { name: "Ask about the device that looks like a camera" });
    const wps = screen.getByRole("article", { name: "Ask for WPS to be turned off on the router" });
    await userEvent.click(within(filters).getByRole("button", { name: "Resolved (1)" }));
    expect(within(filters).getByRole("button", { name: "Resolved (1)" })).toHaveAttribute("aria-pressed", "true");
    expect(cam).not.toBeVisible();
    expect(wps).toBeVisible();
    await userEvent.click(within(filters).getByRole("button", { name: "Open (3)" }));
    expect(cam).toBeVisible();
    expect(wps).not.toBeVisible();
    await userEvent.click(within(filters).getByRole("button", { name: "All (4)" }));
    expect(wps).toBeVisible();
  });

  it("a card shows title, priority, device, status and evidence; it opens for the rest", async () => {
    withBackend(<Handover />);
    const cam = await screen.findByRole("article", { name: "Ask about the device that looks like a camera" });
    expect(cam).toHaveTextContent("Priority: Look at this first");
    expect(cam).toHaveTextContent("From the finding:");
    expect(cam).toHaveTextContent("To do");
    const details = cam.querySelector("details")!;
    expect(details.open).toBe(false);
    await userEvent.click(within(cam).getByText("Questions, steps and notes"));
    expect(details.open).toBe(true);
    // "What to ask" and "Steps" merged: the step that repeats the question is left out.
    expect(cam).not.toHaveTextContent("Ask where it is, what it records and who can view it.");
    expect(cam).toHaveTextContent("Ask for the answer in writing, so you have a record.");
  });

  it("closing a card keeps what you typed (and saves it)", async () => {
    withBackend(<Handover />);
    const cam = await screen.findByRole("article", { name: "Ask about the device that looks like a camera" });
    await userEvent.click(within(cam).getByText("Questions, steps and notes"));
    await userEvent.type(within(cam).getByRole("textbox", { name: "Notes" }), "Asked on Monday");
    await userEvent.click(within(cam).getByText("Questions, steps and notes")); // close
    await userEvent.click(within(cam).getByText("Questions, steps and notes")); // open again
    expect(within(cam).getByRole("textbox", { name: "Notes" })).toHaveValue("Asked on Monday");
  });

  it("the message comes first: choose the open tasks it asks about, edit, copy", async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    withBackend(<Handover />);
    const summary = (await screen.findByText("Draft message to host")).closest("summary")!;
    // Above the tasks.
    expect(summary.compareDocumentPosition(screen.getByRole("heading", { name: "Tasks (4)" })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await userEvent.click(summary);
    const box = screen.getByRole("textbox", { name: "Message" }) as HTMLTextAreaElement;
    expect(box.value).toBe(HANDOVER.message!.text); // all open tasks: the server's own draft
    await userEvent.click(screen.getByRole("checkbox", { name: "Ask for WPS to be turned off on the router" }));
    // The camera and UPnP now, in the same standard wording (the tracker task is your own).
    const ask = (rule: string) => HANDOVER.tasks.find((t) => t.rule_id === rule)!.ask;
    expect(box.value).toBe(
      "Hello,\n\nI checked the devices and Wi-Fi where I'm staying and have a few questions:\n\n1. " +
        ask("R-CAM") +
        "\n2. " +
        ask("R-UPNP") +
        "\n\nThank you for your help.",
    );
    // Edits are kept when the choice changes, until you ask to rewrite.
    await userEvent.type(box, " Thanks again.");
    await userEvent.click(screen.getByRole("checkbox", { name: "Ask for WPS to be turned off on the router" }));
    expect(box.value).toMatch(/Thanks again\.$/);
    await userEvent.click(screen.getByRole("button", { name: "Rewrite it from the tasks you chose" }));
    expect(box.value).toBe(HANDOVER.message!.text);
    await userEvent.click(screen.getByRole("button", { name: "Copy message" }));
    expect(writeText).toHaveBeenCalledWith(HANDOVER.message!.text);
  });
});

describe("Compare: filters and possibly the same device", () => {
  it("New / Not seen this time / Changed filter the lists", async () => {
    withBackend(<Compare result={RESULT} />, { "GET /api/compare": COMPARE_READY });
    const versus = await screen.findByRole("region", { name: "Move-in scan vs this check" });
    await userEvent.click(within(versus).getByRole("button", { name: /^New/ }));
    expect(within(versus).getByRole("button", { name: /^New/ })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("region", { name: "New (1)" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Changed (1)" })).toBeNull();
    expect(screen.queryByRole("region", { name: "Not seen this time (1)" })).toBeNull();
    await userEvent.click(within(versus).getByRole("button", { name: /^Not seen this time/ }));
    expect(screen.getByRole("region", { name: "Not seen this time (1)" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "New (1)" })).toBeNull();
    await userEvent.click(within(versus).getByRole("button", { name: /^All differences/ }));
    expect(screen.getByRole("region", { name: "Changed (1)" })).toBeInTheDocument();
  });

  it("a possible match can be confirmed or rejected, and the answer is saved", async () => {
    const answered = {
      ...COMPARE_READY,
      comparison: {
        ...COMPARE_READY.comparison!,
        possible: [{ ...COMPARE_READY.comparison!.possible![0]!, decision: "same" as const }],
        unchanged_possible: 0,
      },
    };
    const { calls } = withBackend(<Compare result={RESULT} />, {
      "GET /api/compare": COMPARE_READY,
      "POST /api/compare/matches": answered,
    });
    const section = await screen.findByRole("region", { name: "Possibly the same device (1)" });
    const laptop = within(section).getByRole("article", { name: "Computer or phone" });
    const group = within(laptop).getByRole("group", { name: "Is this the same device as at move-in?" });
    expect(within(group).getByRole("radio", { name: "Not sure" })).toBeChecked();
    expect(laptop).toHaveTextContent("Unconfirmed until you answer.");
    await userEvent.click(within(group).getByRole("radio", { name: "Same device" }));
    await waitFor(() => expect(within(group).getByRole("radio", { name: "Same device" })).toBeChecked());
    expect(laptop).toHaveTextContent("You said it's the same device.");
    const post = calls.find((c) => c.method === "POST" && c.url === "/api/compare/matches");
    expect(post?.body).toEqual({ match_id: COMPARE_READY.comparison!.possible![0]!.match_id, decision: "same" });
    // A device matched by its address isn't asked about.
    const plug = within(screen.getByRole("region", { name: "Changed (1)" })).getByRole("article", { name: "Smart plug or switch" });
    expect(within(plug).queryByRole("group", { name: "Is this the same device as at move-in?" })).toBeNull();
  });
});

describe("Compare: one row for a new camera", () => {
  it("R-NEW-CAMERA and R-CAM on the same device are one finding row, the other noted inside it", async () => {
    withBackend(<Compare result={RESULT} />, { "GET /api/compare": COMPARE_READY });
    const added = await screen.findByRole("region", { name: "New (1)" });
    const cam = within(added).getByRole("article", { name: "Camera" });
    const rows = within(cam).getAllByRole("listitem");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toHaveTextContent("Camera-like device that appeared since your move-in scan");
    expect(rows[0]).toHaveTextContent("Also flagged: Possible camera");
    // No "This network" pills on Compare cards.
    expect(document.body).not.toHaveTextContent("This network");
  });
});
