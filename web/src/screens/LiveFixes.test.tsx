// Fixes for bugs found in the live tests of 4 Nov 2026 (docs/bugs-from-live-tests.md).
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { DeleteAllData } from "../components/DeleteAllData";
import { withBackend } from "../test/backend";
import { HANDOVER, REPORT, RESULT } from "../test/fixtures";
import { Report } from "./Report";

const UNAVAILABLE = {
  ...REPORT,
  tsr: null,
  timestamped_at: null,
  timestamp_message: "Couldn't get a trusted timestamp: this laptop isn't connected to a network.",
  timestamp: { state: "unavailable", reason: "Couldn't get a trusted timestamp: this laptop isn't connected to a network." },
};

describe("B12: deleting all saved data clears the room label on an open Report page", () => {
  it("the label offered from the last report goes, with its hint", async () => {
    const user = userEvent.setup();
    let saved: string | null = "Room 4B";
    withBackend(
      <>
        <Report result={RESULT} onOpenHandover={() => {}} />
        <DeleteAllData />
      </>,
      {
        "GET /api/report/defaults": () => ({ room_label: saved }),
        "DELETE /api/data": () => {
          saved = null;
          return { baseline: { state: "none", saved_at: null, devices: 0, nearby: 0, message: null }, handover: { ...HANDOVER, tasks: [] } };
        },
      },
    );
    const label = await screen.findByRole("textbox", { name: /Room name/ });
    await waitFor(() => expect(label).toHaveValue("Room 4B"));
    expect(screen.getByText(/Filled in from your last report/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Delete all saved RoomCheck data" }));
    await user.click(screen.getByRole("button", { name: "Yes, delete all of it" }));
    await waitFor(() => expect(label).toHaveValue(""));
    expect(screen.queryByText(/Filled in from your last report/)).toBeNull();
  });
});

describe("B9 and B8: the report says what really happened to the timestamp", () => {
  it("an unavailable timestamp shows its reason and Try again, which makes the report again", async () => {
    const user = userEvent.setup();
    let made = 0;
    const { calls } = withBackend(<Report result={RESULT} onOpenHandover={() => {}} />, {
      "GET /api/report/defaults": { room_label: "Room 4B" },
      "POST /api/report": () => (++made === 1 ? UNAVAILABLE : REPORT),
    });
    await user.click(await screen.findByRole("button", { name: "Create report" }));
    expect(await screen.findByText(/Unavailable: Couldn't get a trusted timestamp: this laptop isn't connected/)).toBeInTheDocument();
    // Worded for a report with no timestamp (B8).
    expect(screen.queryByText(/since it was timestamped/)).toBeNull();
    expect(screen.getByText(/Without a timestamp, nothing shows when this report was made/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await waitFor(() => expect(calls.filter((c) => c.url === "/api/report")).toHaveLength(2));
    // The same label and choices were sent again.
    const [first, second] = calls.filter((c) => c.url === "/api/report");
    expect(second!.body).toEqual(first!.body);
    expect(await screen.findByText(/since it was timestamped/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
  });
});
