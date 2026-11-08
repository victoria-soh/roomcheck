// Six UX fixes in a real browser, at laptop and phone sizes (the two projects): phone navigation
// with no cut-off labels and a keyboard-usable More menu, the summary's named actions, counts
// scoped to the page, Back/Forward/refresh with focus returned, the cards' three labelled parts
// and the move-in scan wording. axe on each screen, at both sizes.
import { expect, test, type Page } from "@playwright/test";

import { LIVE, RESULT } from "../src/test/fixtures";
import { expectNoAxeViolations, expectNoHorizontalScroll, isPhoneLayout, mockBackend, openPage, START_BUTTON, type Mocked } from "./mock";

async function toResults(page: Page, mocked: Mocked) {
  await page.goto("/");
  await page.getByRole("radio", { name: "No, or I'm not sure", exact: true }).check();
  await page.getByRole("button", { name: START_BUTTON }).click();
  await mocked.socket();
  await mocked.send(LIVE);
  await page.getByRole("button", { name: "See your results" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Results" })).toBeFocused();
}

/** Every visible label in the header shows whole: nothing clipped, nothing off-screen. */
async function expectNoCutOffLabels(page: Page) {
  const problems = await page.getByRole("banner").evaluate((header) => {
    const out: string[] = [];
    const vw = document.documentElement.clientWidth;
    for (const el of header.querySelectorAll<HTMLElement>("button, a, [role=link]")) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || getComputedStyle(el).visibility === "hidden") continue;
      const text = el.innerText.trim();
      if (el.scrollWidth > el.clientWidth + 1) out.push(`clipped: ${text}`);
      if (r.left < -0.5 || r.right > vw + 0.5) out.push(`off-screen: ${text}`);
      // A scrolling parent would hide part of it.
      for (let p = el.parentElement; p && p !== header; p = p.parentElement) {
        const pr = p.getBoundingClientRect();
        const style = getComputedStyle(p);
        if (style.overflowX !== "visible" && (r.left < pr.left - 0.5 || r.right > pr.right + 0.5)) out.push(`hidden by scrolling: ${text}`);
      }
    }
    return out;
  });
  expect(problems).toEqual([]);
}

test.describe("1. Navigation", () => {
  test("no header label is ever cut off, at this size", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await toResults(page, mocked);
    await expectNoCutOffLabels(page);
    await expectNoHorizontalScroll(page);
    if (await isPhoneLayout(page)) {
      const nav = page.getByRole("navigation", { name: "Main" });
      await expect(nav.getByRole("button")).toHaveText([/^Results$/, /^Nearby$/, /^Handover/, /^More$/]);
      await nav.getByRole("button", { name: "More" }).click();
      await expectNoCutOffLabels(page);
    } else {
      // The laptop's row is as it was: every page a tab, Verify at the right.
      const names = await page.getByRole("navigation", { name: "Main" }).getByRole("button").allTextContents();
      expect(names.map((n) => n.replace(/\s*·\s*\d+.*$/, ""))).toEqual(["Results", "Nearby", "Handover", "Compare", "Report", "Verify a report"]);
    }
  });

  test("the More menu works with the keyboard: open, move, Escape, choose", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await toResults(page, mocked);
    test.skip(!(await isPhoneLayout(page)), "the More menu is the phone layout");
    const more = page.getByRole("button", { name: "More", exact: true });
    await more.focus();
    await page.keyboard.press("Enter");
    await expect(more).toHaveAttribute("aria-expanded", "true");
    const list = page.getByRole("list", { name: "More pages" });
    await expect(list.getByRole("button", { name: "Compare" })).toBeFocused();
    await expectNoAxeViolations(page);
    await page.keyboard.press("Escape");
    await expect(list).toHaveCount(0);
    await expect(more).toBeFocused();
    await expect(more).toHaveAttribute("aria-expanded", "false");
    // Outside click closes it.
    await more.click();
    await expect(list).toBeVisible();
    const viewport = page.viewportSize()!;
    await page.mouse.click(8, viewport.height - 8); // well away from the menu
    await expect(list).toHaveCount(0);
    // Choose with the keyboard: Tab to Report, Enter.
    await more.focus();
    await page.keyboard.press("Enter");
    await page.keyboard.press("Tab");
    await expect(list.getByRole("button", { name: "Report", exact: true })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { level: 1, name: "Handover report" })).toBeFocused();
    await expect(more).toHaveAttribute("aria-expanded", "false");
    await more.click();
    await expect(list.getByRole("button", { name: "Report", exact: true })).toHaveAttribute("aria-current", "page");
  });

  test("Handover has a Create report link", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await toResults(page, mocked);
    await openPage(page, "Handover");
    await page.getByRole("button", { name: "Create report" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Handover report" })).toBeFocused();
    await expectNoAxeViolations(page);
  });
});

