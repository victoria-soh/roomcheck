// The Results UI/UX and wording pass in a real browser, at laptop and phone sizes: anchors clear
// the sticky header, the phone's stacked buttons, compact Low/Info rows, Coverage and
// limits, and axe (including colour contrast on the helper text) with everything open.
import { expect, test, type Locator, type Page } from "@playwright/test";

import { LIVE, NOTHING_FOUND_COMPLETE, RESULT } from "../src/test/fixtures";
import { expectNoAxeViolations, expectNoHorizontalScroll, isPhoneLayout, mockBackend, START_BUTTON, type Mocked } from "./mock";

async function toResults(page: Page, mocked: Mocked) {
  await page.goto("/");
  await page.getByRole("radio", { name: "No, or I'm not sure", exact: true }).check();
  await page.getByRole("button", { name: START_BUTTON }).click();
  await mocked.socket();
  await mocked.send(LIVE);
  await page.getByRole("button", { name: "See your results" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Results" })).toBeFocused();
}

/** The element's top edge is below the sticky header's bottom edge. */
async function expectClearOfHeader(page: Page, target: Locator) {
  await page.waitForTimeout(300); // smooth scrolling, if any, has settled
  const header = await page.getByRole("banner").boundingBox();
  const box = await target.boundingBox();
  expect(box!.y).toBeGreaterThanOrEqual(header!.y + header!.height - 1);
}

test("the summary's links scroll their target clear of the sticky header", async ({ page }) => {
  const mocked = await mockBackend(page, RESULT);
  await toResults(page, mocked);
  await page.getByRole("button", { name: "See what didn't" }).click();
  await expectClearOfHeader(page, page.getByRole("heading", { level: 2, name: "Coverage and limits" }));
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.getByRole("button", { name: "Review camera-like device" }).click();
  await expectClearOfHeader(page, page.getByRole("heading", { level: 3, name: /^Likely camera/ }));
});

test("card buttons stack full width on a phone, side by side on a laptop", async ({ page }) => {
  const mocked = await mockBackend(page, RESULT);
  await toResults(page, mocked);
  const draft = page.getByRole("article", { name: /^Likely camera/ }).getByRole("button", { name: "Draft a message to the host" });
  const view = page.getByRole("article", { name: /^Likely camera/ }).getByRole("button", { name: "View in handover" });
  const [a, b] = [await draft.boundingBox(), await view.boundingBox()];
  if (await isPhoneLayout(page)) {
    // Stacked and full width: the second button is below the first, both as wide.
    expect(b!.y).toBeGreaterThan(a!.y + a!.height - 1);
    expect(Math.abs(a!.width - b!.width)).toBeLessThan(2);
  } else {
    expect(Math.abs(a!.y - b!.y)).toBeLessThan(2); // side by side on a laptop
  }
  await expectNoHorizontalScroll(page);
});

test("everything open passes axe, including colour contrast on the helper text", async ({ page }) => {
  const mocked = await mockBackend(page, RESULT);
  await toResults(page, mocked);
  await page.getByRole("button", { name: "See what didn't" }).click();
  // Every disclosure open: compact rows, evidence, the camera expander, Help identify this.
  await page.evaluate(() => document.querySelectorAll("main details").forEach((d) => ((d as HTMLDetailsElement).open = true)));
  await expect(page.getByText(/Device types are unconfirmed: clues, not proof\./)).toBeVisible();
  await expectNoAxeViolations(page);
  await expectNoHorizontalScroll(page);
});

test("nothing found: heading kept, each question's status, Coverage and limits open, and axe", async ({ page }) => {
  const mocked = await mockBackend(page, NOTHING_FOUND_COMPLETE);
  await toResults(page, mocked);
  await expect(page.getByRole("heading", { level: 2, name: "Not detected by the checks that ran" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Is anything watching?" })).toContainText("Not detected by the checks that ran");
  await expect(page.locator("#coverage-limits")).toHaveAttribute("open", "");
  await expectNoAxeViolations(page);
});

test("Fixed rules set every priority opens Help at how priorities are set", async ({ page }) => {
  const mocked = await mockBackend(page, RESULT);
  await toResults(page, mocked);
  await page.getByRole("button", { name: "Fixed rules set every priority." }).click();
  // The row opens, and its summary (holding the heading) takes focus, clear of the header.
  await expect(page.locator("#help-priority")).toHaveAttribute("open", "");
  await expect(page.locator("#help-priority > summary")).toBeFocused();
  await expectClearOfHeader(page, page.getByRole("heading", { level: 3, name: "How priorities are set" }));
});
