// The Start screen's "Check again": it re-reads the laptop's setup from the server, says
// "Checking…" while it does, then shows and announces the time, and the strip updates.
import { expect, test } from "@playwright/test";

import { RESULT, SETUP_MISSING, SETUP_READY } from "../src/test/fixtures";
import { expectNoAxeViolations, mockBackend } from "./mock";

test("Check again says Checking…, then the time, and the updated status", async ({ page }) => {
  const mocked = await mockBackend(page, RESULT);
  mocked.setSetup(SETUP_MISSING);
  await page.goto("/");
  const strip = page.getByRole("region", { name: "Is this laptop ready?" });
  await expect(strip.getByText("Missing", { exact: true })).toHaveCount(2);
  // The laptop changes (e.g. Bluetooth and Nmap set up), and the server answers slowly.
  mocked.setSetup(SETUP_READY);
  mocked.setSetupDelay(800);
  let requests = 0;
  page.on("request", (r) => {
    if (r.url().endsWith("/api/setup")) requests += 1;
  });
  await strip.getByRole("button", { name: "Check again" }).click();
  const busy = strip.getByRole("button", { name: "Checking…" });
  await expect(busy).toBeVisible();
  await expect(busy).toBeDisabled();
  await expect(strip.getByText(/^Checked again at \d{1,2}:\d{2}/)).toBeVisible();
  expect(requests).toBeGreaterThanOrEqual(1); // it asked the server again
  await expect(strip).toContainText("Connected to Example-Home");
  await expect(strip.getByText("Missing", { exact: true })).toHaveCount(0);
  await expect(strip.getByRole("button", { name: "Check again" })).toBeEnabled();
  // The time is in the strip's live region, so it's announced.
  await expect(strip.locator("[aria-live='polite']")).toContainText("Checked again at");
  await expectNoAxeViolations(page);
});

test("a missing item that's been fixed becomes ready after Check again", async ({ page }) => {
  const mocked = await mockBackend(page, RESULT);
  const bluetoothOff = { ...SETUP_READY, all_ready: false, items: SETUP_READY.items.map((i) => (i.name === "bluetooth" ? { ...i, ready: false } : i)) };
  mocked.setSetup(bluetoothOff);
  await page.goto("/");
  const strip = page.getByRole("region", { name: "Is this laptop ready?" });
  await expect(strip).toContainText("Bluetooth:");
  await expect(strip).toContainText("These checks will be limited: the tracker check.");
  mocked.setSetup(SETUP_READY);
  await strip.getByRole("button", { name: "Check again" }).click();
  await expect(strip.getByText(/^Checked again at /)).toBeVisible();
  await expect(strip).not.toContainText("Bluetooth:");
  await expect(strip).not.toContainText("These checks will be limited");
  await expect(page.getByRole("button", { name: /^Start/ })).not.toHaveText(/limited/);
});
