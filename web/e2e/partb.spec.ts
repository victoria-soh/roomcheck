import { expect, test, type Page } from "@playwright/test";

import { BASELINE_SAVED, LIVE, READINGS, RESULT, RESULT_AI_OFF, SETUP_NO_AI, TAMPERED, VERIFIED } from "../src/test/fixtures";
import { expectNoAxeViolations, expectNoHorizontalScroll, isPhoneLayout, mockBackend, openPage, START_BUTTON, type Mocked } from "./mock";

async function toResults(page: Page, mocked: Mocked) {
  await page.goto("/");
  await page.getByRole("radio", { name: "No, or I'm not sure", exact: true }).check();
  await page.getByRole("button", { name: START_BUTTON }).click();
  await mocked.socket();
  await mocked.send(LIVE);
  await page.getByRole("button", { name: "See your results" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Results" })).toBeVisible();
}

// Every page link lives in the one header (the brand row's tools and the Main row).
// Handover's name carries its open-task count, so it's matched with or without one.
function nav(page: Page) {
  const bar = page.getByRole("banner");
  return {
    getByRole: (role: "button", opts: { name: string }) =>
      opts.name === "Handover" ? bar.getByRole(role, { name: /^Handover(\s*,\s*\d+ open tasks?)?$/ }) : bar.getByRole(role, { ...opts, exact: true }),
  };
}

async function toLocator(page: Page, mocked: Mocked) {
  await toResults(page, mocked);
  await nav(page).getByRole("button", { name: "Nearby" }).click();
  const tracker = page.getByRole("article", { name: "Item tracker nearby" });
  await tracker.getByRole("button", { name: "Locate signal" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Locate signal: Tile tracker" })).toBeVisible();
  await mocked.locator();
}

function expectClean(mocked: Mocked) {
  expect(mocked.outside).toEqual([]);
  expect(mocked.cspErrors).toEqual([]);
}

test.describe("Top bar", () => {
  test("before a check only Verify is listed, and keyboard works", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await page.goto("/");
    // No results yet: no navigation row at all, nor Compare without a move-in scan.
    await expect(page.getByRole("navigation", { name: "Main" })).toHaveCount(0);
    const bar = page.getByRole("navigation", { name: "Help and tools" });
    await expect(bar.getByRole("button")).toHaveText(["Verify a report", "Help"]);
    await expect(page.getByRole("button", { name: "New check" })).toHaveCount(0);
    const verify = nav(page).getByRole("button", { name: "Verify a report" });
    await verify.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { level: 1, name: "Verify a report" })).toBeFocused();
    await expect(verify).toHaveAttribute("aria-current", "page");
    await expectNoAxeViolations(page);
    expectClean(mocked);
  });

  test("before a check, Compare is listed too once a move-in scan is saved", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    mocked.setBaseline(BASELINE_SAVED);
    await page.goto("/");
    const bar = page.getByRole("navigation", { name: "Help and tools" });
    await expect(bar.getByRole("button")).toHaveText(["Compare", "Verify a report", "Help"]);
    await openPage(page, "Compare");
    await expect(page.getByRole("heading", { level: 1, name: "Compare with your move-in scan" })).toBeFocused();
  });

  test("after a check every page opens and the current one is marked", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await toResults(page, mocked);
    await expect(nav(page).getByRole("button", { name: "Results" })).toHaveAttribute("aria-current", "page");
    for (const [name, heading] of [
      ["Nearby", "Nearby Wi-Fi and Bluetooth"],
      ["Handover", "Handover"],
      ["Compare", "Compare with your move-in scan"],
      ["Report", "Handover report"],
      ["Verify a report", "Verify a report"],
      ["Results", "Results"],
    ]) {
      await openPage(page, name!);
      await expect(page.getByRole("heading", { level: 1, name: heading! })).toBeFocused();
      if (await isPhoneLayout(page)) {
        // On a phone, a page in the More menu marks More as current; the list says which.
        const inMore = ["Compare", "Report", "Verify a report"].includes(name!);
        if (!inMore) await expect(nav(page).getByRole("button", { name: name! })).toHaveAttribute("aria-current", "page");
      } else {
        await expect(nav(page).getByRole("button", { name: name! })).toHaveAttribute("aria-current", "page");
      }
    }
    // The check is over and shown: the full row on a laptop (Verify at the far right), three
    // tabs and More on a phone, and only one current.
    const names = await page.getByRole("navigation", { name: "Main" }).getByRole("button").allTextContents();
    const expected = (await isPhoneLayout(page))
      ? ["Results", "Nearby", "Handover", "More"]
      : ["Results", "Nearby", "Handover", "Compare", "Report", "Verify a report"];
    expect(names.map((n) => n.replace(/\s*·\s*\d+.*$/, ""))).toEqual(expected);
    await expect(page.getByRole("banner").locator("[aria-current=page]")).toHaveCount(1);
    await expect(page.getByRole("navigation", { name: "Help and tools" }).getByRole("button")).toHaveText(["Help"]);
  });
});

