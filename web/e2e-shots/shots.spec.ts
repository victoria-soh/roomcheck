import { test } from "@playwright/test";
import { readFileSync } from "node:fs";
import path from "node:path";

import { mockBackend, openPage, START_BUTTON } from "../e2e/mock";
import {
  BASELINE_SAVED,
  CAM_FINDING,
  COMPARE_READY,
  FINISHED,
  LISTENING,
  LIVE,
  MIDWAY,
  NOTHING_FOUND,
  NOT_TIMESTAMPED,
  READINGS,
  REPORT_AI_OFF,
  RESULT,
  RESULT_AI_OFF,
  SETUP_MISSING,
  SETUP_NO_AI,
  STARTING,
  TAMPERED,
} from "../src/test/fixtures";

const DIR = process.env.SHOTS_DIR ?? path.resolve(import.meta.dirname, "../../docs/screenshots/design-pass");

function file(name: string, width: string) {
  return path.join(DIR, `${name}-${width}.png`);
}

test("screens", async ({ page }, info) => {
  const w = info.project.name;
  await page.clock.install(); // so the 20 s "updates stopped" state can be shown
  const mocked = await mockBackend(page, RESULT);
  // The readiness strip shows the made-up network name "Example-Home".
  await page.goto("/");
  await page.getByText("Connected to Example-Home").waitFor();
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("1-start", w), fullPage: true });
  await page.getByRole("radio", { name: "Yes, I have permission", exact: true }).check();
  await page.getByRole("button", { name: "Start full check" }).focus();
  await page.waitForTimeout(300); // let the button finish turning teal
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("2-start-selected", w), fullPage: true });
  // Some readiness items missing: what's limited, and the start still allowed.
  mocked.setSetup(SETUP_MISSING);
  await page.getByRole("button", { name: "Check again" }).click();
  await page.getByText("These checks will be limited").waitFor();
  await page.waitForTimeout(300);
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("1b-start-missing", w), fullPage: true });
  // The made-up check is listening-only, so its skipped task matches the badge.
  await page.getByRole("radio", { name: "No, or I'm not sure", exact: true }).check();
  await page.getByRole("button", { name: START_BUTTON }).click();
  await mocked.socket();

  // Running: two tasks at once, with live details.
  await mocked.send([STARTING, LISTENING]);
  await page.getByText("3 devices found so far").waitFor();
  await page.waitForTimeout(300);
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("3-scanning", w), fullPage: true });

  // Quiet fallback: the live connection dropped, polling keeps it up to date.
  await mocked.send([MIDWAY]);
  mocked.setPoll({ ...MIDWAY, version: 11 });
  await mocked.drop();
  await page.clock.runFor(5_000);
  await page.getByText(/^Live connection interrupted/).first().waitFor();
  await page.waitForTimeout(300);
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("3b-scanning-quiet-fallback", w), fullPage: true });

  // Stopped: nothing has answered for over 20 s.
  mocked.setPoll("fail");
  await page.clock.runFor(24_000);
  await page.getByText("Updates have stopped", { exact: true }).waitFor();
  await page.waitForTimeout(300);
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("3c-scanning-stopped", w), fullPage: true });

  // Complete: a poll sees the check has finished; the card waits for you.
  mocked.setPoll({ ...FINISHED, result: RESULT });
  await page.clock.runFor(3_000);
  await page.getByRole("heading", { level: 2, name: "Check complete" }).waitFor();
  await page.getByRole("button", { name: "See your results" }).waitFor();
  await page.waitForTimeout(300);
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("3d-scanning-complete", w), fullPage: true });

  await page.getByRole("button", { name: "See your results" }).click();
  await page.getByRole("heading", { level: 1, name: "Results" }).waitFor();
  await page.waitForTimeout(300);
  // The first screenful on its own (what was found, what didn't run, what next), then the page.
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("4a-results-first-screen", w) });
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("4-results", w), fullPage: true });
  // Coverage, the camera's evidence and its hidden-camera guidance, opened.
  await page.getByRole("button", { name: "See what didn't" }).click();
  const cam = page.getByRole("article", { name: /^Likely camera/ });
  await cam.getByText("Found a hidden camera? See what to do").click();
  await cam.getByText("Evidence and details").click();
  await page.waitForTimeout(300); // let the chevrons finish turning
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("5-results-evidence-open", w), fullPage: true });
  // Every discovered device, including ones with no findings.
  await page.getByText(/^View all discovered devices/).click();
  await page.getByRole("columnheader", { name: "Identification confidence" }).waitFor();
  await page.waitForTimeout(300);
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("5b-results-all-devices", w), fullPage: true });
});

