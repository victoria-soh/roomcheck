// Demo mode (`python -m app --demo`): Start says so, and every page's header has a "Demo data" tag.
import { screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { App } from "../App";
import { withBackend } from "../test/backend";
import { Start } from "./Start";

const HEALTH = { ok: true, scanner: false, version: "test", code_time: null, dashboard_built: null, stale: false };

describe("Demo mode", () => {
  it("Start shows the demo banner", () => {
    withBackend(<Start onStart={vi.fn()} demo />);
    const note = screen.getByRole("note", { name: "Demo mode: made-up data, nothing is scanned" });
    expect(note).toHaveTextContent("Nothing on your network is checked, and nothing is sent anywhere.");
  });

  it("no banner and no tag in a real run", async () => {
    withBackend(<App />, { "GET /api/health": HEALTH });
    await screen.findByRole("banner");
    expect(screen.queryByText("Demo data")).toBeNull();
    expect(screen.queryByRole("note", { name: /Demo mode/ })).toBeNull();
  });

  it("the header says Demo data, and Start shows the banner", async () => {
    withBackend(<App />, { "GET /api/health": { ...HEALTH, demo: true } });
    const banner = await screen.findByRole("banner");
    expect(await within(banner).findByText("Demo data")).toBeVisible();
    expect(await screen.findByRole("note", { name: "Demo mode: made-up data, nothing is scanned" })).toBeVisible();
  });
});
