// `python -m app --demo`, end to end against the real server: every screen works on made-up
// data, it says so on every page, and the browser makes no request outside 127.0.0.1.
import { expect, test, type Page } from "@playwright/test";

import { expectNoAxeViolations, openPage } from "../e2e/mock";

/** Every request and WebSocket the page makes, so the test can check none leaves this laptop. */
function recordRequests(page: Page): string[] {
  const urls: string[] = [];
  page.on("request", (r) => urls.push(r.url()));
  page.on("websocket", (ws) => urls.push(ws.url()));
  return urls;
}

function offLaptop(urls: string[]): string[] {
  return urls.filter((u) => {
    if (u.startsWith("data:") || u.startsWith("blob:") || u === "about:blank") return false;
    return new URL(u).hostname !== "127.0.0.1";
  });
}

async function runDemoCheck(page: Page) {
  await page.goto("/");
  await page.getByRole("radio", { name: "Yes, I have permission", exact: true }).check();
  await page.getByRole("button", { name: "Start full check" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Checking your room" })).toBeVisible();
  await page.getByRole("button", { name: "See your results" }).click({ timeout: 30_000 });
  await expect(page.getByRole("heading", { level: 1, name: "Results" })).toBeVisible();
}

test("Start says it's demo mode, on a made-up laptop, and so does every page", async ({ page }) => {
  const urls = recordRequests(page);
  await page.goto("/");
  await expect(page.getByRole("note", { name: "Demo mode: made-up data, nothing is scanned" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Is this laptop ready?" })).toContainText("Connected to Example-Home");
  await expect(page.getByRole("banner").getByText("Demo data", { exact: true })).toBeVisible();
  await expectNoAxeViolations(page);
  await openPage(page, "Help");
  await expect(page.getByRole("banner").getByText("Demo data", { exact: true })).toBeVisible();
  expect(offLaptop(urls)).toEqual([]);
});

test("a demo check, then Results, Nearby, Handover, Compare, Report and Verify", async ({ page }) => {
  const urls = recordRequests(page);
  await runDemoCheck(page);
  await expect(page.getByRole("article", { name: /^Likely camera/ })).toBeVisible();
  await expect(page.getByRole("banner").getByText("Demo data", { exact: true })).toBeVisible();
  await expectNoAxeViolations(page);

  await openPage(page, "Nearby");
  await expect(page.getByRole("heading", { level: 1, name: "Nearby" })).toBeVisible();

  await openPage(page, "Handover");
  await expect(page.getByRole("heading", { level: 1, name: /Handover/ })).toBeVisible();

  // The demo's move-in scan is already saved, so Compare compares.
  await openPage(page, "Compare");
  await expect(page.getByRole("heading", { level: 1, name: "Compare" })).toBeVisible();
  await expect(page.getByText(/move-in scan/i).first()).toBeVisible();

  // The report is built locally, with no trusted timestamp.
  await openPage(page, "Report");
  await page.getByRole("button", { name: "Create report" }).click();
  await expect(page.getByText("Demo mode: nothing is sent, so the report has no trusted timestamp.").first()).toBeVisible({
    timeout: 60_000,
  });
  const pdfHref = await page.getByRole("link", { name: "PDF", exact: true }).getAttribute("href");
  const shaHref = await page.getByRole("link", { name: "Fingerprint (.sha256)", exact: true }).getAttribute("href");
  const pdf = await (await page.request.get(pdfHref!)).body();
  const sha = await (await page.request.get(shaHref!)).body();
  expect(pdf.subarray(0, 4).toString()).toBe("%PDF");

  // Verify checks that same PDF against its fingerprint.
  await openPage(page, "Verify a report");
  await page.getByLabel("Choose report files").setInputFiles([
    { name: "report.pdf", mimeType: "application/pdf", buffer: pdf },
    { name: "report.sha256", mimeType: "text/plain", buffer: sha },
  ]);
  await page.getByRole("button", { name: "Check the report" }).click();
  await expect(page.getByText(/matches its fingerprint|Not timestamped/i).first()).toBeVisible();

  expect(offLaptop(urls)).toEqual([]);
});