test("nothing found", async ({ page }, info) => {
  const mocked = await mockBackend(page, NOTHING_FOUND);
  await page.goto("/");
  await page.getByRole("radio", { name: "No, or I'm not sure", exact: true }).check();
  await page.getByRole("button", { name: START_BUTTON }).click();
  await mocked.socket();
  await mocked.send(LIVE);
  await page.getByRole("button", { name: "See your results" }).click();
  await page.getByRole("heading", { level: 1, name: "Results" }).waitFor();
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("6-results-nothing-found", info.project.name), fullPage: true });
});

// --- Part B ------------------------------------------------------------------------------------

async function toResults(page: import("@playwright/test").Page, mocked: Awaited<ReturnType<typeof mockBackend>>) {
  await page.goto("/");
  await page.getByRole("radio", { name: "No, or I'm not sure", exact: true }).check();
  await page.getByRole("button", { name: START_BUTTON }).click();
  await mocked.socket();
  await mocked.send(LIVE);
  await page.getByRole("button", { name: "See your results" }).click();
  await page.getByRole("heading", { level: 1, name: "Results" }).waitFor();
}

function navTo(page: import("@playwright/test").Page, name: string) {
  return openPage(page, name);
}

test("part b", async ({ page, context }, info) => {
  const w = info.project.name;
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  // The real report template, rendered from the demo check (tests/fixtures/report/make_demo_preview.py).
  const mocked = await mockBackend(page, RESULT, { pdf: readFileSync(path.resolve(import.meta.dirname, "../../tests/fixtures/report/demo_preview.pdf")) });
  await toResults(page, mocked);

  await navTo(page, "Nearby");
  await page.getByRole("heading", { level: 1, name: "Nearby Wi-Fi and Bluetooth" }).waitFor();
  await page.waitForTimeout(300);
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("7-nearby", w), fullPage: true });

  const tracker = page.getByRole("article", { name: "Item tracker nearby" });
  await tracker.getByRole("button", { name: "Locate signal" }).click();
  await mocked.locator();
  for (const r of READINGS) {
    await mocked.pushReadings([r]); // about a second apart, as Bluetooth readings come
    await page.waitForTimeout(900);
  }
  await page.getByText("Warmer", { exact: true }).waitFor();
  await page.waitForTimeout(300);
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("8-locator", w), fullPage: true });

  await navTo(page, "Report");
  await page.getByRole("textbox", { name: "Room name (optional)" }).fill("Room 4B");
  await page.getByRole("region", { name: "This report will contain" }).waitFor();
  await page.waitForTimeout(300);
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("9a-report-form", w), fullPage: true });
  await page.getByRole("button", { name: "Create report" }).click();
  await page.getByText("Checked: this PDF matches its timestamp.").waitFor();
  await page.getByTitle("Report preview").scrollIntoViewIfNeeded();
  await page.waitForTimeout(6000); // let the PDF viewer finish drawing the page
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("9-report", w), fullPage: true });

  await navTo(page, "Verify a report");
  await page.waitForTimeout(300);
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("10a-verify-start", w), fullPage: true });
  // One drop area for all the files; the checklist says what's here and what's missing.
  await page.getByLabel("Choose report files").setInputFiles([
    { name: "roomcheck-report.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF made-up") },
    { name: "roomcheck-report.tsr", mimeType: "application/octet-stream", buffer: Buffer.from("token") },
  ]);
  await page.getByText("Received: roomcheck-report.tsr").waitFor();
  await page.waitForTimeout(300);
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("10b-verify-files", w), fullPage: true });
  await page.getByRole("button", { name: "Check the report" }).click();
  await page.getByRole("heading", { name: "Verified" }).waitFor();
  await page.waitForTimeout(300);
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("10-verify-verified", w), fullPage: true });

  mocked.setVerify(TAMPERED);
  await page.getByRole("button", { name: "Check the report" }).click();
  await page.getByText("Files don't match").waitFor();
  await page.waitForTimeout(300);
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("11-verify-tampered", w), fullPage: true });

  // A report that wasn't timestamped: explained, never called altered.
  mocked.setVerify(NOT_TIMESTAMPED);
  await page.getByRole("button", { name: "Check the report" }).click();
  await page.getByRole("heading", { name: "Not timestamped" }).waitFor();
  await page.waitForTimeout(300);
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("11b-verify-not-timestamped", w), fullPage: true });
});

