// The final UI polish, in a real browser at laptop and phone sizes (the two projects), at 200%
// zoom and with reduced motion: axe, the keyboard, and that no help section loses work.
import { expect, test, type Page } from "@playwright/test";

import { COMPARE_READY, LIVE, MIDWAY, RESULT, STARTING } from "../src/test/fixtures";
import { expectNoAxeViolations, expectNoHorizontalScroll, mockBackend, openPage, START_BUTTON, type Mocked } from "./mock";


async function startScan(page: Page, answer = "No, or I'm not sure") {
  await page.goto("/");
  await page.getByRole("radio", { name: answer, exact: true }).check();
  await page.getByRole("button", { name: START_BUTTON }).click();
}

async function toResults(page: Page, mocked: Mocked) {
  await startScan(page);
  await mocked.socket();
  await mocked.send(LIVE);
  await page.getByRole("button", { name: "See your results" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Results" })).toBeFocused();
}

function go(page: Page, name: string) {
  return openPage(page, name);
}

test.describe("Results", () => {
  test("a compact banner, coverage open when something wasn't checked, and no new-check button", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await toResults(page, mocked);
    const banner = page.getByRole("region", { name: "5 things to look at" });
    await expect(banner).toContainText(/\d+ of \d+ checks ran/);
    // Coverage and limits is at the bottom, collapsed while there are findings to read.
    await expect(page.locator("#coverage-limits")).not.toHaveAttribute("open", "");
    await expect(page.getByRole("main").getByRole("button", { name: /new check/i })).toHaveCount(0);
    // Move-in scan, under What's changed since move-in?, saying what it keeps.
    await expect(page.getByRole("region", { name: "Move-in scan" })).toContainText("Saved only on this laptop, encrypted for your Windows account.");
    await expectNoAxeViolations(page);
    await expectNoHorizontalScroll(page);
  });

  test("Review finding scrolls to, focuses and briefly highlights the card", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await toResults(page, mocked);
    await page.getByRole("button", { name: "Review camera-like device" }).focus();
    await page.keyboard.press("Enter");
    const cardEl = page.getByRole("article", { name: /^Likely camera/ });
    await expect(cardEl).toBeFocused();
    await expect(cardEl).toHaveClass(/review-highlight/);
    expect(await cardEl.evaluate((el) => getComputedStyle(el).animationName)).toBe("review-fade");
    await expect(cardEl).not.toHaveClass(/review-highlight/, { timeout: 4000 });
  });

  test("under reduced motion the highlight is a still ring, with no animation", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    const mocked = await mockBackend(page, RESULT);
    await toResults(page, mocked);
    await page.getByRole("button", { name: "Review camera-like device" }).click();
    const cardEl = page.getByRole("article", { name: /^Likely camera/ });
    await expect(cardEl).toHaveClass(/review-highlight/);
    const style = await cardEl.evaluate((el) => ({ animation: getComputedStyle(el).animationName, ring: getComputedStyle(el).boxShadow }));
    expect(style.animation).toBe("none");
    expect(style.ring).not.toBe("none");
  });
});

