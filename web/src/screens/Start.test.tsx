import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { App } from "../App";
import { withBackend } from "../test/backend";
import { BASELINE_SAVED, NETWORK_NAME, SETUP_CABLE, SETUP_MISSING, SETUP_OFFLINE } from "../test/fixtures";
import { Start } from "./Start";

const YES = "Yes, I have permission";
const NO = "No, or I'm not sure";
const LISTEN = "RoomCheck only listens. You can ask your host for permission.";
const REQUIRED = "Choose an answer to continue.";
const HINT = "Being on the Wi-Fi isn't the same as permission. What counts?";
const LEGAL = "Checking devices on a network without permission may be against the law in many places.";
const INTRO = "Find out what's connected, who else might control it, and whether the Wi-Fi can be trusted. About 2 minutes.";

afterEach(() => vi.unstubAllGlobals());

function start(routes = {}, onStart = () => {}, onOpenHelp = () => {}) {
  return withBackend(<Start onStart={onStart} onOpenHelp={onOpenHelp} />, routes);
}

describe("Start screen", () => {
  it("opens with the title and one line, the duration in it, and no feature tags", () => {
    start();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Check your room's Wi-Fi and devices");
    expect(screen.getByText(INTRO)).toBeVisible();
    expect(screen.queryByRole("list", { name: "What RoomCheck checks" })).toBeNull();
    expect(screen.queryByText("What does RoomCheck check?")).toBeNull();
    // The duration appears once.
    expect(screen.getAllByText(/2 minutes/)).toHaveLength(1);
    expect(screen.getByText("Stay connected to this Wi-Fi")).toBeVisible();
  });

  it("permission: the heading, one line, and What counts? opens the explanation with the legal line", async () => {
    start();
    const group = screen.getByRole("group", { name: "Do you have permission to check this network?" });
    expect(group).toHaveAccessibleDescription(HINT);
    const counts = within(group).getByRole("button", { name: "What counts?" });
    expect(counts).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText(LEGAL)).not.toBeVisible();
    await userEvent.click(counts);
    expect(counts).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(LEGAL)).toBeVisible();
    expect(screen.getByText(/You own the network/)).toBeVisible();
    expect(screen.getByText(/ideally in writing/)).toBeVisible();
    expect(screen.getByText(/This isn't legal advice. If you're not sure, choose “No, or I'm not sure”/)).toBeVisible();
  });

  it("two answers, nothing chosen, and no instruction until Start is pressed", () => {
    start();
    const radios = within(screen.getByRole("group", { name: "Do you have permission to check this network?" })).getAllByRole("radio");
    expect(radios.map((r) => r.closest("label")?.textContent)).toEqual([
      "Yes, I have permissionAlso checks what each device runs, as well as announced signals.",
      `${NO}${LISTEN}`,
    ]);
    expect(radios.every((r) => !(r as HTMLInputElement).checked)).toBe(true);
    expect(screen.getByRole("radio", { name: YES })).toHaveAccessibleDescription(/as well as announced signals/);
    expect(screen.queryByText(REQUIRED)).toBeNull();
  });

  it("selects an answer from anywhere on its row", async () => {
    start();
    await userEvent.click(screen.getByText(LISTEN));
    const no = screen.getByRole("radio", { name: NO });
    expect(no).toBeChecked();
    expect(no.closest("label")).toHaveClass("border-accent");
    expect(screen.getByRole("radio", { name: YES }).closest("label")).not.toHaveClass("border-accent");
  });

  it.each([
    [YES, "Start full check", true],
    [NO, "Start listening-only check", false],
  ])("%s labels the button %s and starts with consent %s", async (answer, label, consent) => {
    const onStart = vi.fn();
    start({}, onStart);
    await userEvent.click(screen.getByRole("radio", { name: answer }));
    const button = screen.getByRole("button", { name: label });
    expect(button).toHaveAttribute("aria-disabled", "false");
    expect(button).toHaveClass("bg-lagoon", "text-ink");
    await userEvent.click(button);
    expect(onStart).toHaveBeenCalledWith(consent, "other"); // no stay chosen: "Other"
  });

  it("Start with no answer: nothing starts, the instruction appears and the focus goes to the answers", async () => {
    const onStart = vi.fn();
    start({}, onStart);
    const button = screen.getByRole("button", { name: "Start the check" });
    await userEvent.click(button);
    expect(onStart).not.toHaveBeenCalled();
    expect(screen.getByText(REQUIRED)).toBeVisible();
    expect(screen.getByText(REQUIRED).closest("[aria-live]")).toHaveAttribute("aria-live", "polite");
    expect(button).toHaveAccessibleDescription(REQUIRED);
    expect(screen.getByRole("group", { name: /permission/ })).toHaveAccessibleDescription(`${HINT} ${REQUIRED}`);
    expect(screen.getByRole("radio", { name: YES })).toHaveFocus();

    await userEvent.click(screen.getByRole("radio", { name: NO }));
    expect(screen.queryByText(REQUIRED)).toBeNull();
    expect(screen.getByRole("group", { name: /permission/ })).toHaveAccessibleDescription(HINT);
  });

  it("stay: Optional beside the label, short pills, each with its full description", async () => {
    const onStart = vi.fn();
    start({}, onStart);
    const stay = screen.getByRole("group", { name: "Where are you staying? Optional" });
    expect(within(stay).getAllByRole("radio").map((r) => r.getAttribute("value"))).toEqual(["short_stay", "rental", "hostel", "other"]);
    for (const name of ["Short stay", "Room or flat rental", "Hostel", "Other"]) {
      expect(within(stay).getByRole("radio", { name })).toBeInTheDocument();
    }
    const short = within(stay).getByRole("radio", { name: "Short stay" });
    expect(short).toHaveAccessibleDescription("Airbnb or a hotel-style rental");
    expect(short.closest("label")).toHaveAttribute("title", "Airbnb or a hotel-style rental");
    expect(within(stay).getByRole("radio", { name: "Hostel" })).toHaveAccessibleDescription("A hostel or other shared accommodation");
    await userEvent.click(short);
    await userEvent.click(screen.getByRole("radio", { name: YES }));
    await userEvent.click(screen.getByRole("button", { name: "Start full check" }));
    expect(onStart).toHaveBeenCalledWith(true, "short_stay");
  });

  it("works with the keyboard alone", async () => {
    const onStart = vi.fn();
    start({}, onStart);
    await screen.findByText(`Connected to ${NETWORK_NAME}`);
    const user = userEvent.setup();
    const order = [
      screen.getByRole("button", { name: "Check again" }),
      screen.getByRole("button", { name: "What counts?" }),
      screen.getByRole("radio", { name: YES }),
    ];
    for (const el of order) {
      await user.tab();
      expect(el).toHaveFocus();
    }
    await user.keyboard("{ArrowDown}"); // moves to and selects "No, or I'm not sure"
    expect(screen.getByRole("radio", { name: NO })).toBeChecked();
    // Listening only: asking the host for permission comes next, then where you're staying.
    await user.tab();
    expect(screen.getByText("Ask your host for permission")).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("radio", { name: "Short stay" })).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("button", { name: "Start listening-only check" })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(onStart).toHaveBeenCalledWith(false, "other");
  });

  it("shows the backend's message when the check can't start", () => {
    withBackend(<Start onStart={() => {}} error="A check is already running. Wait for it to finish, then try again." />);
    expect(screen.getByRole("alert")).toHaveTextContent("A check is already running.");
  });

  it("one footer line, linking to Help's sections; no privacy expander on Start", async () => {
    const onOpenHelp = vi.fn();
    start({}, () => {}, onOpenHelp);
    const footer = screen.getByText(/^Results are clues, not proof\. Everything runs on this laptop\./);
    expect(footer).toHaveTextContent("Results are clues, not proof. Everything runs on this laptop. What it can't see and what's sent");
    await userEvent.click(within(footer).getByRole("button", { name: "What it can't see" }));
    expect(onOpenHelp).toHaveBeenLastCalledWith("help-cant");
    await userEvent.click(within(footer).getByRole("button", { name: "what's sent" }));
    expect(onOpenHelp).toHaveBeenLastCalledWith("help-online");
    expect(document.getElementById("privacy-calls")).toBeNull();
    expect(screen.queryByText(/^AI explanations \(off unless/)).toBeNull();
  });
});

