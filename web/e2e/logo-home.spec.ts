// The header logo goes to Start (#/), from any page, with a visible focus ring. While a check is
// running it goes to the check's progress instead and never cancels or restarts it. Back and
// Forward still move between the hash routes.
import { expect, test, type Page } from "@playwright/test";

import { LIVE, RESULT, STARTING } from "../src/test/fixtures";
import { expectNoAxeViolations, mockBackend, openPage, START_BUTTON, type Mocked } from "./mock";

const logo = (page: Page) => page.getByRole("banner").getByRole("link", { name: "RoomCheck, go to start" });
const START_TITLE = "Check your room's Wi-Fi and devices";

async function startCheck(page: Page, mocked: Mocked) {
  await page.goto("/");
  await page.getByRole("radio", { name: "No, or I'm not sure", exact: true }).check();
  await page.getByRole("button", { name: START_BUTTON }).click();
  await mocked.socket();
}

test("from Help: the logo goes to Start, and Back returns to Help", async ({ page }) => {
  await mockBackend(page, RESULT);
  await page.goto("/");
  await page.getByRole("radio", { name: "Yes, I have permission", exact: true }).check();
  await openPage(page, "Help");
  await expect(page.getByRole("heading", { level: 1, name: "Help" })).toBeVisible();
  await expect(logo(page)).toHaveAttribute("href", "#/");
  await logo(page).click();
  await expect(page.getByRole("heading", { level: 1, name: START_TITLE })).toBeFocused();
  expect(new URL(page.url()).hash).toBe("#/start");
  // Start as it was left.
  await expect(page.getByRole("radio", { name: "Yes, I have permission", exact: true })).toBeChecked();
  await page.goBack();
  await expect(page.getByRole("heading", { level: 1, name: "Help" })).toBeVisible();
  await page.goForward();
  await expect(page.getByRole("heading", { level: 1, name: START_TITLE })).toBeVisible();
});

test("the logo has a visible focus ring and opens from the keyboard", async ({ page }) => {
  await mockBackend(page, RESULT);
  await page.goto("/");
  await openPage(page, "Help");
  await logo(page).focus();
  await page.keyboard.press("Tab");
  await page.keyboard.press("Shift+Tab");
  await expect(logo(page)).toBeFocused();
  const ring = await logo(page).evaluate((el) => {
    const s = getComputedStyle(el);
    return `${s.outlineStyle} ${s.outlineWidth}`;
  });
  expect(ring).toBe("solid 3px");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { level: 1, name: START_TITLE })).toBeVisible();
  await expectNoAxeViolations(page);
});

test("from Results: Start offers the latest results, and Back and Forward still work", async ({ page }) => {
  const mocked = await mockBackend(page, RESULT);
  await startCheck(page, mocked);
  await mocked.send(LIVE);
  await page.getByRole("button", { name: "See your results" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Results" })).toBeVisible();
  await logo(page).click();
  await expect(page.getByRole("heading", { level: 1, name: START_TITLE })).toBeVisible();
  const latest = page.getByRole("button", { name: /^View your latest results \(.+\)$/ });
  await expect(latest).toBeVisible();
  // Under the connection bar.
  const bar = await page.getByRole("region", { name: "Is this laptop ready?" }).boundingBox();
  expect((await latest.boundingBox())!.y).toBeGreaterThan(bar!.y + bar!.height - 1);
  await expectNoAxeViolations(page);
  await page.goBack();
  await expect(page.getByRole("heading", { level: 1, name: "Results" })).toBeVisible();
  await page.goForward();
  await expect(latest).toBeVisible();
  await latest.click();
  await expect(page.getByRole("heading", { level: 1, name: "Results" })).toBeVisible();
  expect(mocked.scanBodies).toHaveLength(1);
});

test("during a check: the logo goes to its progress and never cancels or restarts it", async ({ page }) => {
  const mocked = await mockBackend(page, RESULT);
  await startCheck(page, mocked);
  await mocked.send([STARTING]);
  await expect(page.getByRole("heading", { level: 1, name: "Checking your room" })).toBeVisible();
  await openPage(page, "Help");
  await expect(page.getByRole("heading", { level: 1, name: "Help" })).toBeVisible();
  await logo(page).click();
  await expect(page.getByRole("heading", { level: 1, name: "Checking your room" })).toBeVisible();
  expect(new URL(page.url()).hash).toBe("#/check");
  await expect(page.getByRole("button", { name: /View your latest results/ })).toHaveCount(0);
  expect(mocked.cancels()).toBe(0);
  expect(mocked.scanBodies).toHaveLength(1);
  // The same check carries on to its results.
  await mocked.send(LIVE);
  await page.getByRole("button", { name: "See your results" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Results" })).toBeVisible();
  expect(mocked.scanBodies).toHaveLength(1);
});
