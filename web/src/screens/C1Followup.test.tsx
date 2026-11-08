// C1 follow-up: Undo for statuses and answers, exact confirmations, the report's privacy
// choices, "Delete all saved RoomCheck data" (on Compare and Help), and the Nearby scope note.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { BaselineCard } from "../components/BaselineCard";
import { withBackend, type Call } from "../test/backend";
import { BASELINE_SAVED, COMPARE_READY, HANDOVER, RESULT } from "../test/fixtures";
import { Compare } from "./Compare";
import { Handover } from "./Handover";
import { Help } from "./Help";
import { Nearby } from "./Nearby";
import { Results } from "./Results";

const CAM_TASK = HANDOVER.tasks[0]!;
const CAM_SUBJECT = CAM_TASK.subject;

describe("Undo", () => {
  it("puts a task's status back, from the keyboard, and announces it", async () => {
    const { calls } = withBackend(<Handover />, {
      "PATCH /api/tasks/*": (call: Call) => ({
        ...HANDOVER,
        tasks: HANDOVER.tasks.map((t, i) => (i === 0 ? { ...t, ...(call.body as object) } : t)),
      }),
    });
    const cam = await screen.findByRole("article", { name: CAM_TASK.title });
    await userEvent.click(within(cam).getByRole("radio", { name: "Resolved" }));
    const note = await within(cam).findByText("Status changed to Resolved.");
    expect(note.closest("[aria-live]")).toHaveAttribute("aria-live", "polite");
    const undo = within(cam).getByRole("button", { name: "Undo" });
    undo.focus();
    await userEvent.keyboard("{Enter}");
    await waitFor(() => expect(within(cam).getByRole("radio", { name: "To do" })).toBeChecked());
    const patches = calls.filter((c) => c.method === "PATCH").map((c) => c.body);
    expect(patches).toEqual([{ status: "resolved" }, { status: "todo" }]);
    expect(within(cam).queryByRole("button", { name: "Undo" })).toBeNull();
  });

  it("puts a recognition answer back, even to no answer at all", async () => {
    const { calls } = withBackend(
      <Results result={RESULT} onOpenNearby={() => {}} onOpenCompare={() => {}} onOpenHandover={() => {}} />,
      {
        "POST /api/answers": (call: Call) => {
          const body = call.body as { answer: "mine" | null };
          return { ...HANDOVER, answers: body.answer ? { [CAM_SUBJECT]: body.answer } : {} };
        },
      },
    );
    const cam = screen.getByRole("article", { name: /^Likely camera/ });
    await userEvent.click(within(cam).getByRole("radio", { name: "Mine" }));
    expect(await within(cam).findByText("Answer changed to Mine.")).toBeInTheDocument();
    await userEvent.click(within(cam).getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(within(cam).getByRole("radio", { name: "Mine" })).not.toBeChecked());
    const posts = calls.filter((c) => c.url === "/api/answers").map((c) => c.body);
    expect(posts).toEqual([
      { subject: CAM_SUBJECT, answer: "mine", confirmed: null },
      { subject: CAM_SUBJECT, answer: null, confirmed: null },
    ]);
  });
});

describe("Confirmations say exactly what will be lost", () => {
  it("replacing the move-in scan", async () => {
    withBackend(<BaselineCard onOpenCompare={() => {}} />, { "GET /api/baseline": BASELINE_SAVED });
    await userEvent.click(await screen.findByRole("button", { name: "Replace it with this check" }));
    const question = screen.getByText(/^Replace your move-in scan from .*2026/);
    expect(question).toHaveTextContent(
      `The saved scan's ${BASELINE_SAVED.devices} devices and ${BASELINE_SAVED.nearby} nearby items will be replaced`,
    );
    expect(question).toHaveTextContent("The old scan can't be recovered. Your handover tasks, notes and answers stay.");
  });

  it("deleting the move-in scan (in Help)", async () => {
    withBackend(<Help />, { "GET /api/baseline": BASELINE_SAVED });
    await userEvent.click(await screen.findByRole("button", { name: "Delete move-in scan" }));
    const question = screen.getByText(/^Delete your move-in scan from .*2026/);
    expect(question).toHaveTextContent("Compare will have nothing to compare with");
    expect(question).toHaveTextContent("Your handover tasks, notes and answers stay saved.");
  });
});

describe("Delete all saved RoomCheck data", () => {
  const QUESTION = /^Delete all saved RoomCheck data from this laptop\?/;

  it("Compare links to it in Help instead of offering the delete buttons itself", async () => {
    const onOpenHelp = vi.fn();
    withBackend(<Compare result={RESULT} onOpenHelp={onOpenHelp} />, { "GET /api/compare": COMPARE_READY });
    await userEvent.click(await screen.findByRole("button", { name: "Manage saved data" }));
    expect(onOpenHelp).toHaveBeenCalledWith("help-delete");
    expect(screen.queryByRole("button", { name: "Delete move-in scan" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete all saved RoomCheck data" })).toBeNull();
  });

  it("is in Help, next to Delete move-in scan, and says exactly what goes and what stays", async () => {
    const { calls } = withBackend(<Help />, {
      "GET /api/baseline": BASELINE_SAVED,
      "DELETE /api/data": { baseline: { state: "none", saved_at: null, devices: 0, nearby: 0, message: null }, handover: { ...HANDOVER, tasks: [] } },
    });
    const button = await screen.findByRole("button", { name: "Delete all saved RoomCheck data" });
    await userEvent.click(button);
    const q = screen.getByText(QUESTION);
    for (const part of [
      "your move-in scan",
      "your handover tasks with their statuses and notes",
      "your answers to “Do you recognise this device?”",
      "the names and notes you gave devices",
      "the key used to match devices between checks",
      "Reports you've already saved as files aren't affected.",
    ]) {
      expect(q).toHaveTextContent(part);
    }
    expect(screen.getByRole("button", { name: "Keep my data" })).toHaveFocus(); // the safe choice
    await userEvent.click(screen.getByRole("button", { name: "Yes, delete all of it" }));
    expect(await screen.findByText(/All saved RoomCheck data was deleted from this laptop/)).toBeInTheDocument();
    expect(calls.some((c) => c.method === "DELETE" && c.url === "/api/data")).toBe(true);
  });

  it("is on the Help page too, with what's kept and where", async () => {
    withBackend(<Help />);
    expect(screen.getByRole("heading", { level: 1, name: "Help" })).toBeInTheDocument();
    // One "Your data" card: what's saved and where, the reports, and the delete button.
    const data = screen.getByRole("region", { name: "Your data" });
    expect(data).toHaveTextContent("%LOCALAPPDATA%\\RoomCheck, encrypted for your Windows account. Nothing is sent anywhere.");
    expect(data).toHaveTextContent("Deleting your data doesn't remove them");
    const del = within(data);
    await userEvent.click(del.getByRole("button", { name: "Delete all saved RoomCheck data" }));
    expect(screen.getByText(QUESTION)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Keep my data" }));
    expect(screen.queryByText(QUESTION)).toBeNull();
  });
});

describe("Nearby scope note", () => {
  it("says some signals may come from neighbouring rooms or buildings", () => {
    withBackend(<Nearby result={RESULT} onFind={() => {}} />);
    expect(screen.getByText("Some signals may come from neighbouring rooms or buildings.")).toBeInTheDocument();
  });
});