describe("Connection bar", () => {
  it("all ready: Connected to <network> and Check again only", async () => {
    start();
    expect(await screen.findByText(`Connected to ${NETWORK_NAME}`)).toBeVisible();
    const strip = screen.getByRole("region", { name: "Is this laptop ready?" });
    expect(within(strip).getAllByRole("button").map((b) => b.textContent)).toEqual(["Check again"]);
    expect(screen.queryByText("Checking a different network?")).toBeNull();
    expect(screen.queryByText(/All set/)).toBeNull();
    expect(screen.queryByText("Missing")).toBeNull();
  });

  it("some missing: says what's missing, how to fix it and what will be limited, without blocking", async () => {
    const onStart = vi.fn();
    start({ "GET /api/setup": SETUP_MISSING }, onStart);
    expect(await screen.findByText(`Connected to ${NETWORK_NAME}`)).toBeVisible();
    const strip = screen.getByRole("region", { name: "Is this laptop ready?" });
    expect(within(strip).getAllByText("Missing")).toHaveLength(2);
    expect(within(strip).getByText(/Turn on Bluetooth in Quick Settings/)).toBeVisible();
    expect(within(strip).getByText(/Install Nmap from nmap.org/)).toBeVisible();
    expect(within(strip).getByText("Ready: Wi-Fi radio, Windows Location, Npcap.")).toBeVisible();
    expect(
      within(strip).getByText(/^These checks will be limited: the tracker check, checking which services devices offer\./),
    ).toBeVisible();
    // A problem: how to switch networks is offered.
    expect(within(strip).getByText("Checking a different network?")).toBeVisible();
    expect(within(strip).queryByRole("button", { name: /Continue/ })).toBeNull();
    await userEvent.click(screen.getByRole("radio", { name: YES }));
    expect(screen.queryByRole("button", { name: "Start full check" })).toBeNull();
    // Missing items never block the start.
    await userEvent.click(screen.getByRole("button", { name: "Start check (some parts limited)" }));
    expect(onStart).toHaveBeenCalledWith(true, "other");
  });

  it("not connected: asks to connect to the room's Wi-Fi first, and how to switch", async () => {
    start({ "GET /api/setup": SETUP_OFFLINE });
    expect(await screen.findByText("Not connected to a network")).toBeVisible();
    expect(screen.getByText(/Connect to the room's Wi-Fi first/)).toBeVisible();
    await userEvent.click(screen.getByText("Checking a different network?"));
    expect(screen.getByText(/Quick Settings \(Windows key \+ A\)/)).toBeVisible();
    expect(screen.getByText(/never changes Windows settings/)).toBeVisible();
  });

  it("cable: says so, with no network name", async () => {
    start({ "GET /api/setup": SETUP_CABLE });
    expect(await screen.findByText("Connected by cable")).toBeVisible();
  });

  it("checks again on request", async () => {
    const { calls } = start();
    await screen.findByText(`Connected to ${NETWORK_NAME}`);
    const before = calls.filter((c) => c.url === "/api/setup").length;
    await userEvent.click(screen.getByRole("button", { name: "Check again" }));
    await waitFor(() => expect(calls.filter((c) => c.url === "/api/setup").length).toBe(before + 1));
  });

  it("still lets you start when the setup can't be read", async () => {
    const onStart = vi.fn();
    start(
      {
        "GET /api/setup": () => {
          throw new Error("offline in this test");
        },
      },
      onStart,
    );
    expect(await screen.findByText(/Couldn't check this laptop's setup/)).toBeVisible();
    await userEvent.click(screen.getByRole("radio", { name: NO }));
    await userEvent.click(screen.getByRole("button", { name: "Start listening-only check" }));
    expect(onStart).toHaveBeenCalledWith(false, "other");
  });

  it("never sends the network name anywhere", async () => {
    const { calls } = start({ "GET /api/setup": SETUP_MISSING });
    await screen.findByText(`Connected to ${NETWORK_NAME}`);
    await userEvent.click(screen.getByRole("radio", { name: YES }));
    expect(calls.every((c) => c.method === "GET" && !c.url.includes(NETWORK_NAME))).toBe(true);
  });
});

describe("Top bar before a check", () => {
  it("shows only Verify when no move-in scan is saved", async () => {
    withBackend(<App />);
    const nav = await screen.findByRole("navigation");
    await waitFor(() =>
      expect(within(nav).getAllByRole("button").map((b) => b.textContent)).toEqual(["Verify a report", "Help"]),
    );
  });

  it("adds Compare when a move-in scan is saved", async () => {
    withBackend(<App />, { "GET /api/baseline": BASELINE_SAVED });
    const nav = await screen.findByRole("navigation");
    await waitFor(() =>
      expect(within(nav).getAllByRole("button").map((b) => b.textContent)).toEqual(["Compare", "Verify a report", "Help"]),
    );
  });
});
