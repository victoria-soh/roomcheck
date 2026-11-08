// Mocked backend for the browser tests: REST routes and the progress WebSocket, from made-up
// data only. Also records anything the page tries to load from another origin, and CSP errors.
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page, type WebSocketRoute } from "@playwright/test";

import type { BaselineInfo, CompareItem, CompareResponse, DiscoveryResult, HandoverState, ScanSnapshot, Setup } from "../src/api/types";
import {
  BASELINE_NONE,
  CANCELLED,
  COMPARE_NONE,
  DONE_WITH_RESULT,
  HANDOVER,
  handoverFor,
  HANDOVER_CAMERA_MINE,
  REPORT,
  SETUP_READY,
  VERIFIED,
} from "../src/test/fixtures";

// Each check gets its own id, as with the real backend: job1, job2, ...
export const JOB_ID = "job1";
// A little longer than the 150 ms colour transitions (tokens.css).
export const TRANSITION_MS = 200;

export interface Mocked {
  socket: () => Promise<WebSocketRoute>;
  /** Send live snapshots over the current WebSocket. */
  send: (snapshots: ScanSnapshot[]) => Promise<void>;
  /** Close the WebSocket without a final state, as a dropped connection does. */
  drop: () => Promise<void>;
  /** What GET /api/scans/{id} answers while polling: a snapshot, or a server error. */
  setPoll: (answer: ScanSnapshot | "fail") => void;
  /** How many WebSocket connections the page has opened. */
  connections: () => number;
  outside: string[];
  cspErrors: string[];
  /** Every red console error, e.g. a missing file or a refused connection. */
  consoleErrors: string[];
  scanBodies: unknown[];
  cancels: () => number;
  /** The locator's WebSocket: push readings, and see whether the page closed it. */
  locator: () => Promise<WebSocketRoute>;
  pushReadings: (readings: object[]) => Promise<void>;
  locatorClosed: () => boolean;
  /** What POST /api/verify answers. */
  setVerify: (answer: object) => void;
  verifyCalls: () => number;
  /** Layer 6: what the handover, baseline and compare routes answer, and what was sent. */
  setBaseline: (info: BaselineInfo) => void;
  setCompare: (answer: CompareResponse) => void;
  layer6Calls: { method: string; url: string; body: unknown }[];
  /** What GET /api/setup answers (the Start screen's readiness strip). */
  setSetup: (answer: Setup) => void;
  /** Delay GET /api/setup, so "Checking…" can be seen. */
  setSetupDelay: (ms: number) => void;
  /** Every URL the page requested and every body it sent, to check what leaves the page. */
  sent: () => string[];
}

/** The Start button's label once an answer is chosen. */
export const START_BUTTON = /^Start (full check|listening-only check|check \(some parts limited\))$/;

/** A tiny made-up PDF, for routes that serve report files. */
export const MADE_UP_PDF = Buffer.from(
  "%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj " +
    "3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF",
);

