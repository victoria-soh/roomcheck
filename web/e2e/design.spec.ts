// The design pass: the sticky header never hides what has focus (WCAG 2.2 2.4.11), every screen
// passes axe with a visible focus ring at laptop and phone sizes and at 200% zoom, the phone tab
// row scrolls on its own, and the scan sweep stops under reduced motion.
import { expect, test, type Page } from "@playwright/test";

import { LIVE, MIDWAY, RESULT, STARTING } from "../src/test/fixtures";
import { expectNoAxeViolations, expectNoHorizontalScroll, mockBackend, openPage, START_BUTTON, type Mocked } from "./mock";


async function startScan(page: Page) {
  await page.goto("/");
  await page.getByRole("radio", { name: "No, or I'm not sure", exact: true }).check();
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

/** The focused element isn't under the sticky header (WCAG 2.2 2.4.11): its top edge is below
 * the header and on screen, and nothing else is drawn on top of it there. Fixed overlays (the
 * skip link) and the header's own controls just need to be the topmost thing where they are. */
async function expectFocusInView(page: Page) {
  const r = await page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    const header = document.querySelector("header")!;
    if (!el || el === document.body) return { ok: true, what: "body" };
    const box = el.getBoundingClientRect();
    const what = `${el.tagName} "${(el.textContent ?? "").trim().slice(0, 40)}" top ${box.top}`;
    const topmost = (x: number, y: number) => {
      const hit = document.elementFromPoint(x, y);
      return !!hit && (el.contains(hit) || hit.contains(el) || (el instanceof HTMLInputElement && !!el.labels?.[0]?.contains(hit)));
    };
    const cx = box.left + Math.min(box.width / 2, 8);
    if (header.contains(el) || ["fixed", "absolute"].includes(getComputedStyle(el).position)) {
      // Fully on screen too: a tab in the sideways-scrolling row is scrolled into view.
    const onScreen = box.left >= -0.5 && box.right <= window.innerWidth + 0.5;
    return { ok: onScreen && topmost(cx, box.top + Math.min(box.height / 2, 8)), what: `${what} left ${box.left} right ${box.right}` };
    }
    const under = header.getBoundingClientRect().bottom;
    const y = box.top + Math.min(box.height / 2, 4);
    const ok = box.top >= under - 0.5 && box.top < window.innerHeight && (box.width === 0 || topmost(cx, y));
    return { ok, what: `${what} under ${under}` };
  });
  expect(r.ok, r.what).toBe(true);
}

/** The focused element has a visible focus indicator. */
async function expectFocusVisible(page: Page) {
  const r = await page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    if (!el || el === document.body) return { ok: true, what: "body" };
    // Radio rows show the ring on their label; everything else on itself.
    const ringed = el.matches("input[type=radio]") ? (el.closest("label") as HTMLElement) : el;
    const s = getComputedStyle(ringed);
    const ok = s.outlineStyle !== "none" && parseFloat(s.outlineWidth) >= 2;
    return { ok, what: `${el.tagName} "${(el.textContent ?? el.getAttribute("aria-label") ?? "").trim().slice(0, 40)}" ${s.outlineStyle} ${s.outlineWidth}` };
  });
  expect(r.ok, r.what).toBe(true);
}

/** Tab forward through the page and back again, checking each stop. */
async function tabThrough(page: Page, stops = 40) {
  for (let i = 0; i < stops; i++) {
    await page.keyboard.press("Tab");
    await expectFocusVisible(page);
    await expectFocusInView(page);
  }
  // Backwards is where a sticky header hides things: content scrolls up under it.
  for (let i = 0; i < stops; i++) {
    await page.keyboard.press("Shift+Tab");
    await expectFocusInView(page);
  }
}

