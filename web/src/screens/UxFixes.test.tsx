// Six UX fixes: phone navigation, the summary's actions, page-scoped counts, browser history,
// the cards' three labelled parts and the move-in scan wording.
import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { App } from "../App";
import type { CoverageItem, DiscoveryResult } from "../api/types";
import { AppHeader, type Page } from "../ds/AppHeader";
import { parseHash, routeHash } from "../route";
import { recoveryStep } from "../results/summary";
import en from "../strings/en.json";
import { withBackend } from "../test/backend";
import { BASELINE_NONE, DONE_WITH_RESULT, HANDOVER, RESULT } from "../test/fixtures";
import { Handover } from "./Handover";
import { Results } from "./Results";

function phone(on: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: on && query.includes("max-width"),
    media: query,
    addEventListener() {},
    removeEventListener() {},
  }));
}

function header(current: Page = "results", onNavigate = vi.fn()) {
  withBackend(
    <AppHeader
      stage="results"
      current={current}
      onNavigate={onNavigate}
      hasResults
      baselineSaved={false}
      openTasks={2}
      onNewCheck={() => {}}
      onSaveBaseline={async () => {}}
    />,
  );
  return onNavigate;
}

describe("1. Phone navigation", () => {
  it("on a phone: Results, Nearby and Handover as tabs, the rest in a More menu", () => {
    phone(true);
    header();
    const nav = screen.getByRole("navigation", { name: "Main" });
    const tabs = within(nav).getAllByRole("button").map((b) => b.textContent);
    expect(tabs).toEqual(["Results", "Nearby", "Handover· 2, 2 open tasks", "More"]);
    expect(within(nav).getByRole("button", { name: "More" })).toHaveAttribute("aria-expanded", "false");
    expect(within(nav).queryByRole("button", { name: "Compare" })).toBeNull();
  });

  it("More opens a list, Escape closes it and returns focus, and a page can be chosen", async () => {
    phone(true);
    const onNavigate = header();
    const user = userEvent.setup();
    const more = screen.getByRole("button", { name: "More" });
    more.focus();
    await user.keyboard("{Enter}");
    expect(more).toHaveAttribute("aria-expanded", "true");
    const list = screen.getByRole("list", { name: "More pages" });
    expect(more).toHaveAttribute("aria-controls", list.id);
    expect(within(list).getAllByRole("button").map((b) => b.textContent)).toEqual(["Compare", "Report", "Verify a report"]);
    expect(within(list).getByRole("button", { name: "Compare" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("list", { name: "More pages" })).toBeNull();
    expect(more).toHaveFocus();
    expect(more).toHaveAttribute("aria-expanded", "false");
    await user.click(more);
    await user.click(screen.getByRole("button", { name: "Report" }));
    expect(onNavigate).toHaveBeenCalledWith("report");
    expect(screen.queryByRole("list", { name: "More pages" })).toBeNull();
  });

  it("a click outside closes the menu", async () => {
    phone(true);
    header();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "More" }));
    expect(screen.getByRole("list", { name: "More pages" })).toBeInTheDocument();
    await user.click(document.body);
    expect(screen.queryByRole("list", { name: "More pages" })).toBeNull();
  });

  it("while a More page is open, More is marked like a current tab and the page as current", async () => {
    phone(true);
    header("report");
    const more = screen.getByRole("button", { name: "More" });
    expect(more.className).toContain("border-accent");
    await userEvent.click(more);
    expect(screen.getByRole("button", { name: "Report" })).toHaveAttribute("aria-current", "page");
  });

  it("on a laptop, the navigation is unchanged: every page is a tab, no More", () => {
    phone(false);
    header();
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).queryByRole("button", { name: "More" })).toBeNull();
    for (const name of ["Results", "Nearby", "Compare", "Report", "Verify a report"]) {
      expect(within(nav).getByRole("button", { name })).toBeInTheDocument();
    }
  });

  it("Handover has a Create report link", async () => {
    const onOpenReport = vi.fn();
    withBackend(<Handover onOpenReport={onOpenReport} />, { "GET /api/handover": HANDOVER });
    await userEvent.click(await screen.findByRole("button", { name: "Create report" }));
    expect(onOpenReport).toHaveBeenCalled();
  });
});