export async function mockBackend(
  page: Page,
  result: DiscoveryResult,
  options: { pdf?: Buffer; report?: object; handover?: HandoverState } = {},
): Promise<Mocked> {
  const outside: string[] = [];
  const cspErrors: string[] = [];
  const consoleErrors: string[] = [];
  const scanBodies: unknown[] = [];
  let jobs = 0;
  const origin = "http://127.0.0.1:4173";
  let poll: ScanSnapshot | "fail" = DONE_WITH_RESULT(result);
  let cancels = 0;

  const sent: string[] = [];
  page.on("request", (r) => {
    sent.push(r.url(), r.postData() ?? "");
    if (!r.url().startsWith(origin) && !r.url().startsWith("ws://127.0.0.1:4173")) outside.push(r.url());
  });
  page.on("console", (m) => {
    if (/Content.Security.Policy/i.test(m.text())) cspErrors.push(m.text());
    if (m.type() === "error") consoleErrors.push(m.text());
  });

  // Anything not mocked below fails here, so a test never reaches a real RoomCheck on this
  // laptop through the preview server's proxy. (Later routes take priority over this one.)
  await page.route("**/api/**", (route) => route.fulfill({ status: 404, json: { detail: "not mocked" } }));
  await page.route("**/api/health", (route) =>
    route.fulfill({
      json: { ok: true, version: "0.1.0", code_time: null, dashboard_built: null, stale: false },
    }),
  );
  await page.route("**/api/scans", async (route) => {
    scanBodies.push(route.request().postDataJSON());
    jobs += 1;
    await route.fulfill({ status: 202, json: { id: `job${jobs}` } });
  });
  await page.route(/\/api\/scans\/job\d+$/, (route) =>
    poll === "fail" ? route.fulfill({ status: 503, json: {} }) : route.fulfill({ json: poll }),
  );
  await page.route(/\/api\/scans\/job\d+\/cancel$/, (route) => {
    cancels += 1;
    return route.fulfill({ json: CANCELLED });
  });

  let verify: object = VERIFIED;
  let verifyCalls = 0;
  // The last room label used is offered next time, like the real backend.
  let roomLabel: string | null = null;
  await page.route("**/api/report", (route) => {
    const body = route.request().postDataJSON() as { room_label?: string | null } | null;
    if (body?.room_label) roomLabel = body.room_label;
    return route.fulfill({ json: options.report ?? REPORT });
  });
  await page.route("**/api/report/defaults", (route) => route.fulfill({ json: { room_label: roomLabel } }));
  await page.route("**/api/report/files/*", (route) => {
    const pdf = route.request().url().split("?")[0]!.endsWith(".pdf");
    return route.fulfill({
      body: pdf ? (options.pdf ?? MADE_UP_PDF) : Buffer.from("made-up token"),
      contentType: pdf ? "application/pdf" : "application/octet-stream",
      headers: { "Content-Security-Policy": "default-src 'none'; object-src 'self'; frame-ancestors 'self'" },
    });
  });
  await page.route("**/api/verify", (route) => {
    verifyCalls += 1;
    return route.fulfill({ json: verify });
  });
  // Layer 6, with a little state so changes behave like the real backend.
  let handover: HandoverState = structuredClone(options.handover ?? handoverFor(result));
  let baseline: BaselineInfo = BASELINE_NONE;
  let compare: CompareResponse = COMPARE_NONE;
  const layer6Calls: { method: string; url: string; body: unknown }[] = [];
  const note = (route: import("@playwright/test").Route) => {
    const req = route.request();
    layer6Calls.push({ method: req.method(), url: new URL(req.url()).pathname, body: req.postDataJSON() });
  };
  await page.route("**/api/handover", (route) => route.fulfill({ json: handover }));
  await page.route("**/api/answers", (route) => {
    note(route);
    const body = route.request().postDataJSON() as {
      subject: string;
      answer: "mine" | "landlord" | "unknown" | null;
      confirmed: boolean | null;
    };
    const names = handover.names;
    handover = body.answer === "mine" ? structuredClone(HANDOVER_CAMERA_MINE) : structuredClone(HANDOVER);
    handover.names = names;
    handover.answers = body.answer ? { [body.subject]: body.answer } : {};
    handover.confirmed = body.answer === "landlord" && body.confirmed != null ? { [body.subject]: body.confirmed } : {};
    return route.fulfill({ json: handover });
  });
  // "Recheck this": made-up results by rule, as app/handover/recheck.py words them.
  await page.route("**/api/tasks/*/recheck", (route) => {
    note(route);
    const id = decodeURIComponent(new URL(route.request().url()).pathname.split("/").slice(-2)[0] ?? "");
    const text = id.startsWith("R-WPS") ? "WPS is now off on that router." : "The device is still on this network.";
    const observed = id.startsWith("R-WPS");
    handover = {
      ...handover,
      tasks: handover.tasks.map((t) =>
        t.id === id
          ? {
              ...t,
              observed,
              recheck: { outcome: observed ? "fixed" : "still_there", text, checked_at: "2026-11-21T10:20:00Z" },
            }
          : t,
      ),
    };
    return route.fulfill({ json: handover });
  });
  await page.route("**/api/names", (route) => {
    note(route);
    const body = route.request().postDataJSON() as { subject: string; name: string };
    handover = { ...handover, names: { ...(handover.names ?? {}), [body.subject]: body.name } };
    return route.fulfill({ json: handover });
  });
  await page.route("**/api/tasks/*", (route) => {
    note(route);
    const id = decodeURIComponent(new URL(route.request().url()).pathname.split("/").pop() ?? "");
    const change = route.request().postDataJSON() as { status?: string; notes?: string; host_confirmed?: boolean };
    handover = {
      ...handover,
      tasks: handover.tasks.map((t) =>
        t.id === id
          ? {
              ...t,
              ...(change.status ? { status: change.status as typeof t.status } : {}),
              ...(change.notes !== undefined ? { notes: change.notes } : {}),
              ...(change.host_confirmed !== undefined
                ? { host_confirmed: change.host_confirmed, host_confirmed_at: change.host_confirmed ? "2026-11-21T10:15:00Z" : null }
                : {}),
              changed_at: "2026-11-21T10:15:00Z",
            }
          : t,
      ),
    };
    return route.fulfill({ json: handover });
  });
  await page.route("**/api/baseline", (route) => {
    note(route);
    const method = route.request().method();
    if (method === "POST") baseline = { state: "saved", saved_at: "2026-11-03T05:30:00Z", devices: 6, nearby: 1, message: null };
    if (method === "DELETE") {
      baseline = BASELINE_NONE;
      compare = COMPARE_NONE;
    }
    return route.fulfill({ json: baseline });
  });
  await page.route("**/api/compare", (route) => route.fulfill({ json: compare }));
  // "Possibly the same device": record the answer on the matching items.
  await page.route("**/api/compare/matches", (route) => {
    note(route);
    const { match_id, decision } = route.request().postDataJSON() as { match_id: string; decision: "same" | "different" | null };
    if (compare.comparison) {
      const mark = (items: CompareItem[]) =>
        items.map((i) => (i.match_id === match_id ? { ...i, decision } : i));
      const c = compare.comparison;
      compare = { ...compare, comparison: { ...c, changed: mark(c.changed), possible: mark(c.possible ?? []) } };
    }
    return route.fulfill({ json: compare });
  });
  // "Delete all saved RoomCheck data": everything back to nothing saved.
  await page.route("**/api/data", (route) => {
    note(route);
    roomLabel = null;
    baseline = BASELINE_NONE;
    compare = COMPARE_NONE;
    handover = { ...structuredClone(HANDOVER), names: {}, notes: {}, answers: {}, confirmed: {} };
    return route.fulfill({ json: { baseline, handover } });
  });
  let setup: Setup = SETUP_READY;
  let setupDelay = 0;
  await page.route("**/api/setup", async (route) => {
    if (setupDelay) await new Promise((r) => setTimeout(r, setupDelay));
    await route.fulfill({ json: setup });
  });

  let locatorResolve: (ws: WebSocketRoute) => void = () => {};
  const locatorOpened = new Promise<WebSocketRoute>((r) => (locatorResolve = r));
  let locatorSocket: WebSocketRoute | null = null;
  let locatorClosed = false;
  await page.routeWebSocket(/\/api\/nearby\/locate\//, (ws) => {
    locatorSocket = ws;
    locatorClosed = false;
    ws.onClose(() => {
      locatorClosed = true;
    });
    locatorResolve(ws);
  });

  let resolve: (ws: WebSocketRoute) => void = () => {};
  const opened = new Promise<WebSocketRoute>((r) => (resolve = r));
  let current: WebSocketRoute | null = null;
  let connections = 0;
  await page.routeWebSocket(/\/api\/scans\/job\d+\/events$/, (ws) => {
    connections += 1;
    current = ws; // keep the latest connection
    resolve(ws);
  });

  return {
    socket: () => opened,
    async send(snapshots) {
      const ws = current ?? (await opened);
      for (const s of snapshots) ws.send(JSON.stringify({ type: "state", ...s }));
    },
    async drop() {
      const ws = current ?? (await opened);
      await ws.close({ code: 4000, reason: "dropped" });
    },
    setPoll(answer) {
      poll = answer;
    },
    connections: () => connections,
    outside,
    cspErrors,
    consoleErrors,
    scanBodies,
    cancels: () => cancels,
    locator: () => locatorOpened,
    async pushReadings(readings) {
      const ws = locatorSocket ?? (await locatorOpened);
      for (const r of readings) ws.send(JSON.stringify(r));
    },
    locatorClosed: () => locatorClosed,
    setVerify(answer) {
      verify = answer;
    },
    verifyCalls: () => verifyCalls,
    setBaseline(info) {
      baseline = info;
    },
    setCompare(answer) {
      compare = answer;
    },
    layer6Calls,
    setSetupDelay(ms) {
      setupDelay = ms;
    },
    setSetup(answer) {
      setup = answer;
    },
    sent: () => sent,
  };
}