test.describe("Sticky header never hides focus", () => {
  test("tabbing through Results, forwards and back", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await toResults(page, mocked);
    for (const summary of await page.locator("main details:not([open]) > summary").elementHandles()) await summary.click(); // a long page
    await page.getByRole("heading", { level: 1, name: "Results" }).focus();
    await tabThrough(page, 60);
  });

  test("Review finding lands its card below the header", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await toResults(page, mocked);
    await page.mouse.wheel(0, 4000); // start from further down, so it scrolls up to the card
    const review = page.getByRole("button", { name: "Review camera-like device" }).first();
    await review.focus();
    await page.keyboard.press("Enter");
    await expect(page.locator("article:focus, [tabindex='-1']:focus")).toHaveCount(1);
    await expectFocusInView(page);
  });

  test("every page's heading shows below the header when it opens", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await toResults(page, mocked);
    for (const name of ["Nearby", "Handover", "Compare", "Report", "Verify a report", "Help", "Results"]) {
      await page.mouse.wheel(0, 3000);
      await go(page, name);
      await expect(page.locator("main h1:visible")).toBeFocused();
      await expectFocusInView(page);
    }
  });

  test("tabbing through Help and Handover", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await toResults(page, mocked);
    for (const name of ["Help", "Handover"]) {
      await go(page, name);
      await tabThrough(page, 30);
    }
  });
});

/** Every screen, in order, with axe and keyboard checks on each. */
async function everyScreen(page: Page, mocked: Mocked) {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await expectNoAxeViolations(page);
  await expectNoHorizontalScroll(page);
  for (const name of ["Help", "Verify a report"]) {
    await go(page, name);
    await expect(page.locator("main h1:visible")).toBeFocused();
    await expectNoAxeViolations(page);
    await expectNoHorizontalScroll(page);
    await tabThrough(page, 12);
  }
  await startScan(page);
  await mocked.socket();
  await mocked.send([STARTING, MIDWAY]);
  await expect(page.getByRole("heading", { level: 1, name: "Checking your room" })).toBeVisible();
  await expectNoAxeViolations(page);
  await expectNoHorizontalScroll(page);
  await go(page, "Help"); // Help during a check
  await expectNoAxeViolations(page);
  await page.getByRole("banner").getByRole("button", { name: "Check in progress" }).click();
  await mocked.send(LIVE.slice(2));
  await page.getByRole("button", { name: "See your results" }).click();
  for (const name of ["Results", "Nearby", "Handover", "Compare", "Report", "Verify a report", "Help"]) {
    if (name !== "Results") await go(page, name); // Results is already open
    await expect(page.locator("main h1:visible")).toBeFocused();
    await expectNoAxeViolations(page);
    await expectNoHorizontalScroll(page);
    await page.locator("main h1:visible").focus();
    await tabThrough(page, 12);
  }
  await page.getByRole("button", { name: "New check", exact: true }).click();
  await expectNoAxeViolations(page); // the confirmation, open
  await expectNoHorizontalScroll(page);
  // Fully on screen at every width (it once ran off a phone's left edge), and usable.
  const panel = page.getByRole("group", { name: "Start a new check?" });
  const box = (await panel.boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(page.viewportSize()!.width);
  await panel.getByRole("button", { name: "Keep these results" }).click();
  await expect(panel).toHaveCount(0);
}

test.describe("Every screen: axe, focus and reflow", () => {
  // Each walks every screen with axe and the keyboard: longer than the 30 s default allows
  // when the whole suite runs in parallel.
  test.describe.configure({ timeout: 90_000 });

  test("at this project's size (laptop or phone)", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await everyScreen(page, mocked);
  });

  test("at 200% zoom (a 1280 px window is 640 CSS px)", async ({ page }) => {
    await page.setViewportSize({ width: 640, height: 400 });
    const mocked = await mockBackend(page, RESULT);
    await everyScreen(page, mocked);
  });

  test("at the 320 px reflow width", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 640 });
    const mocked = await mockBackend(page, RESULT);
    await everyScreen(page, mocked);
  });
});

test.describe("Header on a phone", () => {
  test("a compact brand row, three whole tabs and a More menu, with nothing scrolling", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const mocked = await mockBackend(page, RESULT);
    await toResults(page, mocked);
    // The brand row stays one line: mark, wordmark, New check and the Help icon.
    const brand = page.getByRole("banner").locator("> div").first();
    expect((await brand.boundingBox())!.height).toBeLessThan(64);
    await expect(page.getByRole("banner").getByRole("button", { name: "Help", exact: true })).toBeVisible();
    await expect(page.getByText("Wi-Fi & device checker", { exact: false })).toBeHidden(); // descriptor
    // Results, Nearby and Handover as tabs, the rest under More: every label whole, no row
    // that scrolls sideways.
    const nav = page.getByRole("navigation", { name: "Main" });
    await expect(nav.getByRole("button")).toHaveText([/^Results$/, /^Nearby$/, /^Handover/, /^More$/]);
    for (const tab of await nav.getByRole("button").all()) {
      expect(await tab.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
      await expect(tab).toBeInViewport({ ratio: 1 });
    }
    expect(await nav.locator("ul").first().evaluate((el) => getComputedStyle(el).overflowX)).toBe("visible");
    await expectNoHorizontalScroll(page);
    await go(page, "Report"); // through the More menu
    await expect(page.getByRole("heading", { level: 1, name: "Handover report" })).toBeFocused();
    await expect(nav.getByRole("button", { name: "More" })).toBeInViewport();
  });
});

