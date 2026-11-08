// Final polish: help and disclosure sections never lose work (selections and typed text).
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { App } from "../App";
import { withBackend } from "../test/backend";
import { RESULT } from "../test/fixtures";
import { Handover } from "./Handover";
import { Report } from "./Report";

describe("Help never loses work", () => {
  it("Start: opening and closing What counts?, and Help from the footer, keeps the answer chosen", async () => {
    withBackend(<App />);
    const no = await screen.findByRole("radio", { name: "No, or I'm not sure" });
    await userEvent.click(no);
    const counts = screen.getByRole("button", { name: "What counts?" });
    await userEvent.click(counts);
    await userEvent.click(counts);
    expect(no).toBeChecked();
    // The footer's link opens Help with "What it can't see" open and focused; the browser's
    // Back (Help has no Back button from Start) keeps the answer.
    await userEvent.click(screen.getByRole("button", { name: "What it can't see" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Help" })).toBeInTheDocument();
    const row = screen.getByRole("heading", { level: 3, name: "What it can't see" }).closest("details")!;
    expect(row).toHaveAttribute("open");
    await waitFor(() => expect(row.querySelector("summary")).toHaveFocus());
    expect(screen.queryByRole("button", { name: "Back to the start" })).toBeNull();
    await act(async () => window.history.back());
    await screen.findByRole("radio", { name: "No, or I'm not sure" });
    expect(screen.getByRole("radio", { name: "No, or I'm not sure" })).toBeChecked();
    expect(screen.getByRole("button", { name: "Start listening-only check" })).toHaveAttribute("aria-disabled", "false");
  });

  it("Start: going to Help and back (the browser's Back) keeps the answer, and focus returns to Help's button", async () => {
    withBackend(<App />);
    await userEvent.click(await screen.findByRole("radio", { name: "Yes, I have permission" }));
    await userEvent.click(within(screen.getByRole("banner")).getByRole("button", { name: "Help" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Help" })).toBeInTheDocument();
    await act(async () => window.history.back());
    expect(await screen.findByRole("radio", { name: "Yes, I have permission" })).toBeChecked();
    // As with every Back: focus returns to the control that opened Help.
    await waitFor(() => expect(within(screen.getByRole("banner")).getByRole("button", { name: "Help" })).toHaveFocus());
  });

  it("Handover: closing the message or a card keeps what you typed", async () => {
    withBackend(<Handover />);
    const draft = (await screen.findByText("Draft message to host")).closest("summary")!;
    await userEvent.click(draft);
    const box = screen.getByRole("textbox", { name: "Message" });
    await userEvent.type(box, " Many thanks.");
    await userEvent.click(draft);
    await userEvent.click(draft);
    expect((screen.getByRole("textbox", { name: "Message" }) as HTMLTextAreaElement).value).toMatch(/Many thanks\.$/);
    // And the task choices.
    const wps = screen.getByRole("checkbox", { name: "Ask for WPS to be turned off on the router" });
    await userEvent.click(wps);
    await userEvent.click(draft);
    await userEvent.click(draft);
    expect(screen.getByRole("checkbox", { name: "Ask for WPS to be turned off on the router" })).not.toBeChecked();
  });

  it("Report: the typed label and every choice stay while you read the hints", async () => {
    withBackend(<Report result={RESULT} onOpenHandover={() => {}} />, { "GET /api/report/defaults": { room_label: null } });
    const label = screen.getByRole("textbox", { name: "Room name (optional)" });
    await userEvent.type(label, "Room 7");
    await userEvent.click(screen.getByRole("checkbox", { name: "Handover notes" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Trusted timestamp" }));
    // Focusing each hint-bearing control (where the hints are read) changes nothing.
    for (const name of ["Network name", "Device names"]) screen.getByRole("checkbox", { name }).focus();
    expect(label).toHaveValue("Room 7");
    expect(screen.getByRole("checkbox", { name: "Handover notes" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Trusted timestamp" })).not.toBeChecked();
  });
});
