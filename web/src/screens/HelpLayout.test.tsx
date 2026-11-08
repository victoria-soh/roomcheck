// Help, reorganised: one column of four cards, jump links, collapsed rows that links open, the
// outside calls as a table with an AI on/off tag, and one "Your data" card.
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import en from "../strings/en.json";
import { withBackend } from "../test/backend";
import { SETUP_NO_AI } from "../test/fixtures";
import { Help } from "./Help";

const CARDS = ["If you find a hidden camera", "How RoomCheck works", "What's sent", "Your data"];

describe("Help layout", () => {
  it("title, one line, jump links, then the four cards in order", () => {
    withBackend(<Help />);
    expect(screen.getByRole("heading", { level: 1, name: "Help" })).toBeInTheDocument();
    expect(screen.getByText("Quick answers about RoomCheck.")).toBeInTheDocument();
    const jumps = within(screen.getByRole("navigation", { name: "On this page" })).getAllByRole("link");
    expect(jumps.map((a) => a.textContent)).toEqual(["Found a hidden camera?", "How it works", "What's sent", "Your data"]);
    expect(jumps.map((a) => a.getAttribute("href"))).toEqual(["#help-camera", "#help-how", "#help-online", "#help-data"]);
    expect(screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent)).toEqual(CARDS);
    expect(screen.queryByRole("button", { name: /^Back to/ })).toBeNull();
  });

  it("a jump link focuses its card's heading", async () => {
    withBackend(<Help />);
    await userEvent.click(screen.getByRole("link", { name: "Your data" }));
    expect(screen.getByRole("heading", { level: 2, name: "Your data" })).toHaveFocus();
  });

  it("the camera card: three steps and one small note, with a warning edge", () => {
    withBackend(<Help />);
    const card = screen.getByRole("region", { name: "If you find a hidden camera" });
    expect(card).toHaveClass("border-l-sev-medium");
    expect(within(card).getAllByRole("listitem").map((li) => li.textContent)).toEqual([
      "Don't touch or unplug it. Photograph it where it is.",
      "Leave if you feel unsafe.",
      "Report it to the police, and to whoever runs the place: the platform, the host or landlord's agent, or the management.",
    ]);
    expect(card).toHaveTextContent(
      "Many platforms don't allow indoor cameras; Airbnb hasn't since 2024. Laws differ by country. This isn't legal advice.",
    );
  });

  it("How RoomCheck works: four collapsed rows that open", async () => {
    withBackend(<Help />);
    const card = screen.getByRole("region", { name: "How RoomCheck works" });
    const rows = [...card.querySelectorAll("details")];
    expect(rows.map((d) => d.querySelector("summary")!.textContent)).toEqual([
      "What it checks",
      "What it can't see",
      "How priorities are set",
      "What counts as permission",
    ]);
    expect(rows.every((d) => !d.open)).toBe(true);
    await userEvent.click(within(card).getByText("How priorities are set"));
    expect(rows[2]).toHaveAttribute("open");
    expect(rows[2]).toHaveTextContent("The AI only words the explanations. It never sets or changes a priority.");
    await userEvent.click(within(card).getByText("What counts as permission"));
    expect(rows[3]).toHaveTextContent(en.start.permission.legal);
  });

  it.each([
    ["help-priority", "How priorities are set"],
    ["help-cant", "What it can't see"],
  ])("a link to %s lands on its row, open and focused", async (section, title) => {
    withBackend(<Help section={section} />);
    const row = screen.getByText(title, { selector: "h3" }).closest("details")!;
    expect(row).toHaveAttribute("open");
    await waitFor(() => expect(row.querySelector("summary")).toHaveFocus());
    // Only that row is open.
    expect([...document.querySelectorAll("details[open]")]).toEqual([row]);
  });

  it.each([
    ["help-online", "What's sent"],
    ["help-delete", "Delete your data"],
  ])("a link to %s lands on its heading", async (section, name) => {
    withBackend(<Help section={section} />);
    await waitFor(() => expect(screen.getByRole("heading", { name })).toHaveFocus());
  });

  it("What's sent: the AI tag, the intro, a three-row table and the network-name note", async () => {
    withBackend(<Help />);
    const card = screen.getByRole("region", { name: "What's sent" });
    expect(await within(card).findByText("AI is on in this setup")).toBeInTheDocument();
    expect(card).toHaveTextContent("Everything runs on this laptop. Only these optional calls go out:");
    const rows = within(within(card).getByRole("table")).getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getByRole("rowheader").textContent)).toEqual([
      "AI explanations",
      "Known-issue lookups",
      "Trusted timestamps",
    ]);
    expect(card).toHaveTextContent("The network name on Start is shown on this laptop only and is never sent anywhere.");
  });

  it("the AI tag follows this setup", async () => {
    withBackend(<Help />, { "GET /api/setup": SETUP_NO_AI });
    expect(await screen.findByText("AI is off in this setup")).toBeInTheDocument();
  });
});
