// Component tests for the Part B screens: Nearby, Locator, Report, Verify, and the top bar.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";

import type { ReportResponse } from "../api/types";
import { describe, expect, it, vi } from "vitest";

import { withBackend } from "../test/backend";
import { FakeLocatorSocket } from "../test/fakeLocatorSocket";
import {
  COULDNT_VERIFY,
  HANDOVER,
  NOT_TIMESTAMPED,
  NOTHING_FOUND,
  READINGS,
  REPORT,
  RESULT,
  SETUP_READY,
  TAMPERED,
  VERIFIED,
} from "../test/fixtures";
import { Locator } from "./Locator";
import { Nearby } from "./Nearby";
import { Report } from "./Report";
import { Verify } from "./Verify";

function withQuery(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const TRACKER = RESULT.nearby_items.find((i) => i.kind === "bluetooth")!;

describe("Nearby screen", () => {
  it("shows only signals that aren't your network, each with Locate signal", async () => {
    const onFind = vi.fn();
    withBackend(<Nearby result={RESULT} onFind={onFind} />);
    expect(screen.getByText(/^Wi-Fi and Bluetooth signals detected around you\. Some may come from the network you're using\./)).toBeInTheDocument();
    expect(screen.getByText(/only reads what they broadcast and never connects/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Flagged nearby (3)" })).toBeInTheDocument();
    // WPS on your own router is on Results, under "This network".
    expect(screen.queryByRole("article", { name: "Router advertises WPS" })).toBeNull();
    const tracker = screen.getByRole("article", { name: "Item tracker nearby" });
    expect(tracker).toHaveTextContent("Priority: Look at this soon");
    // The card's own button (the "Help identify this" panel repeats it when opened).
    const find = within(tracker).getAllByRole("button", { name: "Locate signal" })[0]!;
    expect(find).toHaveAccessibleDescription("Signal strength gives a rough idea of distance. It doesn't prove where a device is.");
    await userEvent.click(find);
    expect(onFind).toHaveBeenCalledWith(TRACKER);
    expect(screen.getByText("Compared with your Wi-Fi: “Example-Home”")).toBeInTheDocument();
  });

  it("other signals are one small line, and coverage is a compact disclosure", async () => {
    withBackend(<Nearby result={RESULT} onFind={() => {}} />);
    const line = screen.getByText(/^Other signals detected: 6 Wi-Fi networks · 4 Bluetooth devices/);
    expect(line).toHaveTextContent("3 earbuds, headphones or speakers");
    expect(line.nextElementSibling).toHaveTextContent("nothing about them was kept");
    expect(screen.queryByRole("region", { name: "Also heard, then discarded" })).toBeNull();
    // Coverage and limits: closed while something is flagged, and opens from the keyboard.
    const coverage = document.getElementById("nearby-checks") as HTMLDetailsElement;
    expect(coverage.tagName).toBe("DETAILS");
    expect(coverage.open).toBe(false);
    expect(coverage.querySelector("summary")).toHaveTextContent(/Nearby coverage\s*\d+ checked · \d+ not checked/);
    await userEvent.click(within(coverage).getByText("Nearby coverage"));
    expect(coverage.open).toBe(true);
    expect(coverage).toHaveTextContent("Some signals may come from neighbouring rooms or buildings.");
  });

  it("nothing flagged: Not detected by these checks, with coverage and limits open", async () => {
    const result = { ...RESULT, findings: RESULT.findings.filter((f) => f.scope !== "nearby") };
    withBackend(<Nearby result={result} onFind={() => {}} />);
    expect(screen.getByText("Not detected by these checks")).toBeInTheDocument();
    expect(screen.getByText("No nearby signals were flagged.")).toBeInTheDocument();
    const coverage = document.getElementById("nearby-checks") as HTMLDetailsElement;
    expect(coverage.open).toBe(true);
    coverage.open = false;
    await userEvent.click(screen.getByRole("button", { name: "See nearby coverage and limits" }));
    expect(coverage.open).toBe(true);
    expect(coverage.querySelector("summary")).toHaveFocus();
    expect(document.body).not.toHaveTextContent(/\bsafe\b/i);
  });

  it("says the nearby check didn't run, instead of that nothing was there", () => {
    withBackend(<Nearby result={{ ...NOTHING_FOUND, nearby_heard: null }} onFind={() => {}} />);
    expect(screen.getByText("Nearby signals: not checked this time, so nothing nearby is listed.")).toBeInTheDocument();
    expect(screen.queryByText("Not detected by these checks")).toBeNull();
  });
});

function setupLocator() {
  FakeLocatorSocket.all = [];
  vi.stubGlobal("WebSocket", FakeLocatorSocket);
  const speak = vi.fn();
  vi.stubGlobal("speechSynthesis", { speak, cancel: vi.fn() });
  vi.stubGlobal(
    "SpeechSynthesisUtterance",
    class {
      constructor(readonly text: string) {}
    },
  );
  const onBack = vi.fn();
  const view = render(<Locator item={TRACKER} onBack={onBack} />);
  const socket = FakeLocatorSocket.last;
  if (!socket) throw new Error("no socket");
  return { socket, speak, onBack, view };
}

describe("Locator screen", () => {
  it("opens the locator for the flagged item only, on this page's origin", () => {
    const { socket } = setupLocator();
    expect(socket.url).toBe(`ws://${window.location.host}/api/nearby/locate/${encodeURIComponent(TRACKER.ref)}`);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Locate signal: Tile tracker");
    expect(screen.getByText("The locator only works for items flagged in your latest check.")).toBeInTheDocument();
  });

  it("shows a large bar and warmer or colder in words", () => {
    const { socket } = setupLocator();
    act(() => socket.push(READINGS[0]!));
    expect(screen.getByText(/Getting a steady reading/)).toBeInTheDocument();
    act(() => READINGS.slice(1).forEach((r) => socket.push(r)));
    const meter = screen.getByRole("meter", { name: "Signal strength" });
    expect(meter).toHaveAttribute("aria-valuenow", String(Math.round(READINGS[9]!.level * 100)));
    expect(meter).toHaveAttribute("aria-valuetext", "Warmer");
    expect(screen.getByText("Warmer")).toHaveAttribute("aria-live", "polite");
    expect(screen.getByText("Over the last 30 seconds the signal got stronger.")).toBeInTheDocument();
  });

  it("drops the words when the signal is jumping around, and shows the Wi-Fi note", () => {
    const { socket } = setupLocator();
    act(() =>
      socket.push({
        ...READINGS[5]!,
        trend: null,
        unstable: true,
        message: "The signal is jumping around. Move more slowly and hold the laptop still.",
        note: "Wi-Fi readings update every few seconds, so move slowly and pause at each spot.",
      }),
    );
    expect(screen.queryByText("Warmer")).toBeNull();
    expect(screen.getAllByText(/The signal is jumping around/).length).toBeGreaterThan(0);
    expect(screen.getByText(/Wi-Fi readings update every few seconds/)).toBeInTheDocument();
  });

  it("speaks only when turned on, and only when the word changes", async () => {
    const { socket, speak } = setupLocator();
    const toggle = screen.getByRole("checkbox", { name: /Say “warmer” or “colder” out loud/ });
    expect(toggle).not.toBeChecked(); // off by default
    act(() => READINGS.forEach((r) => socket.push(r)));
    expect(speak).not.toHaveBeenCalled();
    await userEvent.click(toggle);
    act(() => socket.push({ ...READINGS[9]!, trend: "colder" }));
    act(() => socket.push({ ...READINGS[9]!, trend: "colder" }));
    expect(speak).toHaveBeenCalledTimes(1);
    expect(speak.mock.calls[0]![0].text).toBe("Colder");
  });

  it("Stop closes the connection and says nothing was kept", async () => {
    const { socket } = setupLocator();
    act(() => socket.push(READINGS[4]!));
    await userEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(socket.closed).toBe(true);
    expect(screen.getByText("Stopped. Nothing from this session was kept.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Start again" }));
    expect(FakeLocatorSocket.all).toHaveLength(2);
    expect(FakeLocatorSocket.last?.closed).toBe(false);
  });

  it("closes its connection when you leave the screen", () => {
    const { socket, view } = setupLocator();
    act(() => socket.push(READINGS[4]!));
    view.unmount();
    expect(socket.closed).toBe(true);
  });

  it("shows the backend's message for an item that isn't in the latest check", () => {
    const { socket } = setupLocator();
    act(() => socket.push({ error: "That item isn't in the latest nearby check. Run the nearby check again." }));
    expect(screen.getByText(/isn't in the latest nearby check/)).toBeInTheDocument();
    expect(screen.queryByRole("meter")).toBeNull();
  });
});

function setupReport(
  over: Partial<ReportResponse> = {},
  verify: object = VERIFIED,
  aiKey = false,
  opts: { lastLabel?: string | null; fail?: number } = {},
) {
  const calls: string[] = [];
  const bodies: unknown[] = [];
  let failures = opts.fail ?? 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${url}`);
      if (url === "/api/setup") return new Response(JSON.stringify({ ...SETUP_READY, outside: { ...SETUP_READY.outside, ai: aiKey } }));
      if (url === "/api/handover") return new Response(JSON.stringify(HANDOVER));
      if (url === "/api/report/defaults") return new Response(JSON.stringify({ room_label: opts.lastLabel ?? null }));
      if (url === "/api/report") {
        bodies.push(JSON.parse(String(init?.body)));
        if (failures > 0) {
          failures -= 1;
          return new Response(JSON.stringify({ detail: "The PDF couldn't be made just now." }), { status: 503 });
        }
        return new Response(JSON.stringify({ ...REPORT, ...over }));
      }
      if (url === "/api/verify") return new Response(JSON.stringify(verify));
      return new Response(new Blob(["%PDF-1.7 made-up"]));
    }),
  );
  const writeText = vi.fn(async () => {});
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  const onOpenHandover = vi.fn();
  withQuery(<Report result={RESULT} onOpenHandover={onOpenHandover} />);
  return { calls, writeText, bodies, onOpenHandover };
}

describe("Report screen", () => {
  it("creates the report, previews it inline and offers the downloads", async () => {
    const { calls } = setupReport();
    await userEvent.click(screen.getByRole("button", { name: "Create report" }));
    const preview = await screen.findByTitle("Report preview");
    expect(preview).toHaveAttribute("src", `/api/report/files/${REPORT.pdf}?inline=true#navpanes=0`);
    // One bundle first; the files one by one as secondary links.
    expect(screen.getByRole("link", { name: "Download report bundle" })).toHaveAttribute("href", `/api/report/files/${REPORT.bundle}`);
    expect(screen.getByRole("link", { name: "PDF" })).toHaveAttribute("href", `/api/report/files/${REPORT.pdf}`);
    expect(screen.getByRole("link", { name: "Timestamp (.tsr)" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Fingerprint (.sha256)" })).toBeInTheDocument();
    expect(screen.getByText(REPORT.sha256)).toBeInTheDocument();
    expect(await screen.findByText("Checked: this PDF matches its timestamp.")).toBeInTheDocument();
    expect(calls).toContain("POST /api/verify");
    expect(calls.every((c) => c.includes(" /api/"))).toBe(true); // only RoomCheck's own backend
  });

  it("offers two independent choices, each saying what it sends; AI only with a key", async () => {
    const { bodies } = setupReport({}, VERIFIED, false);
    const stamp = await screen.findByRole("checkbox", { name: "Trusted timestamp" });
    expect(stamp).toHaveAccessibleDescription("Sends only the report's fingerprint to a timestamp service.");
    expect(screen.queryByRole("checkbox", { name: "AI explanations" })).toBeNull(); // no key
    await userEvent.click(stamp);
    await userEvent.click(screen.getByRole("button", { name: "Create report" }));
    await screen.findByTitle("Report preview");
    expect(bodies[0]).toEqual({
      ai: false,
      timestamp: false,
      include_network_name: true,
      include_device_names: true,
      include_notes: false,
      room_label: null,
    });
  });

  it("lets you choose what's in it: names in and notes out by default", async () => {
    const { bodies } = setupReport();
    const network = screen.getByRole("checkbox", { name: "Network name" });
    const devices = screen.getByRole("checkbox", { name: "Device names" });
    const notes = screen.getByRole("checkbox", { name: "Handover notes" });
    expect(network).toBeChecked();
    expect(devices).toBeChecked();
    expect(notes).not.toBeChecked();
    expect(notes).toHaveAccessibleDescription(/Off unless you choose it/);
    await userEvent.click(network);
    await userEvent.click(notes);
    await userEvent.click(screen.getByRole("button", { name: "Create report" }));
    await screen.findByTitle("Report preview");
    expect(bodies[0]).toMatchObject({ include_network_name: false, include_device_names: true, include_notes: true });
  });

  it("with a key, AI explanations is its own choice", async () => {
    const { bodies } = setupReport({}, VERIFIED, true);
    const aiBox = await screen.findByRole("checkbox", { name: "AI explanations" });
    expect(aiBox).toHaveAccessibleDescription("Sends each finding's rule and wording, with the device type and maker, to Anthropic. Never addresses, device names or network names.");
    expect(aiBox).toBeChecked();
    await userEvent.click(aiBox);
    await userEvent.click(screen.getByRole("button", { name: "Create report" }));
    await screen.findByTitle("Report preview");
    expect(bodies[0]).toEqual({
      ai: false,
      timestamp: true,
      include_network_name: true,
      include_device_names: true,
      include_notes: false,
      room_label: null,
    });
  });

  it("shows each service's real outcome, and never promises a timestamp that failed", async () => {
    setupReport({
      tsr: null,
      timestamped_at: null,
      timestamp_message: "The timestamp service couldn't be reached.",
      ai: { state: "unavailable", reason: "The AI didn't answer in time." },
      timestamp: { state: "unavailable", reason: "The timestamp service couldn't be reached." },
    });
    await userEvent.click(screen.getByRole("button", { name: "Create report" }));
    const outcomes = await screen.findByRole("region", { name: "What happened" });
    expect(outcomes).toHaveTextContent("AI explanationsUnavailable: The AI didn't answer in time.");
    expect(outcomes).toHaveTextContent("Trusted timestampUnavailable: The timestamp service couldn't be reached.");
    expect(screen.getByText("This report has no trusted timestamp.")).toBeInTheDocument();
    expect(screen.queryByText("Checked: this PDF matches its timestamp.")).toBeNull();
    expect(screen.queryByRole("link", { name: "Timestamp (.tsr)" })).toBeNull();
  });

  it("says what verifying proves, and links to Handover for the host", async () => {
    const { onOpenHandover } = setupReport();
    await userEvent.click(screen.getByRole("button", { name: "Create report" }));
    expect(
      await screen.findByText(
        "Verifying shows the report hasn't changed since it was timestamped. It doesn't prove the findings are correct.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "What happened" })).toHaveTextContent("Trusted timestampAdded");
    expect(screen.queryByRole("region", { name: "Message to your host" })).toBeNull();
    expect(screen.getByText(/Need to contact your host\?/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Open Handover" }));
    expect(onOpenHandover).toHaveBeenCalled();
  });
});

function setupVerify(answer: object) {
  const bodies: FormData[] = [];
  const urls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      urls.push(url);
      bodies.push(init?.body as FormData);
      return new Response(JSON.stringify(answer));
    }),
  );
  withQuery(<Verify />);
  return { bodies, urls };
}

async function pickFiles(pdf: string) {
  await userEvent.upload(screen.getByLabelText(/^Report PDF/), new File([pdf], "report.pdf", { type: "application/pdf" }));
  await userEvent.upload(screen.getByLabelText(/^Timestamp file/), new File(["token"], "report.tsr"));
}

describe("Verify screen", () => {
  it("can't check until the PDF is chosen, and says why", async () => {
    const { urls } = setupVerify(VERIFIED);
    const button = screen.getByRole("button", { name: "Check the report" });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).toHaveAccessibleDescription("Choose the report's PDF to check it.");
    await userEvent.click(button);
    expect(urls).toEqual([]);
    expect(screen.getByText(/never sent anywhere else/)).toBeInTheDocument();
  });

  it("shows a verified report in plain words", async () => {
    const { bodies, urls } = setupVerify(VERIFIED);
    await pickFiles("%PDF genuine");
    await userEvent.click(screen.getByRole("button", { name: "Check the report" }));
    expect(await screen.findByRole("heading", { name: "Verified" })).toBeInTheDocument();
    expect(screen.getByText(/This PDF matches its timestamp/)).toBeInTheDocument();
    expect(screen.getByText("FreeTSA, the timestamp service RoomCheck uses")).toBeInTheDocument();
    expect(urls).toEqual(["/api/verify"]); // RoomCheck's own backend, nothing else
    expect((bodies[0]!.get("pdf") as File).size).toBeGreaterThan(0);
    expect(bodies[0]!.get("tsr")).not.toBeNull();
  });

  it("Files don't match: a valid token, a different PDF", async () => {
    setupVerify(TAMPERED);
    await pickFiles("%PDF changed");
    await userEvent.click(screen.getByRole("button", { name: "Check the report" }));
    expect(await screen.findByText("Files don't match")).toBeInTheDocument();
    expect(screen.getByText(/The timestamp is valid, but this PDF's fingerprint is different/)).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Verified" })).toBeNull();
    // The danger look (the High tokens), in the same card as the other outcomes.
    const outcome = screen.getByRole("region", { name: "Files don't match" });
    expect(outcome).toHaveClass("border-sev-high");
    expect(outcome.querySelector(".text-sev-high")).not.toBeNull();
  });

  it("Couldn't verify, with the specific reason", async () => {
    setupVerify(COULDNT_VERIFY);
    await pickFiles("%PDF genuine");
    await userEvent.click(screen.getByRole("button", { name: "Check the report" }));
    expect(await screen.findByText("Couldn't verify")).toBeInTheDocument();
    expect(screen.getByText(/wasn't signed by the timestamp service RoomCheck uses/)).toBeInTheDocument();
  });

  it("explains a report that wasn't timestamped, and never calls it altered", async () => {
    const { bodies } = setupVerify(NOT_TIMESTAMPED);
    await userEvent.upload(screen.getByLabelText(/^Report PDF/), new File(["%PDF x"], "report.pdf", { type: "application/pdf" }));
    await userEvent.click(screen.getByRole("button", { name: "Check the report" }));
    expect(await screen.findByRole("heading", { name: "Not timestamped" })).toBeInTheDocument();
    expect(screen.getByText("This report wasn't timestamped, so it can't be timestamp-verified.")).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(/altered|tampered|has changed/i);
    expect(bodies[0]!.get("tsr")).toBeNull();
  });
});

// The header (stages, New check, the open-task count) is tested in src/ds/Header.test.tsx.

describe("Report screen: before and while it's made", () => {
  it("says what the report will contain before it's made", async () => {
    setupReport();
    const contents = await screen.findByRole("region", { name: "This report will contain" });
    expect(contents).toHaveTextContent(/Check.*2026.*Listening only|Check.*2026.*With permission/);
    expect(contents).toHaveTextContent("Things to look at5: Watching 2 · Control 0 · Wi-Fi 3");
    expect(contents).toHaveTextContent(/Coverage\d+ of \d+ checks ran/);
    expect(await within(contents).findByText("4 tasks, with their status and evidence")).toBeInTheDocument();
    expect(contents).toHaveTextContent("Network name included · device names included · notes left out");
    expect(contents).toHaveTextContent("AI explanations off · trusted timestamp on");
    // It follows the choices above.
    await userEvent.click(screen.getByRole("checkbox", { name: "Handover notes" }));
    expect(contents).toHaveTextContent("notes included");
  });

  it("fills in the last room label used", async () => {
    const { bodies } = setupReport({}, VERIFIED, false, { lastLabel: "Flat 4B" });
    const box = screen.getByRole("textbox", { name: "Room name (optional)" });
    await waitFor(() => expect(box).toHaveValue("Flat 4B"));
    expect(box).toHaveAccessibleDescription(/Filled in from your last report/);
    await userEvent.click(screen.getByRole("button", { name: "Create report" }));
    await screen.findByTitle("Report preview");
    expect((bodies[0] as { room_label: string }).room_label).toBe("Flat 4B");
  });

  it("shows progress, and an error with Try again that keeps the settings", async () => {
    const { bodies } = setupReport({}, VERIFIED, false, { fail: 1 });
    await userEvent.type(screen.getByRole("textbox", { name: "Room name (optional)" }), "Room 2");
    await userEvent.click(screen.getByRole("checkbox", { name: "Handover notes" }));
    await userEvent.click(screen.getByRole("button", { name: "Create report" }));
    expect(await screen.findByText("The PDF couldn't be made just now.")).toBeInTheDocument();
    expect(screen.getByText("Your settings above are kept.")).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Room name (optional)" })).toHaveValue("Room 2");
    expect(screen.getByRole("checkbox", { name: "Handover notes" })).toBeChecked();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByTitle("Report preview");
    expect(bodies).toHaveLength(2);
    expect(bodies[1]).toEqual(bodies[0]); // the same settings, both times
  });
});

describe("Verify screen: one drop area for all three files", () => {
  const pdf = new File(["%PDF genuine"], "roomcheck-report.pdf", { type: "application/pdf" });
  const tsr = new File(["token"], "roomcheck-report.tsr");
  const hash = new File(["abc  roomcheck-report.pdf"], "roomcheck-report.sha256");
  const checklist = () => screen.getByRole("list", { name: "Files" });
  const row = (name: string) => within(checklist()).getByText(name).closest("li") as HTMLElement;

  it("takes the three files together and works out which is which", async () => {
    const { bodies } = setupVerify(VERIFIED);
    expect(row("Report PDF")).toHaveTextContent("Missing: needed to check the report.");
    expect(row("Timestamp (.tsr)")).toHaveTextContent("Optional: leave it out if the report wasn't timestamped.");
    await userEvent.upload(screen.getByLabelText("Choose report files"), [hash, tsr, pdf]);
    expect(row("Report PDF")).toHaveTextContent("Received: roomcheck-report.pdf");
    expect(row("Timestamp (.tsr)")).toHaveTextContent("Received: roomcheck-report.tsr");
    expect(row("Fingerprint (.sha256)")).toHaveTextContent("Received: roomcheck-report.sha256");
    await userEvent.click(screen.getByRole("button", { name: "Check the report" }));
    expect(await screen.findByRole("heading", { name: "Verified" })).toBeInTheDocument();
    // Each file went in its own field (the client names them report.*).
    expect((bodies[0]!.get("pdf") as File).size).toBe(pdf.size);
    expect((bodies[0]!.get("tsr") as File).size).toBe(tsr.size);
    expect((bodies[0]!.get("sha256") as File).size).toBe(hash.size);
  });

  it("the .tsr stays optional", async () => {
    setupVerify(NOT_TIMESTAMPED);
    await userEvent.upload(screen.getByLabelText("Choose report files"), [pdf]);
    expect(screen.getByRole("button", { name: "Check the report" })).toHaveAttribute("aria-disabled", "false");
    expect(row("Timestamp (.tsr)")).toHaveTextContent("Not added.");
  });

  it("says what's wrong next to the file it's about", async () => {
    setupVerify(VERIFIED);
    await userEvent.upload(screen.getByLabelText("Choose report files"), [new File([""], "empty.pdf", { type: "application/pdf" })]);
    expect(within(row("Report PDF")).getByRole("alert")).toHaveTextContent("“empty.pdf” is empty.");
    // In the individual fields too: a file of the wrong kind, next to that field's row.
    await userEvent.click(screen.getByText("Choose files individually"));
    await userEvent.upload(screen.getByLabelText(/^Timestamp file/), new File(["x"], "notes.sha256"), { applyAccept: false });
    expect(within(row("Timestamp (.tsr)")).getByRole("alert")).toHaveTextContent("“notes.sha256” isn't a .tsr file.");
  });

  it("names a file that isn't a report file", async () => {
    setupVerify(VERIFIED);
    await userEvent.upload(screen.getByLabelText("Choose report files"), [new File(["x"], "photo.jpg")], { applyAccept: false });
    expect(screen.getByRole("alert")).toHaveTextContent("“photo.jpg” isn't a report file.");
  });

  it("offers Verify another report after a result, which starts afresh", async () => {
    setupVerify(VERIFIED);
    await userEvent.upload(screen.getByLabelText("Choose report files"), [pdf, tsr]);
    await userEvent.click(screen.getByRole("button", { name: "Check the report" }));
    await screen.findByRole("heading", { name: "Verified" });
    await userEvent.click(screen.getByRole("button", { name: "Verify another report" }));
    expect(screen.queryByRole("heading", { name: "Verified" })).toBeNull();
    expect(row("Report PDF")).toHaveTextContent("Missing");
    expect(screen.getByRole("heading", { level: 1, name: "Verify a report" })).toHaveFocus();
  });
});
