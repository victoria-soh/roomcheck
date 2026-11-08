// Follow-up to the typography pass, in a real browser: digits from Plus Jakarta Sans under the
// body family, card buttons side by side (stacked on phones), the nothing-found header's
// Handover count, and the quiet page's device total.
import { expect, test, type Page } from "@playwright/test";

import { LIVE, NOTHING_FOUND, RESULT } from "../src/test/fixtures";
import type { DiscoveryResult } from "../src/api/types";
import { expectNoAxeViolations, isPhoneLayout, mockBackend, START_BUTTON } from "./mock";

async function showResults(page: Page, result: DiscoveryResult) {
  const mocked = await mockBackend(page, result);
  await page.goto("/");
  await page.getByRole("radio", { name: "No, or I'm not sure", exact: true }).check();
  await page.getByRole("button", { name: START_BUTTON }).click();
  await mocked.socket();
  await mocked.send(LIVE);
  await page.getByRole("button", { name: "See your results" }).click();
  await page.getByRole("heading", { level: 1, name: "Results" }).waitFor();
  return mocked;
}

test("digits 0–9 come from Plus Jakarta Sans, letters from Atkinson, both bundled", async ({ page }) => {
  const fonts: string[] = [];
  page.on("request", (r) => {
    if (/\.woff2?(\?|$)/.test(r.url())) fonts.push(r.url());
  });
  const mocked = await showResults(page, RESULT);
  await page.evaluate(() => document.fonts.ready);
  const faces = await page.evaluate(() =>
    [...document.fonts]
      .filter((f) => f.family.replace(/"/g, "") === "Atkinson Hyperlegible Next" && f.unicodeRange === "U+30-39")
      .map((f) => ({ weight: f.weight, status: f.status })),
  );
  expect(faces.map((f) => f.weight).sort()).toEqual(["400", "600", "700"]);
  // The body text has digits ("17 of 18 checks ran"), so the 400 digit face was used.
  expect(faces.find((f) => f.weight === "400")!.status).toBe("loaded");
  expect(fonts.some((u) => /plus-jakarta-sans-latin-400-normal/.test(u))).toBe(true);
  expect(fonts.every((u) => new URL(u).origin === new URL(page.url()).origin)).toBe(true);
  expect(mocked.cspErrors).toEqual([]);
});

test("the tracker card's two buttons sit side by side, stacked only on phones", async ({ page }) => {
  await showResults(page, RESULT);
  const tracker = page.getByRole("article", { name: /^Item tracker nearby/ });
  const nearby = tracker.getByRole("button", { name: "Find it on Nearby" });
  const handover = tracker.getByRole("button", { name: "View in handover" });
  await handover.scrollIntoViewIfNeeded();
  const a = (await nearby.boundingBox())!;
  const b = (await handover.boundingBox())!;
  if (await isPhoneLayout(page)) {
    expect(b.y).toBeGreaterThan(a.y + a.height - 1); // stacked, full width
    expect(Math.abs(a.width - b.width)).toBeLessThan(2);
  } else {
    expect(Math.abs(a.y - b.y)).toBeLessThan(2); // one row
    expect(b.x).toBeGreaterThan(a.x + a.width - 1);
  }
  await expectNoAxeViolations(page);
});

test("nothing found: the header's Handover count matches that check's handover data", async ({ page }) => {
  await showResults(page, NOTHING_FOUND);
  const bar = page.getByRole("banner");
  const more = bar.getByRole("button", { name: "More", exact: true });
  if (await more.isVisible()) await more.click();
  // That check has no tasks, so no count (the full check's 4 tasks would say "4 open tasks").
  await expect(bar.getByRole("button", { name: /^Handover/ })).toHaveAccessibleName("Handover");
});

test("quiet page: the device rows add up to the summary's number", async ({ page }) => {
  await showResults(page, NOTHING_FOUND);
  const n = NOTHING_FOUND.devices.length;
  await expect(page.getByText(new RegExp(`^Heard ${n} devices:`))).toBeVisible();
  const limits = page.locator("#coverage-limits");
  if ((await limits.getAttribute("open")) === null) await limits.locator("summary").click();
  await expect(limits.getByRole("row", { name: /^Devices heard in all/ })).toHaveText(
    `Devices heard in all${n} devices, each counted once however many checks heard it`,
  );
  await expectNoAxeViolations(page);
});