test.describe("Nearby screen", () => {
  test("nearby findings moved here, with Locate signal and the other-signals line", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await toResults(page, mocked);
    // WPS on your own router is under "Can you trust this Wi-Fi?"; the tracker is under "Is
    // anything watching?", and its card is the way to Nearby for the locator.
    await expect(page.getByRole("region", { name: "Can you trust this Wi-Fi?" }).getByRole("article", { name: /^Router advertises WPS/ })).toBeVisible();
    await expect(page.getByRole("region", { name: "Nearby Wi-Fi and Bluetooth" })).toHaveCount(0);
    await page.getByRole("article", { name: /^Item tracker nearby/ }).getByRole("button", { name: "Find it on Nearby" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Nearby Wi-Fi and Bluetooth" })).toBeFocused();
    await expect(page.getByText(/^Wi-Fi and Bluetooth signals detected around you\. Some may come from the network you're using\./)).toBeVisible();
    await expect(page.getByRole("article", { name: /^Router advertises WPS/ })).toHaveCount(0);
    // The tracker and the hidden network; the open networks can't be located one by one.
    await expect(page.getByRole("button", { name: "Locate signal" })).toHaveCount(2);
    await expect(page.getByText(/^Other signals detected: 6 Wi-Fi networks · 4 Bluetooth devices/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Locate signal" }).first()).toHaveAccessibleDescription(
      "Signal strength gives a rough idea of distance. It doesn't prove where a device is.",
    );
    await expectNoAxeViolations(page);
    for (const summary of await page.locator("details:not([open]) > summary").elementHandles()) await summary.click();
    await expectNoAxeViolations(page);
    expectClean(mocked);
  });
});

test.describe("Locator screen", () => {
  test("a live bar, warmer in words, the 30 s line, and Stop closes the connection", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await toLocator(page, mocked);
    await mocked.pushReadings(READINGS);
    const meter = page.getByRole("meter", { name: "Signal strength" });
    await expect(meter).toHaveAttribute("aria-valuetext", "Warmer");
    await expect(page.getByText("Warmer", { exact: true })).toBeVisible();
    await expect(page.locator(".recharts-line-curve")).toHaveCount(1);
    await expect(page.getByText("Over the last 30 seconds the signal got stronger.")).toBeVisible();
    await expect(page.getByRole("checkbox", { name: /out loud/ })).not.toBeChecked();
    await expectNoAxeViolations(page);
    expectClean(mocked); // Recharts included: no CSP errors

    const stop = page.getByRole("button", { name: "Stop" });
    await stop.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByText("Stopped. Nothing from this session was kept.")).toBeVisible();
    await expect.poll(() => mocked.locatorClosed()).toBe(true);
  });

  test("leaving the screen closes the locator's connection", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await toLocator(page, mocked);
    await mocked.pushReadings(READINGS.slice(0, 4));
    expect(mocked.locatorClosed()).toBe(false);
    await nav(page).getByRole("button", { name: "Results" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Results" })).toBeVisible();
    await expect.poll(() => mocked.locatorClosed()).toBe(true);
  });

  test("the unstable message replaces the words, and the backend's refusal is shown", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await toLocator(page, mocked);
    await mocked.pushReadings([
      {
        ...READINGS[6],
        trend: null,
        unstable: true,
        message: "The signal is jumping around. Move more slowly and hold the laptop still.",
        note: "Wi-Fi readings update every few seconds, so move slowly and pause at each spot.",
      },
    ]);
    await expect(page.getByText("Warmer", { exact: true })).toHaveCount(0);
    await expect(page.getByText(/Wi-Fi readings update every few seconds/)).toBeVisible();
    await expectNoAxeViolations(page);
    await mocked.pushReadings([{ error: "That item isn't in the latest nearby check. Run the nearby check again." }]);
    await expect(page.getByText(/isn't in the latest nearby check/)).toBeVisible();
    await expectNoAxeViolations(page);
  });
});

test.describe("Report screen", () => {
  test("create, preview inline, download, a checked timestamp, and a link to the message", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await toResults(page, mocked);
    await openPage(page, "Report");
    await expectNoAxeViolations(page);
    await page.getByRole("button", { name: "Create report" }).click();
    await expect(page.getByTitle("Report preview")).toHaveAttribute("src", /\?inline=true#/);
    await expect(page.getByRole("link", { name: "Download report bundle" })).toBeVisible();
    await expect(page.getByRole("link", { name: "PDF", exact: true })).toBeVisible();
    await expect(page.getByText("Checked: this PDF matches its timestamp.")).toBeVisible();
    expect(mocked.verifyCalls()).toBe(1);

    await page.getByRole("button", { name: "Open Handover" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Handover" })).toBeFocused();
    await expectNoAxeViolations(page);
    expectClean(mocked);
  });

  test("a timestamp that wasn't requested is never promised, and the outcome says so", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT, {
      report: {
        pdf: "roomcheck-report-20261103-132509.pdf",
        sha256_file: "roomcheck-report-20261103-132509.sha256",
        tsr: null,
        sha256: VERIFIED.sha256,
        timestamped_at: null,
        timestamp_message: null,
        explanations: RESULT_AI_OFF.explanations,
        ai: { state: "not_requested", reason: null },
        timestamp: { state: "not_requested", reason: null },
      },
    });
    mocked.setSetup(SETUP_NO_AI); // no API key in this build
    await toResults(page, mocked);
    await openPage(page, "Report");
    const stamp = page.getByRole("checkbox", { name: "Trusted timestamp" });
    await expect(stamp).toBeChecked();
    // No API key in this build: the AI choice isn't offered at all.
    await expect(page.getByRole("checkbox", { name: "AI explanations" })).toHaveCount(0);
    await stamp.focus();
    await page.keyboard.press("Space");
    await expect(stamp).not.toBeChecked();
    await page.getByRole("button", { name: "Create report" }).click();
    const outcomes = page.getByRole("region", { name: "What happened" });
    await expect(outcomes).toContainText("Trusted timestampNot requested");
    await expect(page.getByText("This report has no trusted timestamp.")).toBeVisible();
    // Worded for a report with no timestamp: it never says "since it was timestamped".
    await expect(page.getByText(/Without a timestamp, nothing shows when this report was made/)).toBeVisible();
    await expect(page.getByText(/since it was timestamped/)).toHaveCount(0);
    expect(mocked.verifyCalls()).toBe(0);
    await expectNoAxeViolations(page);
  });
});

test.describe("Verify screen", () => {
  async function pick(page: Page) {
    await page.getByLabel(/^Report PDF/).setInputFiles({ name: "r.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF made-up") });
    await page.getByLabel(/^Timestamp file/).setInputFiles({ name: "r.tsr", mimeType: "application/octet-stream", buffer: Buffer.from("token") });
  }

  test("checks a genuine report, and rejects a tampered one", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await page.goto("/");
    await openPage(page, "Verify a report");
    const check = page.getByRole("button", { name: "Check the report" });
    await expect(check).toHaveAttribute("aria-disabled", "true");
    await expect(page.getByText("Choose the report's PDF to check it.")).toBeVisible();
    await expectNoAxeViolations(page);
    await pick(page);
    await expect(check).toHaveAttribute("aria-disabled", "false");
    await check.click();
    await expect(page.getByRole("heading", { name: "Verified" })).toBeVisible();
    await expectNoAxeViolations(page);

    mocked.setVerify(TAMPERED);
    await pick(page);
    await check.click();
    await expect(page.getByText("Files don't match")).toBeVisible();
    await expect(page.getByText("Doesn't match this PDF")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Verified" })).toHaveCount(0);
    await expectNoAxeViolations(page);
    expectClean(mocked); // the files went to RoomCheck's own backend only
  });

  test("works with the keyboard alone", async ({ page }) => {
    await mockBackend(page, RESULT);
    await page.goto("/");
    await openPage(page, "Verify a report");
    await pick(page);
    const check = page.getByRole("button", { name: "Check the report" });
    await check.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { name: "Verified" })).toBeVisible();
  });
});

test.describe("Part B at 200% zoom and narrow screens", () => {
  for (const width of [640, 320]) {
    test(`Nearby, Locator, Report and Verify reflow at ${width} px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 700 });
      const mocked = await mockBackend(page, RESULT);
      await toResults(page, mocked);
      await nav(page).getByRole("button", { name: "Nearby" }).click();
      await expectNoHorizontalScroll(page);
      await page.getByRole("button", { name: "Locate signal" }).last().click();
      await mocked.locator();
      await mocked.pushReadings(READINGS);
      await expect(page.getByText("Warmer", { exact: true })).toBeVisible();
      await expectNoHorizontalScroll(page);
      await openPage(page, "Report");
      await page.getByRole("button", { name: "Create report" }).click();
      await expect(page.getByText("Checked: this PDF matches its timestamp.")).toBeVisible();
      await expectNoHorizontalScroll(page);
      await openPage(page, "Verify a report");
      await expectNoHorizontalScroll(page);
      await expectNoAxeViolations(page);
    });
  }
});