function results(result: DiscoveryResult = RESULT) {
  const handlers = { onOpenNearby: vi.fn(), onOpenCompare: vi.fn(), onOpenHandover: vi.fn() };
  withBackend(<Results result={result} {...handlers} />, { "GET /api/baseline": BASELINE_NONE });
  return handlers;
}
const banner = () => screen.getByRole("region", { name: /to look at$|^Not detected/ });

describe("2. The summary's actions", () => {
  it("names what the main button opens, from the top finding's rule, and opens that card", async () => {
    results();
    const b = banner();
    await userEvent.click(within(b).getByRole("button", { name: "Review camera-like device" }));
    await waitFor(() => expect(screen.getByRole("article", { name: /^Likely camera/ })).toHaveFocus());
    // One way in from the summary; the questions below hold the rest.
    expect(within(b).getAllByRole("button").filter((el) => /^Review/.test(el.textContent ?? ""))).toHaveLength(1);
  });

  it("a partial check shows the one recovery step for its actual reason, saying next time once", () => {
    const listening: DiscoveryResult = {
      ...RESULT,
      coverage: (RESULT.coverage ?? []).map((r) => (r.area === "router" ? { ...r, reason_code: "passive_mode" } : r)),
    };
    results(listening);
    expect(banner()).toHaveTextContent(
      "To check more next time: If you have permission, answer “Yes” on the Start screen to also check device services",
    );
    expect(banner().textContent!.match(/next time/g)).toHaveLength(1);
  });

  it("no recovery step for a reason without a fix (the demo's DHCP and lookup reasons)", () => {
    results();
    expect(banner()).not.toHaveTextContent("To check more next time");
  });

  it("the step comes from a fixed mapping, most useful first, and only for reasons with a fix", () => {
    const row = (reason_code: string | null, state: CoverageItem["state"] = "limited"): CoverageItem => ({
      area: "x",
      label: "x",
      state,
      reason: "x",
      reason_code,
    });
    expect(recoveryStep([row("bluetooth_off", "not_run"), row("location_off")])).toBe("results.recover.location_off");
    expect(recoveryStep([row("passive_mode"), row("bluetooth_off")])).toBe("results.recover.bluetooth_off");
    expect(recoveryStep([row("timeout"), row("internal"), row(null)])).toBeNull();
    expect(recoveryStep([row("location_off", "completed")])).toBeNull();
    expect(en.results.recover.location_off).toBe("Turn on Windows Location to include nearby Wi-Fi");
    expect(en.results.recover.bluetooth_off).toBe("Turn on Bluetooth to include nearby devices");
  });
});

describe("3. One count across the questions", () => {
  it("the headline counts things to look at across every question, nearby signals included", () => {
    results();
    expect(within(banner()).getByRole("heading", { level: 2 })).toHaveTextContent(/^5 things to look at$/);
    // No chips and no separate Nearby chip: nearby signals sit under their question.
    expect(screen.queryByRole("button", { name: /Nearby signals/ })).toBeNull();
    expect(screen.getByRole("region", { name: "Is anything watching?" })).toHaveTextContent("Item tracker nearby");
  });

  it("a nearby card offers Nearby for the locator", async () => {
    const { onOpenNearby } = results();
    const tracker = screen.getByRole("article", { name: /^Item tracker nearby/ });
    await userEvent.click(within(tracker).getByRole("button", { name: "Find it on Nearby" }));
    expect(onOpenNearby).toHaveBeenCalled();
  });
});