test.describe("Scan progress bar", () => {
  test("a visible bar of tasks done under Scan progress, never animated under reduced motion", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await startScan(page);
    await mocked.socket();
    await mocked.send([STARTING, MIDWAY]);
    const bar = page.getByRole("progressbar", { name: "Scan progress" });
    await expect(bar).toBeVisible();
    await expect(bar).toHaveAttribute("aria-valuetext", "3 of 5 tasks done");
    const box = (await bar.boundingBox())!;
    expect(box.height).toBeGreaterThanOrEqual(6); // a real bar, not a hairline
    expect(await page.locator(".scan-sweep").count()).toBe(0); // the old top line is gone
    await page.emulateMedia({ reducedMotion: "reduce" });
    const moving = await bar.evaluate((el) => getComputedStyle(el, "::-webkit-progress-value").transitionDuration);
    expect(parseFloat(moving)).toBeLessThan(0.01); // reduced motion: effectively instant
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await expectNoAxeViolations(page);
    await mocked.send(LIVE.slice(2));
    await expect(page.getByRole("heading", { level: 2, name: "Check complete" })).toBeVisible();
    await expect(bar).toHaveCount(0); // it goes when the check ends
  });
});

// Every primary button that can be used has the full primary look (lagoon fill, ink text, fully
// opaque); only primaries that can't be used yet (aria-disabled) are paler. Checked from the
// computed style, with the pointer away so no hover colour is measured.
async function primaries(page: Page) {
  await page.mouse.move(0, 0);
  await page.waitForTimeout(250); // let the 150 ms hover transition finish
  return page.evaluate(() =>
    [...document.querySelectorAll<HTMLElement>("button, a")]
      .filter((el) => el.className.includes("bg-lagoon") && el.offsetParent !== null)
      .map((el) => {
        const s = getComputedStyle(el);
        return {
          name: (el.textContent ?? "").trim(),
          unavailable: el.getAttribute("aria-disabled") === "true",
          background: s.backgroundColor,
          opacity: Number(s.opacity),
        };
      }),
  );
}

async function expectPrimariesConsistent(page: Page, where: string) {
  const found = await primaries(page);
  expect(found.length, `${where}: a primary button`).toBeGreaterThan(0);
  const full = await page.evaluate(() => {
    const probe = document.createElement("span");
    probe.className = "bg-lagoon";
    document.body.append(probe);
    const colour = getComputedStyle(probe).backgroundColor;
    probe.remove();
    return colour;
  });
  for (const b of found) {
    if (b.unavailable) {
      expect(b.opacity, `${where}: "${b.name}" can't be used yet, so it's paler`).toBeLessThan(1);
    } else {
      expect({ name: b.name, background: b.background, opacity: b.opacity }, where).toEqual({
        name: b.name,
        background: full,
        opacity: 1,
      });
    }
  }
}

test("enabled primary buttons use the full primary style on every screen; only unavailable ones are pale", async ({ page }) => {
  const mocked = await mockBackend(page, RESULT);
  await page.goto("/");
  await expectPrimariesConsistent(page, "Start, nothing chosen"); // "Start the check" is unavailable
  await page.getByRole("radio", { name: "No, or I'm not sure", exact: true }).check();
  await expectPrimariesConsistent(page, "Start");
  await page.getByRole("button", { name: START_BUTTON }).click();
  await mocked.socket();
  await mocked.send(LIVE);
  await page.getByRole("button", { name: "See your results" }).waitFor();
  await expectPrimariesConsistent(page, "Scanning complete");
  await page.getByRole("button", { name: "See your results" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Results" })).toBeFocused();
  await expectPrimariesConsistent(page, "Results"); // "Review …"
  await go(page, "Report");
  await expectPrimariesConsistent(page, "Report");
  await go(page, "Verify a report");
  await expectPrimariesConsistent(page, "Verify"); // "Check the report", unavailable until a PDF
});