/** WCAG 2.2 AA checks with axe, on the page as it is now. */
export async function expectNoAxeViolations(page: Page) {
  await page.waitForTimeout(TRANSITION_MS); // check final colours, not a 150 ms fade
  // axe reads a control that has scrolled under the sticky header as covered (target-size), so
  // the header scrolls with the page while axe runs. Whether the header ever hides focus is
  // tested on its own (design.spec.ts, Focus Not Obscured). Set through the CSSOM: no inline CSS.
  await page.evaluate(() => document.querySelector("header")?.style.setProperty("position", "static"));
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"])
    .analyze();
  await page.evaluate(() => document.querySelector("header")?.style.removeProperty("position"));
  const summary = results.violations.map(
    (v) => `${v.id}: ${v.help}\n  ${v.nodes.map((n) => n.target.join(" ")).join("\n  ")}`,
  );
  expect(summary).toEqual([]);
}

/** No sideways scrolling: content reflows at this width (WCAG 1.4.10). */
export async function expectNoHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
}

const HANDOVER_TAB = /^Handover(\s*,\s*\d+ open tasks?)?$/;

/** Go to a page from the header, as a person would at this size: a visible tab, or on a phone
 * the "More" menu first (Compare, Report, Verify a report). Handover's name carries its count. */
export async function openPage(page: Page, name: string) {
  const bar = page.getByRole("banner");
  const target = () => (name === "Handover" ? bar.getByRole("button", { name: HANDOVER_TAB }) : bar.getByRole("button", { name, exact: true }));
  if ((await target().count()) === 0) {
    const more = bar.getByRole("button", { name: "More", exact: true });
    if ((await more.count()) > 0 && (await more.getAttribute("aria-expanded")) !== "true") await more.click();
  }
  await target().first().click();
}

/** Whether this page shows the phone layout (the "More" menu). */
export async function isPhoneLayout(page: Page) {
  return (await page.getByRole("banner").getByRole("button", { name: "More", exact: true }).count()) > 0;
}
