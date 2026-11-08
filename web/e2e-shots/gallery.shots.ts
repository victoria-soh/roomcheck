import { expect, test } from "@playwright/test";
import path from "node:path";

const DIR = process.env.SHOTS_DIR ?? path.resolve(import.meta.dirname, "../../docs/screenshots/design-pass");

// The gallery calls no backend; answer anything sent to /api/ with nothing, so no request leaves.
test("component gallery", async ({ page }) => {
  await page.route((url) => url.pathname.startsWith("/api/"), (route) => route.fulfill({ status: 404, json: {} }));
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("response", (r) => r.status() >= 400 && errors.push(`${r.status()} ${r.url()}`));
  await page.goto("/gallery");
  await expect(page.getByRole("heading", { level: 1, name: "Component gallery" })).toBeVisible();
  await page.waitForTimeout(500);
  expect(errors).toEqual([]);
  await page.screenshot({ path: path.join(DIR, "0-gallery-1280.png"), fullPage: true });
});