test.describe("Scanning", () => {
  test("Scan progress, network and mode under the title, elapsed time, and a plain Cancel", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await startScan(page);
    await mocked.socket();
    await mocked.send([STARTING, MIDWAY]);
    await expect(page.getByText("Example-Home · Listening only", { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { level: 2, name: "Scan progress" })).toBeVisible();
    await expect(page.getByText(/Elapsed \d+:\d\d · usually about 2 minutes$/)).toBeVisible();
    await expectNoAxeViolations(page);
    await page.getByRole("button", { name: "Cancel check" }).focus();
    await page.keyboard.press("Enter");
    await expect(page.getByText(/Nothing from a cancelled check is kept/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Keep checking" })).toBeFocused();
    await page.keyboard.press("Enter");
    // Completion waits for you: no jumping to Results.
    await mocked.send(LIVE.slice(2));
    await expect(page.getByRole("button", { name: "See your results" })).toBeVisible();
    await expect(page.getByRole("heading", { level: 1, name: "Checking your room" })).toBeVisible();
  });
});

test.describe("Nearby", () => {
  test("Locate signal with its note, one line of other signals, compact coverage", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await toResults(page, mocked);
    await go(page, "Nearby");
    await expect(page.getByRole("button", { name: "Locate signal" }).first()).toHaveAccessibleDescription(
      "Signal strength gives a rough idea of distance. It doesn't prove where a device is.",
    );
    await expect(page.getByText(/^Other signals detected: /)).toBeVisible();
    const coverage = page.locator("#nearby-checks");
    await expect(coverage).not.toHaveAttribute("open", "");
    await coverage.locator("summary").focus();
    await page.keyboard.press("Enter");
    await expect(coverage).toHaveAttribute("open", "");
    await expect(coverage).toContainText("Limits");
    await expectNoAxeViolations(page);
    await expectNoHorizontalScroll(page);
  });

  test("nothing flagged: Not detected by these checks, with coverage and limits", async ({ page }) => {
    const quiet = { ...RESULT, findings: RESULT.findings.filter((f) => f.scope !== "nearby") };
    const mocked = await mockBackend(page, quiet);
    await toResults(page, mocked);
    await go(page, "Nearby");
    await expect(page.getByText("Not detected by these checks")).toBeVisible();
    await expect(page.getByText("No nearby signals were flagged.")).toBeVisible();
    await expect(page.locator("#nearby-checks")).toHaveAttribute("open", "");
    await expectNoAxeViolations(page);
  });
});

test.describe("Handover", () => {
  test("summary and filters, compact cards that open, and the message first", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await toResults(page, mocked);
    await go(page, "Handover");
    await expect(page.getByText("Track questions and follow-up actions for your host.")).toBeVisible();
    await expect(page.getByText(/^\d+ open · \d+ resolved$/)).toBeVisible();
    const filters = page.getByRole("group", { name: "Show tasks" });
    await filters.getByRole("button", { name: /^Open/ }).click();
    await expect(filters.getByRole("button", { name: /^Open/ })).toHaveAttribute("aria-pressed", "true");
    await filters.getByRole("button", { name: /^All/ }).click();
    // A card opens from the keyboard for the question, steps, status and notes.
    const wps = page.getByRole("article", { name: "Ask for WPS to be turned off on the router" });
    await wps.getByText("Questions, steps and notes").focus();
    await page.keyboard.press("Enter");
    await expect(wps.getByText("Who to ask")).toBeVisible();
    await expectNoAxeViolations(page);
    // The message: choose the tasks it asks about, then edit and copy.
    await page.getByText("Draft message to host").click();
    const box = page.getByRole("textbox", { name: "Message" });
    await expect(box).toHaveValue(/1\. .*camera/);
    await page.getByRole("checkbox", { name: "Ask about the device that looks like a camera" }).uncheck();
    await expect(box).not.toHaveValue(/camera/);
    await expectNoAxeViolations(page);
    await expectNoHorizontalScroll(page);
  });
});

test.describe("Compare", () => {
  test("move-in scan vs this check, filters, and answering a possible match by keyboard", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    mocked.setBaseline({ state: "saved", saved_at: "2026-11-03T05:30:00Z", devices: 6, nearby: 1, message: null });
    mocked.setCompare(COMPARE_READY);
    await toResults(page, mocked);
    await go(page, "Compare");
    const versus = page.getByRole("region", { name: "Move-in scan vs this check" });
    await expect(versus).toContainText("With permission");
    await expect(versus).toContainText("Listening only");
    await versus.getByRole("button", { name: /^Changed/ }).click();
    await expect(page.getByRole("region", { name: "New (1)" })).toHaveCount(0);
    await versus.getByRole("button", { name: /^All differences/ }).click();
    const laptop = page.getByRole("article", { name: "Computer or phone" });
    await laptop.getByRole("radio", { name: "Not sure" }).focus();
    await page.keyboard.press("ArrowLeft"); // radios: arrows move and select
    await expect(laptop.getByRole("radio", { name: "Different devices" })).toBeChecked();
    const sent = mocked.layer6Calls.filter((c) => c.url === "/api/compare/matches");
    expect(sent.at(-1)?.body).toEqual({ match_id: COMPARE_READY.comparison!.possible![0]!.match_id, decision: "different" });
    await expectNoAxeViolations(page);
    await expectNoHorizontalScroll(page);
  });
});

test.describe("Report", () => {
  test("a contents summary, the bundle first, and the last room label filled in next time", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await toResults(page, mocked);
    await go(page, "Report");
    await expect(page.getByRole("region", { name: "This report will contain" })).toContainText("Network name included");
    await expectNoAxeViolations(page);
    await page.getByRole("textbox", { name: "Room name (optional)" }).fill("Room 4B");
    await page.getByRole("button", { name: "Create report" }).click();
    await expect(page.getByRole("link", { name: "Download report bundle" })).toHaveAttribute("href", /\.zip$/);
    await expect(page.getByRole("link", { name: "Fingerprint (.sha256)" })).toBeVisible();
    await expectNoAxeViolations(page);
    await go(page, "Results");
    await go(page, "Report");
    await expect(page.getByRole("textbox", { name: "Room name (optional)" })).toHaveValue("Room 4B");
    await expectNoHorizontalScroll(page);
  });
});

