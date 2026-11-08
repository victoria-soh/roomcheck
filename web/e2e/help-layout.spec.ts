// Help, reorganised, in a real browser at laptop and phone sizes: axe, no sideways scroll, the
// keyboard order (jump links, then each row), and links from elsewhere landing on the right row.
import { expect, test } from "@playwright/test";

import { LIVE, RESULT } from "../src/test/fixtures";
import { expectNoAxeViolations, expectNoHorizontalScroll, mockBackend, openPage, START_BUTTON } from "./mock";

test("four cards in one column, axe-clean closed and open, no sideways scroll", async ({ page }) => {
  await mockBackend(page, RESULT);
  await page.goto("/");
  await openPage(page, "Help");
  await expect(page.getByRole("heading", { level: 1, name: "Help" })).toBeVisible();
  const cards = page.locator("main section:has(> h2), main section:has(> div > h2)");
  await expect(page.getByRole("heading", { level: 2 })).toHaveText(["If you find a hidden camera", "How RoomCheck works", "What's sent", "Your data"]);
  // One column: each card starts below the one before, at the same left edge.
  const boxes = await Promise.all((await cards.all()).map((c) => c.boundingBox()));
  for (let i = 1; i < boxes.length; i += 1) {
    expect(boxes[i]!.y).toBeGreaterThan(boxes[i - 1]!.y + boxes[i - 1]!.height - 1);
    expect(Math.abs(boxes[i]!.x - boxes[0]!.x)).toBeLessThan(1);
  }
  await expectNoHorizontalScroll(page);
  await expectNoAxeViolations(page);
  for (const summary of await page.locator("details:not([open]) > summary").elementHandles()) await summary.click();
  await expectNoHorizontalScroll(page);
  await expectNoAxeViolations(page);
});

test("keyboard: the jump links, then each row of How RoomCheck works, opened with Enter", async ({ page }) => {
  await mockBackend(page, RESULT);
  await page.goto("/");
  await openPage(page, "Help");
  const title = page.getByRole("heading", { level: 1, name: "Help" });
  await expect(title).toBeFocused();
  for (const name of ["Found a hidden camera?", "How it works", "What's sent", "Your data"]) {
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name, exact: true })).toBeFocused();
  }
  for (const name of ["What it checks", "What it can't see", "How priorities are set", "What counts as permission"]) {
    await page.keyboard.press("Tab");
    await expect(page.locator("summary", { hasText: name })).toBeFocused();
  }
  await page.keyboard.press("Enter");
  await expect(page.locator("#help-permission")).toHaveAttribute("open", "");
  await expect(page.locator("#help-permission").getByText("may be against the law in many places")).toBeVisible();
  // A jump link moves focus to its card.
  await page.getByRole("link", { name: "What's sent", exact: true }).click();
  await expect(page.getByRole("heading", { level: 2, name: "What's sent" })).toBeFocused();
});

test("Fixed rules set every priority lands on its row, open", async ({ page }) => {
  const mocked = await mockBackend(page, RESULT);
  await page.goto("/");
  await page.getByRole("radio", { name: "No, or I'm not sure", exact: true }).check();
  await page.getByRole("button", { name: START_BUTTON }).click();
  await mocked.socket();
  await mocked.send(LIVE);
  await page.getByRole("button", { name: "See your results" }).click();
  await page.getByRole("button", { name: "Fixed rules set every priority." }).click();
  await expect(page.locator("#help-priority")).toHaveAttribute("open", "");
  await expect(page.locator("#help-priority > summary")).toBeFocused();
  await expect(page.getByText("The AI only words the explanations. It never sets or changes a priority.")).toBeInViewport();
});

test("Start's footer lands on What it can't see, open", async ({ page }) => {
  await mockBackend(page, RESULT);
  await page.goto("/");
  await page.getByRole("button", { name: "What it can't see" }).click();
  await expect(page.locator("#help-cant")).toHaveAttribute("open", "");
  await expect(page.locator("#help-cant > summary")).toBeFocused();
  await expectNoAxeViolations(page);
});
