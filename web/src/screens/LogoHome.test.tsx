// The header logo goes to Start, and Start links back to the latest results when there are some.
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { App } from "../App";
import { withBackend } from "../test/backend";
import { Start } from "./Start";

describe("Header logo", () => {
  it("is one link to #/, named RoomCheck, go to start", async () => {
    withBackend(<App />);
    const link = within(await screen.findByRole("banner")).getByRole("link", { name: "RoomCheck, go to start" });
    expect(link).toHaveAttribute("href", "#/");
    expect(link).toHaveTextContent("RoomCheck");
    expect(link.querySelector("svg[data-logo='mark']")).not.toBeNull();
  });

  it("from Help, goes back to Start", async () => {
    withBackend(<App />);
    const banner = await screen.findByRole("banner");
    await userEvent.click(within(banner).getByRole("button", { name: "Help" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Help" })).toBeInTheDocument();
    await userEvent.click(within(banner).getByRole("link", { name: "RoomCheck, go to start" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Check your room's Wi-Fi and devices" })).toBeVisible();
    expect(window.location.hash).toBe("#/start");
  });
});

describe("Start: the latest results", () => {
  it("a small link under the connection bar when there are results", async () => {
    const onView = vi.fn();
    withBackend(<Start onStart={vi.fn()} latest={{ when: "3 Nov 2026, 13:24", onView }} />);
    const link = screen.getByRole("button", { name: "View your latest results (3 Nov 2026, 13:24)" });
    const bar = screen.getByRole("region", { name: "Is this laptop ready?" });
    expect(bar.compareDocumentPosition(link) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await userEvent.click(link);
    expect(onView).toHaveBeenCalled();
  });

  it("nothing when there are none", () => {
    withBackend(<Start onStart={vi.fn()} />);
    expect(screen.queryByText(/View your latest results/)).toBeNull();
  });
});