test.describe("2 and 3. The summary and the questions", () => {
  test("named action, the recovery step, one count, and nearby cards that lead to Nearby", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await toResults(page, mocked);
    const banner = page.getByRole("region", { name: "5 things to look at" });
    await expect(banner.getByRole("button", { name: "Review camera-like device" })).toBeVisible();
    // The demo's reasons (no DHCP answer, the lookup service) have no fix to offer, so no step.
    await expect(banner).not.toContainText("To check more next time:");
    await expect(page.getByRole("region", { name: "Findings by priority" })).toHaveCount(0);
    await page.getByRole("article", { name: /^Item tracker nearby/ }).getByRole("button", { name: "Find it on Nearby" }).click();
    await expect(page.getByRole("heading", { level: 1, name: /Nearby/ })).toBeFocused();
  });
});

test.describe("4. Back, Forward and refresh", () => {
  test("Back returns to the previous screen and to the control that was used", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await toResults(page, mocked);
    await openPage(page, "Nearby");
    await expect(page).toHaveURL(/#\/nearby$/);
    const locate = page.getByRole("button", { name: "Locate signal" }).first();
    await locate.focus();
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/#\/nearby\/locate\//);
    await page.goBack();
    await expect(page.getByRole("heading", { level: 1, name: /Nearby/ })).toBeVisible();
    await expect(page.getByRole("button", { name: "Locate signal" }).first()).toBeFocused();
    await page.goBack();
    await expect(page.getByRole("heading", { level: 1, name: "Results" })).toBeVisible();
    await page.goForward();
    await expect(page.getByRole("heading", { level: 1, name: /Nearby/ })).toBeVisible();
    await expect(page).toHaveURL(/#\/nearby$/);
  });

  test("a refresh keeps the screen while its check is still there, and explains when it isn't", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await toResults(page, mocked);
    await openPage(page, "Handover");
    await page.reload();
    await expect(page.getByRole("heading", { level: 1, name: "Handover" })).toBeVisible();
    await expect(page).toHaveURL(/#\/handover$/);
    mocked.setPoll("fail"); // the server no longer has the check
    await page.reload();
    await expect(page.getByText("That page needs a check that isn't available any more")).toBeVisible();
    await expect(page).toHaveURL(/#\/start$/);
    await expectNoAxeViolations(page);
  });

  test("Back during a check keeps the check: it returns to its progress", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await page.goto("/");
    await page.getByRole("radio", { name: "No, or I'm not sure", exact: true }).check();
    await page.getByRole("button", { name: START_BUTTON }).click();
    await mocked.socket();
    await expect(page).toHaveURL(/#\/check$/);
    await page.goBack();
    await expect(page).toHaveURL(/#\/check$/);
    await expect(page.getByRole("heading", { level: 1, name: "Checking your room" })).toBeVisible();
    expect(mocked.connections()).toBe(1); // the same live connection: not restarted
    expect(mocked.scanBodies).toHaveLength(1); // and no second check started
  });
});

test.describe("5 and 6. Cards and the move-in scan", () => {
  test("each flagged card has its three labelled parts, details collapsed below", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await toResults(page, mocked);
    // Low and Info cards are compact rows: open them to see their parts.
    for (const summary of await page.locator("article details[data-compact] > summary").all()) await summary.click();
    for (const card of await page.getByRole("article").all()) {
      await expect(card.getByRole("heading", { level: 4 }).nth(0)).toHaveText("What we observed");
      await expect(card.getByRole("heading", { level: 4 }).nth(1)).toHaveText("What it could mean");
      await expect(card.getByRole("heading", { level: 4 }).nth(2)).toHaveText("What you can do");
      await expect(card.locator("details:not([data-compact])", { hasText: "Evidence and details" })).not.toHaveAttribute("open", "");
    }
    const move = page.getByRole("region", { name: "Move-in scan" });
    await expect(move).toContainText("Save this check so RoomCheck can show you anything new that appears later.");
    await expect(move.getByRole("button", { name: "Save as my move-in scan" })).toBeVisible();
    await expect(page.locator("body")).not.toContainText(/\bbaseline\b/i);
    await expectNoAxeViolations(page);
  });
});

test.describe("axe and keyboard on every main screen", () => {
  for (const name of ["Results", "Nearby", "Handover", "Compare", "Report", "Verify a report"]) {
    test(`${name}: no axe violations, and the page tab is reachable by keyboard`, async ({ page }) => {
      const mocked = await mockBackend(page, RESULT);
      await toResults(page, mocked);
      if (name !== "Results") await openPage(page, name);
      await expect(page.getByRole("heading", { level: 1 })).toBeFocused();
      await expectNoAxeViolations(page);
      await expectNoHorizontalScroll(page);
      // Keyboard: from the top, Tab reaches the navigation (a tab, or More on a phone).
      // Start from the top of the page: the skip link, the first thing Tab reaches.
      await page.getByRole("link", { name: "Skip to main content" }).focus();
      const target = (await isPhoneLayout(page)) && ["Compare", "Report", "Verify a report"].includes(name) ? "More" : name;
      let reached = false;
      for (let i = 0; i < 25 && !reached; i++) {
        await page.keyboard.press("Tab");
        reached = await page.evaluate(
          (t) => (document.activeElement?.textContent ?? "").trim().startsWith(t) && !!document.activeElement?.closest("header"),
          target,
        );
      }
      expect(reached).toBe(true);
    });
  }
});