// --- Layer 6 -------------------------------------------------------------------------------------

test("layer 6", async ({ page }, info) => {
  const w = info.project.name;
  const mocked = await mockBackend(page, RESULT);
  await toResults(page, mocked);

  await navTo(page, "Handover");
  await page.getByRole("heading", { level: 2, name: "Tasks (4)" }).waitFor();
  await page.waitForTimeout(300);
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("13-handover", w), fullPage: true });
  // The message to the host, open: choose the tasks, edit, copy.
  await page.getByText("Draft message to host").click();
  await page.getByRole("textbox", { name: "Message" }).waitFor();
  await page.waitForTimeout(300);
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("13a-handover-message", w), fullPage: true });
  await page.getByText("Draft message to host").click();
  // A Resolved task, rechecked: what changed, and the "Observed by RoomCheck" evidence.
  const wps = page.getByRole("article", { name: "Ask for WPS to be turned off on the router" });
  await wps.getByText("Questions, steps and notes").click();
  await wps.getByRole("radio", { name: "Resolved" }).click();
  await wps.getByRole("button", { name: "Recheck this" }).click();
  await wps.getByText("Observed by RoomCheck").waitFor();
  await wps.scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("13b-handover-recheck", w), fullPage: true });
  // Back to To do, so every later screenshot of this check shows the same "Handover · 2".
  await wps.getByRole("radio", { name: "To do" }).click();
  await page.getByRole("banner").getByText(/^·\s*\d+$/).first().waitFor();

  mocked.setBaseline({ state: "saved", saved_at: "2026-11-03T05:30:00Z", devices: 6, nearby: 1, message: null });
  mocked.setCompare(COMPARE_READY);
  await navTo(page, "Compare");
  await page.getByRole("region", { name: "New (1)" }).waitFor();
  await page.waitForTimeout(300);
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("14-compare", w), fullPage: true });

  // Results with the camera answered "Host's", confirmed, and named: the second line says so,
  // and the finding and its priority stay where they were.
  await navTo(page, "Results");
  const cam = page.getByRole("article", { name: /^Likely camera/ });
  await cam.getByRole("radio", { name: "Host's" }).click();
  // "Not yet": a host-confirmed device would close its task and change the header's count.
  await cam.getByRole("group", { name: "Has the host confirmed this?" }).getByRole("radio", { name: "Not yet" }).click();
  await cam.getByRole("textbox", { name: "Your name for it (optional)" }).fill("Hallway camera");
  await cam.getByRole("button", { name: "Save name" }).click();
  await page.getByRole("article", { name: "Likely camera" }).filter({ hasText: "Hallway camera" }).waitFor();
  await page.waitForTimeout(300);
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("12-results-recognised", w), fullPage: true });
});

test("help identify this", async ({ page }, info) => {
  // The camera as an Unknown device (no maker, no type), with the guided panel open.
  const mocked = await mockBackend(page, {
    ...RESULT,
    devices: RESULT.devices.map((d) => (d.id === CAM_FINDING.device_ref ? { ...d, vendor: null, fingerprint: null } : d)),
  });
  await toResults(page, mocked);
  const card = page.getByRole("article", { name: /^Likely camera/ });
  await card.getByText("Help identify this").click();
  await card.getByText("1. Its clues").waitFor();
  await card.scrollIntoViewIfNeeded();
  await page.waitForTimeout(300);
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("12b-results-help-identify", info.project.name), fullPage: true });
});

