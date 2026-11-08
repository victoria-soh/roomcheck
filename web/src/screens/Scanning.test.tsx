import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { ScanSnapshot } from "../api/types";
import { FakeSocket } from "../test/fakeSocket";
import {
  BLUETOOTH_OFF,
  CANCELLED,
  DONE_WITH_RESULT,
  FINISHED,
  LISTENING,
  MIDWAY,
  NVD_SKIPPED,
  RESULT,
  SETUP_READY,
  SLOW,
  STARTING,
} from "../test/fixtures";
import { Scanning } from "./Scanning";

interface Backend {
  poll: ScanSnapshot | "fail";
}

function setup(start: Partial<Backend> = {}) {
  FakeSocket.all = [];
  vi.stubGlobal("WebSocket", FakeSocket);
  const backend: Backend = { poll: DONE_WITH_RESULT(RESULT), ...start };
  const calls: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${url}`);
      if (url.endsWith("/cancel")) return new Response(JSON.stringify(CANCELLED));
      if (url.endsWith("/api/setup")) return new Response(JSON.stringify(SETUP_READY));
      if (backend.poll === "fail") return new Response("{}", { status: 503 });
      return new Response(JSON.stringify(backend.poll));
    }),
  );
  const onComplete = vi.fn();
  const onShowResults = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Scanning scanId="job1" consent={false} onComplete={onComplete} onShowResults={onShowResults} onRestart={() => {}} />
    </QueryClientProvider>,
  );
  const socket = FakeSocket.last;
  if (!socket) throw new Error("no socket");
  return { socket, backend, calls, onComplete, onShowResults };
}

const NEARBY = "Looking at nearby Wi-Fi and Bluetooth";

function row(name: string) {
  return within(screen.getByRole("list", { name: "Steps" })).getByText(name).closest("li") as HTMLElement;
}


const task = () => document.getElementById("current-task") as HTMLElement;

describe("Scanning screen: heading and progress", () => {
  it("shows the network and mode under the page title", async () => {
    setup();
    expect(await screen.findByText("Example-Home · Listening only")).toBeInTheDocument();
  });

  it("the card is 'Scan progress', naming one running task, and combining several", () => {
    const { socket } = setup();
    act(() => socket.send(STARTING)); // listening and nearby at the same time
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("Scan progress");
    expect(task()).toHaveTextContent("Scanning devices and nearby signals");
    act(() => socket.send({ ...MIDWAY, steps: MIDWAY.steps.map((s) => (s.key === "nearby" ? { ...s, status: "failed" } : s)) }));
    expect(task()).toHaveTextContent("Checking the router");
  });

  it("counts tasks done, not a step number, and shows elapsed time against the usual length", () => {
    const { socket } = setup();
    act(() => socket.send(LISTENING));
    // Counted from the five rows shown; the skipped one is done with.
    expect(screen.getAllByRole("listitem")).toHaveLength(5);
    expect(screen.getByText(/^1 of 5 tasks done · Elapsed 0:4\d · usually about 2 minutes$/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar", { name: "Scan progress" })).toHaveAttribute("aria-valuetext", "1 of 5 tasks done");
    act(() => socket.send(MIDWAY));
    expect(screen.getByText(/^3 of 5 tasks done · /)).toBeInTheDocument(); // listening, nearby (with a note) and the skipped one
    expect(screen.getByRole("progressbar", { name: "Scan progress" })).toHaveAttribute("value", "3");
    expect(document.body.textContent).not.toMatch(/\d+ ?%/);
  });

  it("says when it's taking longer than the estimate", () => {
    const { socket } = setup();
    act(() => socket.send(SLOW));
    expect(screen.getByText(/Taking longer than usual\. Larger networks can take a few more minutes\./)).toBeInTheDocument();
    expect(screen.queryByText(/usually about 2 minutes/)).toBeNull();
  });

  it("shows the device count beside the heading", () => {
    const { socket } = setup();
    act(() => socket.send(STARTING));
    expect(screen.getByText("Waiting for device results")).toBeInTheDocument();
    act(() => socket.send(LISTENING));
    expect(screen.getByText("3 devices found so far")).toBeInTheDocument();
  });
});

describe("Scanning screen: tasks", () => {
  it("lists each task with an icon and a word on the right", () => {
    const { socket } = setup();
    act(() => socket.send(MIDWAY));
    expect(row("Listening for devices")).toHaveTextContent("Done");
    expect(row("Checking the router")).toHaveTextContent("Running");
    expect(row(NEARBY)).toHaveTextContent("Couldn't finish");
    expect(row("Preparing your results")).toHaveTextContent("Waiting");
    for (const li of Array.from(screen.getByRole("list", { name: "Steps" }).children)) {
      expect(li.querySelector("svg[aria-hidden='true']")).not.toBeNull();
    }
  });

  it("lists tasks in the order they start, so ones that run together sit together", () => {
    const { socket } = setup();
    act(() => socket.send(STARTING));
    const names = within(screen.getByRole("list", { name: "Steps" }))
      .getAllByRole("listitem")
      .map((li) => li.querySelector("p")?.textContent);
    expect(names).toEqual([
      "Listening for devices",
      "Looking at nearby Wi-Fi and Bluetooth",
      "Checking which services devices offer",
      "Checking the router",
      "Preparing your results",
    ]);
  });

  it("shows a listening-only check's skipped task as Not checked, with the reason, from the start", () => {
    const { socket } = setup();
    act(() => socket.send(STARTING));
    const services = row("Checking which services devices offer");
    expect(services).toHaveTextContent("Not checked");
    expect(services).toHaveTextContent("Needs permission to check the network");
    expect(services).not.toHaveTextContent("Waiting");
  });

  it("shows one live detail under each running task, from real counts", () => {
    const { socket } = setup();
    act(() => socket.send(LISTENING));
    expect(row("Listening for devices")).toHaveTextContent("Heard 3 devices so far");
    expect(row(NEARBY)).toHaveTextContent("Heard 12 nearby networks");
    act(() => socket.send(MIDWAY)); // listening is done: no detail any more
    expect(row("Listening for devices")).not.toHaveTextContent("Heard");
  });

  it("says the nearby task is scanning until the Wi-Fi count arrives, then the counts", () => {
    const { socket } = setup();
    act(() => socket.send(STARTING));
    expect(row(NEARBY)).toHaveTextContent("Scanning nearby Wi-Fi…");
    const withCounts = (detail: Record<string, number>) => ({
      ...STARTING,
      version: STARTING.version + Object.keys(detail).length + 1,
      steps: STARTING.steps.map((s) => (s.key === "nearby" ? { ...s, detail } : s)),
    });
    act(() => socket.send(withCounts({ wifi: 12 })));
    expect(row(NEARBY)).toHaveTextContent("Heard 12 nearby networks");
    expect(row(NEARBY)).not.toHaveTextContent("Scanning nearby Wi-Fi");
    act(() => socket.send(withCounts({ wifi: 12, bluetooth: 4 })));
    expect(row(NEARBY)).toHaveTextContent("Heard 12 nearby networks and 4 Bluetooth devices");
  });

  it("gives a Bluetooth-only count when the Wi-Fi survey couldn't run", () => {
    const { socket } = setup();
    act(() =>
      socket.send({
        ...STARTING,
        version: 5,
        steps: STARTING.steps.map((s) => (s.key === "nearby" ? { ...s, detail: { bluetooth: 1 } } : s)),
      }),
    );
    expect(row(NEARBY)).toHaveTextContent("Heard 1 Bluetooth device");
    expect(row(NEARBY)).not.toHaveTextContent("networks");
  });

  it("puts each failure under its task, with “the rest carries on” inside that task's note", () => {
    const { socket } = setup();
    act(() => socket.send(MIDWAY));
    expect(row(NEARBY)).toHaveTextContent(`${BLUETOOTH_OFF}The rest of the check carries on.`);
    expect(row("Checking the router")).not.toHaveTextContent("carries on");
    expect(screen.getAllByText("The rest of the check carries on.")).toHaveLength(1);
  });

  it("the known-issues lookup note sits under the services step (full checks), never the router", () => {
    const { socket } = setup();
    act(() =>
      socket.send({
        ...MIDWAY,
        steps: MIDWAY.steps.map((s) =>
          s.key === "services" ? { key: "services", status: "done" as const, problems: [NVD_SKIPPED] } : s,
        ),
      }),
    );
    expect(row("Checking which services devices offer")).toHaveTextContent(`${NVD_SKIPPED}The rest of the check carries on.`);
    // The step had finished: it stays Done, with the lookup's note under it.
    expect(row("Checking which services devices offer")).toHaveTextContent("Done");
    expect(row("Checking which services devices offer")).not.toHaveTextContent("Couldn't finish");
    expect(row("Checking the router")).not.toHaveTextContent(NVD_SKIPPED);
  });

  it("announces task changes once, not on every heartbeat", () => {
    const { socket } = setup();
    act(() => socket.send(STARTING));
    const region = document.querySelectorAll("p.sr-only[aria-live='polite']")[0] as HTMLElement;
    expect(region).toHaveTextContent("Listening for devices: Running");
    act(() => socket.send(MIDWAY));
    expect(region).toHaveTextContent("Checking the router: Running");
    const changes: MutationRecord[] = [];
    const observer = new MutationObserver((m) => changes.push(...m));
    observer.observe(region, { childList: true, characterData: true, subtree: true });
    act(() => {
      socket.send({ ...MIDWAY, elapsed_seconds: 69 });
      socket.send({ ...MIDWAY, elapsed_seconds: 74 });
    });
    observer.disconnect();
    expect(changes).toHaveLength(0);
  });
});

describe("Scanning screen: connection problems", () => {
  // The 20 s "updates stopped" level, Retry and the poll-detected finish are checked in a real
  // browser with a controlled clock (e2e/scanning.spec.ts).
  it("shows only a quiet line while polling keeps the screen up to date", async () => {
    const { socket } = setup({ poll: { ...MIDWAY, version: 11 } });
    act(() => socket.send(MIDWAY));
    act(() => socket.drop());
    const card = screen.getByRole("region", { name: "Scan progress" });
    expect(
      await within(card).findByText(/^Live connection interrupted\. Checking for updates automatically\./, {}, { timeout: 4000 }),
    ).toBeInTheDocument();
    expect(within(card).getByText(/^Last updated \d+ seconds? ago\.$/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry connection" })).toBeNull(); // no panel
    expect(screen.queryByText("Updates have stopped")).toBeNull();
    expect(row("Checking the router")).toHaveTextContent("Running"); // the real states stay
  });

  it("goes to the completion state when a poll shows the check has finished", async () => {
    const { socket, onComplete } = setup({ poll: DONE_WITH_RESULT(RESULT) });
    act(() => socket.send(MIDWAY));
    act(() => socket.drop());
    expect(await screen.findByRole("heading", { level: 2, name: "Check complete" }, { timeout: 4000 })).toBeInTheDocument();
    expect(onComplete).toHaveBeenCalledWith(RESULT);
  });
});

describe("Scanning screen: completion", () => {
  it("says it's complete with a summary from the real result, and waits for you", async () => {
    const user = userEvent.setup();
    const { socket, onComplete, onShowResults } = setup();
    act(() => socket.send(MIDWAY));
    act(() => socket.send(FINISHED));
    const heading = await screen.findByRole("heading", { level: 2, name: "Check complete" });
    expect(heading).toHaveFocus();
    expect(await screen.findByText("3 devices · 1 high, 3 medium findings")).toHaveAttribute("aria-live", "polite");
    expect(onComplete).toHaveBeenCalledWith(RESULT);
    expect(onShowResults).not.toHaveBeenCalled(); // no jumping to another page
    await user.click(screen.getByRole("button", { name: "See your results" }));
    expect(onShowResults).toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Cancel check" })).toBeNull();
  });
});

describe("Scanning screen: cancel", () => {
  it("is a button beside the stay-connected line, and asks first", async () => {
    const user = userEvent.setup();
    const { socket, calls } = setup();
    act(() => socket.send(MIDWAY));
    const cancel = screen.getByRole("button", { name: "Cancel check" });
    expect(cancel.parentElement).toHaveTextContent("Stay connected to this Wi-Fi and keep your laptop in the room.");
    cancel.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("button", { name: "Keep checking" })).toHaveFocus();
    // It says plainly that nothing from a cancelled check is kept.
    expect(document.body).toHaveTextContent("Nothing from a cancelled check is kept: no devices, findings or results.");
    await user.keyboard("{Enter}");
    expect(screen.getByRole("button", { name: "Cancel check" })).toHaveFocus();
    await user.keyboard("{Enter}");
    await user.tab();
    await user.keyboard("{Enter}");
    expect(await screen.findByRole("heading", { level: 1, name: "Check cancelled" })).toBeInTheDocument();
    expect(screen.getByText(/^Nothing from this check was kept\./)).toBeInTheDocument();
    expect(calls).toContain("POST /api/scans/job1/cancel");
  });
});

describe("Scanning screen: stopping and preparing (B6, B7)", () => {
  it("says Stopping… after a cancel until the check has really stopped, then offers Start again", () => {
    const { socket } = setup();
    act(() => socket.send(MIDWAY));
    act(() => socket.send({ ...CANCELLED, version: MIDWAY.version + 1, stopping: true }));
    expect(screen.getByRole("heading", { level: 1, name: "Stopping…" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Start again" })).toBeNull();
    // The live connection stays open while it stops, so the next update still arrives.
    act(() => socket.send({ ...CANCELLED, version: MIDWAY.version + 2, stopping: false }));
    expect(screen.getByRole("heading", { level: 1, name: "Check cancelled" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start again" })).toBeInTheDocument();
  });

  it("says Finishing the previous check… while the scanner is made ready", () => {
    const { socket } = setup();
    act(() => socket.send({ ...STARTING, preparing: true }));
    expect(task()).toHaveTextContent("Finishing the previous check…");
    act(() => socket.send({ ...STARTING, version: STARTING.version + 1, preparing: false }));
    expect(task()).not.toHaveTextContent("Finishing the previous check…");
  });
});