describe("4. Browser history", () => {
  it("routes round-trip through the address", () => {
    for (const r of [{ name: "results" }, { name: "help" }, { name: "locator", ref: "wifi:abc" }] as const) {
      expect(parseHash(routeHash(r))).toEqual(r);
    }
    expect(parseHash("#/nowhere")).toEqual({ name: "start" });
    expect(parseHash("")).toEqual({ name: "start" });
  });

  it("a refresh on Results gets the check back from the server and stays there", async () => {
    sessionStorage.setItem("roomcheck.check", JSON.stringify({ id: "job1", consent: false }));
    window.history.replaceState(null, "", "/#/results");
    withBackend(<App />, { "GET /api/scans/job1": DONE_WITH_RESULT(RESULT) });
    expect(await screen.findByRole("heading", { level: 1, name: "Results" })).toBeInTheDocument();
    expect(window.location.hash).toBe("#/results");
  });

  it("a refresh where the check is gone goes to Start and says why", async () => {
    window.history.replaceState(null, "", "/#/nearby");
    withBackend(<App />);
    expect(await screen.findByText("That page needs a check that isn't available any more")).toBeInTheDocument();
    expect(window.location.hash).toBe("#/start");
  });

  it("Back returns to the previous screen and focus to the control that left it", async () => {
    sessionStorage.setItem("roomcheck.check", JSON.stringify({ id: "job1", consent: false }));
    window.history.replaceState(null, "", "/#/results");
    withBackend(<App />, { "GET /api/scans/job1": DONE_WITH_RESULT(RESULT) });
    await screen.findByRole("heading", { level: 1, name: "Results" });
    const nearbyTab = screen.getByRole("button", { name: "Nearby" });
    nearbyTab.focus();
    await userEvent.click(nearbyTab);
    expect(await screen.findByRole("heading", { level: 1, name: /Nearby/ })).toBeInTheDocument();
    expect(window.location.hash).toBe("#/nearby");
    await act(async () => {
      window.history.back();
      await new Promise((r) => window.setTimeout(r, 50));
    });
    expect(await screen.findByRole("heading", { level: 1, name: "Results" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Nearby" })).toHaveFocus());
    await act(async () => {
      window.history.forward();
      await new Promise((r) => window.setTimeout(r, 50));
    });
    expect(await screen.findByRole("heading", { level: 1, name: /Nearby/ })).toBeInTheDocument();
  });
});

describe("5. The cards' three labelled parts", () => {
  it("each flagged device and network card has What we observed, What it could mean, What you can do", () => {
    results();
    for (const card of screen.getAllByRole("article")) {
      const parts = within(card).getAllByRole("heading", { level: 4 }).map((h) => h.textContent);
      expect(parts.slice(0, 3)).toEqual(["What we observed", "What it could mean", "What you can do"]);
      // Evidence and details stays collapsed below them.
      const details = within(card).getByText("Evidence and details").closest("details")!;
      expect(details).not.toHaveAttribute("open");
    }
    const cam = screen.getByRole("article", { name: /^Likely camera/ });
    const meaning = within(cam).getByRole("group", { name: "What it could mean" });
    // The rule's fixed risk sentence; the AI's explanation is under Evidence and details.
    expect(meaning).toHaveTextContent(RESULT.findings[0]!.could_mean!);
    // The specific clues, one fixed sentence each, instead of the rule's general sentence.
    const observed = within(cam).getByRole("group", { name: "What we observed" });
    for (const clue of RESULT.findings[0]!.clues!) expect(observed).toHaveTextContent(clue);
    const action = within(cam).getByRole("group", { name: "What you can do" });
    expect(action).toHaveTextContent(RESULT.findings[0]!.next_step);
  });
});

describe("6. Move-in scan wording", () => {
  it("before saving: Save as my move-in scan, with one sentence of what it's for", async () => {
    results();
    const card = await screen.findByRole("region", { name: "Move-in scan" });
    expect(card).toHaveTextContent("Save this check so RoomCheck can show you anything new that appears later.");
    expect(within(card).getByRole("button", { name: "Save as my move-in scan" })).toBeInTheDocument();
  });

  it("no user-facing text uses the bare word baseline", () => {
    const values: string[] = [];
    const walk = (v: unknown) => {
      if (typeof v === "string") values.push(v);
      else if (v && typeof v === "object") Object.values(v).forEach(walk);
    };
    walk(en);
    expect(values.filter((v) => /\bbaseline\b/i.test(v))).toEqual([]);
  });
});