test("layer 6, no baseline", async ({ page }, info) => {
  const mocked = await mockBackend(page, RESULT);
  await toResults(page, mocked); // with no saved scan, Compare is listed once there are results
  await navTo(page, "Compare");
  await page.getByRole("heading", { name: "Save a starting point to compare future checks" }).waitFor();
  await page.waitForTimeout(300);
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("15-compare-no-baseline", info.project.name), fullPage: true });
});

test("help and deleting data", async ({ page }, info) => {
  await mockBackend(page, RESULT);
  await page.goto("/");
  await navTo(page, "Help");
  await page.getByRole("heading", { level: 1, name: "Help" }).waitFor();
  await page.waitForTimeout(300);
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("16-help", info.project.name), fullPage: true });
  // The confirmation, saying exactly what will be deleted.
  await page.getByRole("button", { name: "Delete all saved RoomCheck data" }).click();
  await page.getByRole("button", { name: "Keep my data" }).waitFor();
  await page.waitForTimeout(300);
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("16b-help-delete-confirm", info.project.name), fullPage: true });
});

test("header: New check without a saved move-in scan, and the scrolled header", async ({ page }, info) => {
  const mocked = await mockBackend(page, RESULT);
  await toResults(page, mocked);
  await page.getByRole("button", { name: "New check", exact: true }).click();
  await page.getByRole("button", { name: "Keep these results" }).waitFor();
  await page.waitForTimeout(300);
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("17-new-check-no-baseline", info.project.name) });
  await page.getByRole("button", { name: "Keep these results" }).click();
  await page.mouse.wheel(0, 600); // the header's shadow once content scrolls under it
  await page.waitForTimeout(300);
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("17b-header-scrolled", info.project.name) });
});

test("header: New check with a saved move-in scan", async ({ page }, info) => {
  const mocked = await mockBackend(page, RESULT);
  mocked.setBaseline(BASELINE_SAVED); // with one saved, it just asks
  await toResults(page, mocked);
  await page.getByRole("button", { name: "New check", exact: true }).click();
  await page.getByRole("button", { name: "Keep these results" }).waitFor();
  await page.waitForTimeout(300);
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("17c-new-check-with-baseline", info.project.name) });
});

test("nearby, nothing flagged", async ({ page }, info) => {
  const quiet = { ...RESULT, findings: RESULT.findings.filter((f) => f.scope !== "nearby") };
  const mocked = await mockBackend(page, quiet);
  await toResults(page, mocked);
  await navTo(page, "Nearby");
  await page.getByText("Not detected by these checks").waitFor();
  await page.waitForTimeout(300);
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250); // let the 150 ms colour transition finish
  await page.screenshot({ path: file("7b-nearby-nothing-flagged", info.project.name), fullPage: true });
});

// The one AI-off state (no API key): the standard, template wording everywhere. The rest of the
// screenshots tell the demo's AI-on story.
test("AI off: template wording", async ({ page }, info) => {
  const w = info.project.name;
  const mocked = await mockBackend(page, RESULT_AI_OFF, { report: REPORT_AI_OFF });
  mocked.setSetup(SETUP_NO_AI);
  await page.goto("/");
  await toResults(page, mocked);
  await page.getByText("Findings are explained in standard words.").waitFor();
  await page.waitForTimeout(300);
  await page.mouse.move(0, 0); // no hover colour in the picture
  await page.waitForTimeout(250);
  await page.screenshot({ path: file("4c-results-ai-off", w), fullPage: true });
  await navTo(page, "Report");
  await page.getByRole("button", { name: "Create report" }).click();
  await page.getByRole("region", { name: "What happened" }).waitFor();
  await page.waitForTimeout(300);
  await page.mouse.move(0, 0);
  await page.waitForTimeout(250);
  await page.screenshot({ path: file("9c-report-ai-off", w), fullPage: true });
});