test.describe("Verify", () => {
  test("one drop area for all three files, a checklist, and Verify another report", async ({ page }) => {
    await mockBackend(page, RESULT);
    await page.goto("/");
    await go(page, "Verify a report");
    await expectNoAxeViolations(page);
    await page.getByLabel("Choose report files").setInputFiles([
      { name: "r.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF made-up") },
      { name: "r.tsr", mimeType: "application/octet-stream", buffer: Buffer.from("token") },
      { name: "r.sha256", mimeType: "text/plain", buffer: Buffer.from("abc  r.pdf") },
    ]);
    const files = page.getByRole("list", { name: "Files" });
    await expect(files).toContainText("Received: r.pdf");
    await expect(files).toContainText("Received: r.tsr");
    await expect(files).toContainText("Received: r.sha256");
    await expectNoAxeViolations(page);
    await page.getByRole("button", { name: "Check the report" }).click();
    await expect(page.getByRole("heading", { name: "Verified" })).toBeVisible();
    await page.getByRole("button", { name: "Verify another report" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Verify a report" })).toBeFocused();
    await expect(files).toContainText("Missing: needed to check the report.");
    await expectNoHorizontalScroll(page);
  });

  test("the drop area shows its focus ring", async ({ page }) => {
    await mockBackend(page, RESULT);
    await page.goto("/");
    await go(page, "Verify a report");
    await page.getByLabel("Choose report files").focus();
    await page.keyboard.press("Shift+Tab");
    await page.keyboard.press("Tab"); // focus from the keyboard, so :focus-visible applies
    const ring = await page.locator("label:has(input[multiple])").evaluate((el) => getComputedStyle(el).outlineStyle);
    expect(ring).toBe("solid");
  });
});

test.describe("Help never loses work", () => {
  test("Start: Help and back keeps the answer", async ({ page }) => {
    await mockBackend(page, RESULT);
    await page.goto("/");
    await page.getByRole("radio", { name: "Yes, I have permission" }).check();
    await go(page, "Help");
    await expect(page.getByRole("heading", { level: 1, name: "Help" })).toBeVisible();
    // No "Back to the start" button: the browser's Back returns to Start as it was.
    await expect(page.getByRole("button", { name: "Back to the start" })).toHaveCount(0);
    await page.goBack();
    await expect(page.getByRole("radio", { name: "Yes, I have permission" })).toBeChecked();
  });

  test("Report and Handover: Help and back keeps what you typed", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await toResults(page, mocked);
    await go(page, "Report");
    await page.getByRole("textbox", { name: "Room name (optional)" }).fill("Room 9");
    await page.getByRole("checkbox", { name: "Handover notes" }).check();
    await go(page, "Help");
    await page.getByRole("button", { name: "Back to Report" }).click();
    await expect(page.getByRole("textbox", { name: "Room name (optional)" })).toHaveValue("Room 9");
    await expect(page.getByRole("checkbox", { name: "Handover notes" })).toBeChecked();

    await go(page, "Handover");
    await page.getByText("Draft message to host").click();
    await page.getByRole("textbox", { name: "Message" }).fill("My own words.");
    await go(page, "Help");
    await page.getByRole("button", { name: "Back to Handover" }).click();
    await expect(page.getByRole("textbox", { name: "Message" })).toHaveValue("My own words.");
  });
});

test.describe("At 200% zoom", () => {
  test("Handover, Compare, Report and Verify reflow at 640 px and pass axe", async ({ page }) => {
    await page.setViewportSize({ width: 640, height: 400 });
    const mocked = await mockBackend(page, RESULT);
    mocked.setBaseline({ state: "saved", saved_at: "2026-11-03T05:30:00Z", devices: 6, nearby: 1, message: null });
    mocked.setCompare(COMPARE_READY);
    await toResults(page, mocked);
    for (const name of ["Handover", "Compare", "Report", "Verify a report", "Nearby"]) {
      await go(page, name);
      for (const summary of await page.locator("main details:not([open]) > summary").elementHandles()) await summary.click();
      await expectNoHorizontalScroll(page);
      await expectNoAxeViolations(page);
    }
  });
});
