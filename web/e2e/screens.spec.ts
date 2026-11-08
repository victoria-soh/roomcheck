import { expect, test, type Page } from "@playwright/test";

import { BLUETOOTH_OFF, CAM_FINDING, CAM_SUBJECT, DONE_WITH_RESULT, FINISHED, LISTENING, LIVE, MIDWAY, NETWORK_NAME, NOTHING_FOUND, NOT_TIMESTAMPED, NVD_SKIPPED, RESULT, SETUP_CABLE, SETUP_MISSING, SETUP_NO_AI, SETUP_OFFLINE, SETUP_READY, SETUP_WITH_AI, SLOW, STARTING, snapshot } from "../src/test/fixtures";
import {
  expectNoAxeViolations,
  expectNoHorizontalScroll,
  isPhoneLayout,
  mockBackend,
  openPage,
  START_BUTTON,
  TRANSITION_MS,
  type Mocked,
} from "./mock";

type Answer = "Yes, I have permission" | "No, or I'm not sure";

async function startScan(page: Page, answer: Answer = "No, or I'm not sure") {
  await page.goto("/");
  await page.getByRole("radio", { name: answer, exact: true }).check();
  await page.getByRole("button", { name: START_BUTTON }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Checking your room" })).toBeVisible();
}

async function toResults(page: Page, mocked: Mocked) {
  await startScan(page);
  await mocked.socket();
  await mocked.send(LIVE);
  await page.getByRole("button", { name: "See your results" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Results" })).toBeVisible();
}

test.describe("Start screen", () => {
  test("passes the accessibility checks, closed and with the details open", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await page.goto("/");
    await expectNoAxeViolations(page);
    await page.getByRole("button", { name: "What counts?" }).click();
    await expect(page.getByText(/may be against the law in many places/)).toBeVisible();
    await expectNoAxeViolations(page);
    await page.getByRole("radio", { name: "No, or I'm not sure", exact: true }).check();
    await expectNoAxeViolations(page);
    expect(mocked.outside).toEqual([]);
    expect(mocked.cspErrors).toEqual([]);
    expect(mocked.consoleErrors).toEqual([]); // e.g. no 404 for a missing icon
  });

  test("nothing is chosen at first; Start with no answer says why, only then", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await page.goto("/");
    for (const radio of await page.getByRole("radio").all()) await expect(radio).not.toBeChecked();
    await expect(page.getByText("Choose an answer to continue.")).toHaveCount(0);
    const button = page.getByRole("button", { name: "Start the check" });
    await button.click();
    await expect(page.getByText("Choose an answer to continue.")).toBeVisible();
    await expect(button).toHaveAccessibleDescription("Choose an answer to continue.");
    await expect(page.getByRole("radio", { name: "Yes, I have permission", exact: true })).toBeFocused();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Check your room's Wi-Fi and devices");
    expect(mocked.scanBodies).toEqual([]);
    await expectNoAxeViolations(page);
  });

  test("Yes asks for a consented scan; No, or I'm not sure, listens only", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await startScan(page, "Yes, I have permission");
    await expect(page.getByText("Example-Home · With permission", { exact: true })).toBeVisible();
    await page.goto("/");
    await startScan(page, "No, or I'm not sure");
    await expect(page.getByText("Example-Home · Listening only", { exact: true })).toBeVisible();
    // No stay chosen: "other", each rule's default next steps.
    expect(mocked.scanBodies).toEqual([
      { consent: true, stay: "other" },
      { consent: false, stay: "other" },
    ]);
  });

  test("works with the keyboard alone, with a visible focus ring", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await page.goto("/");
    await page.keyboard.press("Tab"); // skip link
    await expect(page.getByRole("link", { name: "Skip to main content" })).toBeFocused();
    await page.keyboard.press("Enter"); // past the top bar, to the page itself
    // The connection bar's Check again, then What counts?, before the answers.
    for (const target of [page.getByRole("button", { name: "Check again" }), page.getByRole("button", { name: "What counts?" })]) {
      await page.keyboard.press("Tab");
      await expect(target).toBeFocused();
    }
    await page.keyboard.press("Enter"); // opens the explanation from the keyboard
    await expect(page.getByText(/may be against the law in many places/)).toBeVisible();
    await page.keyboard.press("Tab");
    const yes = page.getByRole("radio", { name: "Yes, I have permission", exact: true });
    await expect(yes).toBeFocused();
    // The ring is drawn round the whole row, 3 px in dark ink and set off from it, so it never
    // looks like the teal selected state.
    await page.waitForTimeout(TRANSITION_MS);
    const row = (el: Element) => {
      const s = getComputedStyle(el.closest("label") as Element);
      return { ring: `${s.outlineStyle} ${s.outlineWidth} ${s.outlineColor}`, border: s.borderColor };
    };
    expect((await yes.evaluate(row)).ring).toBe("solid 3px rgb(14, 43, 40)");
    await page.keyboard.press("Space");
    await page.waitForTimeout(TRANSITION_MS);
    const chosen = await yes.evaluate(row);
    expect(chosen.border).toBe("rgb(11, 107, 104)");
    expect(chosen.ring).not.toContain("27, 111, 104");
    // Then where you're staying (optional, one tab stop), then the start button.
    await page.keyboard.press("Tab");
    await expect(page.getByRole("radio", { name: "Short stay", exact: true })).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(page.getByRole("button", { name: "Start full check" })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { level: 1, name: "Checking your room" })).toBeFocused();
    expect(mocked.scanBodies).toEqual([{ consent: true, stay: "other" }]);
  });

  for (const [state, setup] of [
    ["all ready", SETUP_READY],
    ["some checks missing", SETUP_MISSING],
  ] as const) {
    test(`everything through the start button fits at 1280 by 800 (${state})`, async ({ page }) => {
      await page.setViewportSize({ width: 1280, height: 800 });
      const mocked = await mockBackend(page, RESULT);
      mocked.setSetup(setup);
      await page.goto("/");
      await expect(page.getByRole("region", { name: "Is this laptop ready?" })).toContainText(NETWORK_NAME);
      for (const name of ["Yes, I have permission", "No, or I'm not sure"]) {
        await expect(page.getByRole("radio", { name, exact: true })).toBeInViewport({ ratio: 1 });
      }
      const button = page.getByRole("button", { name: "Start the check" });
      await expect(button).toBeInViewport({ ratio: 1 });
      await expect(page.getByText("Stay connected to this Wi-Fi")).toBeInViewport({ ratio: 1 });
      // Pressed with no answer: the instruction appears below the options, and the button
      // stays in view.
      await button.click();
      const instruction = await page.getByText("Choose an answer to continue.").boundingBox();
      const no = await page.getByText("No, or I'm not sure", { exact: true }).boundingBox();
      expect(instruction!.y).toBeGreaterThan(no!.y);
      await expect(button).toBeInViewport({ ratio: 1 });
    });
  }

  test("readiness: missing items say what's limited and never block the start", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    mocked.setSetup(SETUP_MISSING);
    await page.goto("/");
    const strip = page.getByRole("region", { name: "Is this laptop ready?" });
    await expect(strip).toContainText(`Connected to ${NETWORK_NAME}`);
    await expect(strip.getByText("Checking a different network?")).toBeVisible(); // a problem, so offered
    await expect(strip.getByText("Missing", { exact: true })).toHaveCount(2);
    await expect(strip).toContainText(
      "These checks will be limited: the tracker check, checking which services devices offer.",
    );
    await expect(strip.getByRole("button", { name: /Continue/ })).toHaveCount(0);
    await expectNoAxeViolations(page);
    await page.getByRole("radio", { name: "Yes, I have permission", exact: true }).check();
    await page.getByRole("button", { name: "Start check (some parts limited)" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Checking your room" })).toBeVisible();
    expect(mocked.scanBodies).toEqual([{ consent: true, stay: "other" }]);
  });

  test("readiness: not connected, and by cable", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    mocked.setSetup(SETUP_OFFLINE);
    await page.goto("/");
    const strip = page.getByRole("region", { name: "Is this laptop ready?" });
    await expect(strip).toContainText("Not connected to a network");
    await expect(strip).toContainText("Connect to the room's Wi-Fi first");
    await expectNoAxeViolations(page);
    mocked.setSetup(SETUP_CABLE);
    await strip.getByRole("button", { name: "Check again" }).click();
    await expect(strip).toContainText("Connected by cable");
    await expect(strip.getByText("Checking a different network?")).toHaveCount(0); // all set
  });

  test("the network name is shown on the page but never sent anywhere", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await page.goto("/");
    await expect(page.getByText(`Connected to ${NETWORK_NAME}`, { exact: true })).toBeVisible();
    await startScan(page, "Yes, I have permission");
    await mocked.send(LIVE);
    await page.getByRole("button", { name: "See your results" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Results" })).toBeVisible();
    expect(mocked.sent().filter((x) => x.includes(NETWORK_NAME))).toEqual([]);
    expect(mocked.outside).toEqual([]);
  });

  test("Start's footer opens Help's privacy list, which follows the configuration", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    mocked.setSetup(SETUP_NO_AI);
    await page.goto("/");
    await expect(page.getByText("Results are clues, not proof. Everything runs on this laptop.", { exact: false })).toBeVisible();
    await expect(page.getByText(/^AI explanations \(off unless/)).toHaveCount(0); // not on Start
    await page.getByRole("button", { name: "what's sent" }).click();
    await expect(page.getByRole("heading", { level: 2, name: "What's sent" })).toBeFocused();
    const trust = page.getByRole("region", { name: "What's sent" });
    await expect(trust).toContainText("product names are sent to NIST");
    await expect(trust).toContainText("is sent to freetsa.org.");
    // Every outside call is listed, AI too; below, whether it's on in this setup.
    await expect(trust).toContainText("off unless you add an Anthropic API key");
    await expect(trust).toContainText("AI is off in this setup");
    await expect(trust).toContainText("never sent anywhere");
    mocked.setSetup(SETUP_WITH_AI);
    await page.goto("/");
    await page.getByRole("button", { name: "what's sent" }).click();
    await expect(trust).toContainText("AI is on in this setup");
  });

  for (const width of [1280, 375]) {
    test(`passes axe and works by keyboard at ${width} px`, async ({ page }) => {
      await page.setViewportSize({ width, height: width === 1280 ? 800 : 740 });
      const mocked = await mockBackend(page, RESULT);
      mocked.setSetup(SETUP_MISSING);
      await page.goto("/");
      await expectNoHorizontalScroll(page);
      await expectNoAxeViolations(page);
      for (const summary of await page.locator("details:not([open]) > summary").elementHandles()) await summary.click();
      await page.getByRole("button", { name: "What counts?" }).click();
      await expectNoAxeViolations(page);
      await page.getByRole("radio", { name: "No, or I'm not sure", exact: true }).focus();
      await page.keyboard.press("Space");
      // Listening only: asking the host for permission, then where you're staying.
      await page.keyboard.press("Tab");
      await expect(page.getByText("Ask your host for permission", { exact: true })).toBeFocused();
      await page.keyboard.press("Tab");
      await expect(page.getByRole("radio", { name: "Short stay", exact: true })).toBeFocused();
      await page.keyboard.press("Tab");
      // Something is missing, so the one start button says the check will be limited.
      await expect(page.getByRole("button", { name: "Start check (some parts limited)" })).toBeFocused();
      await expectNoAxeViolations(page);
      await page.keyboard.press("Enter");
      await expect(page.getByRole("heading", { level: 1, name: "Checking your room" })).toBeFocused();
      expect(mocked.scanBodies).toEqual([{ consent: false, stay: "other" }]);
    });
  }
});

function stepRow(page: Page, name: string) {
  return page.locator("ol[aria-label='Steps'] > li").filter({ hasText: name });
}

// The one header: the brand row's tools, and (after a check) the Main row.
function nav(page: Page) {
  return page.getByRole("banner");
}

const HANDOVER = /^Handover(\s*,\s*\d+ open tasks?)?$/;

test.describe("Scanning screen", () => {
  test("a full check: tasks in start order, a nearby detail, and quiet heartbeats stay live", async ({ page }) => {
    await page.clock.install();
    const mocked = await mockBackend(page, RESULT);
    await startScan(page, "Yes, I have permission");
    await mocked.socket();
    // A consented check's start: services is waiting (not skipped) while listening and nearby run.
    const start = snapshot({
      steps: STARTING.steps.map((s) =>
        s.key === "services" ? { key: "services", status: "upcoming", problems: [], detail: null } : s,
      ),
      total_steps: 5,
    });
    await mocked.send([start]);
    const names = await page.locator("ol[aria-label='Steps'] > li > div > p:first-child").allTextContents();
    expect(names).toEqual([
      "Listening for devices",
      "Looking at nearby Wi-Fi and Bluetooth",
      "Checking which services devices offer",
      "Checking the router",
      "Preparing your results",
    ]);
    await expect(stepRow(page, "Looking at nearby Wi-Fi and Bluetooth")).toContainText("Scanning nearby Wi-Fi…");
    // 30 s of nothing changing, with a heartbeat every 5 s as the server sends them: still live.
    for (let i = 0; i < 6; i++) {
      await page.clock.runFor(5_000);
      await mocked.send([{ ...start, elapsed_seconds: 3 + 5 * (i + 1) }]);
    }
    await expect(page.getByText(/Live connection interrupted/)).toHaveCount(0);
    await expect(page.getByText("Updates have stopped", { exact: true })).toHaveCount(0);
    expect(mocked.connections()).toBe(1);
    await mocked.send([
      {
        ...start,
        version: 6,
        steps: start.steps.map((s) => (s.key === "nearby" ? { ...s, detail: { wifi: 12 } } : s)),
      },
    ]);
    await expect(stepRow(page, "Looking at nearby Wi-Fi and Bluetooth")).toContainText("Heard 12 nearby networks");
    expect(mocked.scanBodies).toEqual([{ consent: true, stay: "other" }]);
    await expectNoAxeViolations(page);
  });

  test("heading from the real tasks, tasks done, live details and failures, accessibly", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await startScan(page);
    await mocked.socket();
    await mocked.send([STARTING]);
    await expect(page.getByRole("heading", { level: 2, name: "Scan progress" })).toBeVisible();
    await expect(page.locator("#current-task")).toHaveText("Scanning devices and nearby signals");
    await expect(page.getByText("Waiting for device results")).toBeVisible();
    await expect(stepRow(page, "Checking which services devices offer")).toContainText("Not checked");
    await expect(stepRow(page, "Checking which services devices offer")).toContainText(
      "Needs permission to check the network",
    );
    await mocked.send([LISTENING]);
    await expect(stepRow(page, "Listening for devices")).toContainText("Heard 3 devices so far");
    await expect(stepRow(page, "Looking at nearby Wi-Fi and Bluetooth")).toContainText("Heard 12 nearby networks");
    await expect(page.getByText("3 devices found so far")).toBeVisible();
    await expect(page.getByText(/^1 of 5 tasks done · Elapsed 0:4\d · usually about 2 minutes$/)).toBeVisible();
    await expectNoAxeViolations(page);

    await mocked.send([MIDWAY]);
    await expect(page.locator("#current-task")).toHaveText("Checking the router");
    await expect(page.getByText(/^3 of 5 tasks done · /)).toBeVisible();
    await expect(stepRow(page, "Looking at nearby Wi-Fi and Bluetooth")).toContainText("Couldn't finish");
    await expect(stepRow(page, "Looking at nearby Wi-Fi and Bluetooth")).toContainText(BLUETOOTH_OFF);
    // "The rest of the check carries on." sits inside the note of the task that couldn't finish.
    await expect(stepRow(page, "Looking at nearby Wi-Fi and Bluetooth")).toContainText("The rest of the check carries on.");
    await expect(page.getByText("The rest of the check carries on.")).toHaveCount(1);
    await expect(stepRow(page, "Checking the router")).not.toContainText(NVD_SKIPPED);
    // The status column sits at the card's right edge.
    const card = page.getByRole("region", { name: "Scan progress" });
    const cardBox = (await card.boundingBox())!;
    const status = (await stepRow(page, "Listening for devices").getByText("Done", { exact: true }).boundingBox())!;
    expect(cardBox.x + cardBox.width - (status.x + status.width)).toBeLessThan(40);
    await expect(page.locator("body")).not.toContainText(/\d+ ?%/);
    await expectNoAxeViolations(page);
    await expectNoHorizontalScroll(page);
    expect(mocked.outside).toEqual([]);
    expect(mocked.cspErrors).toEqual([]);
  });

  test("past the estimate it says it's taking longer", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await startScan(page);
    await mocked.send([SLOW]);
    await expect(page.getByText(/Taking longer than usual\. Larger networks can take a few more minutes\./)).toBeVisible();
    await expect(page.getByText(/usually about 2 minutes/)).toHaveCount(0);
  });

  test("connection: a quiet line while polls work, the panel after 20 s without any update", async ({ page }) => {
    await page.clock.install();
    const mocked = await mockBackend(page, RESULT);
    mocked.setPoll({ ...MIDWAY, version: 11 });
    await startScan(page);
    await mocked.send([MIDWAY]);
    await mocked.drop();
    await page.clock.runFor(3_000);
    const quiet = page.locator("#current-task ~ p").filter({ hasText: "Live connection interrupted" });
    await expect(quiet).toContainText("Checking for updates automatically. Last updated");
    await expect(page.getByRole("button", { name: "Retry connection" })).toHaveCount(0);
    await expectNoAxeViolations(page);

    mocked.setPoll("fail"); // nothing answers now
    await page.clock.runFor(22_000);
    await expect(page.getByText("Updates have stopped", { exact: true })).toBeVisible();
    await expect(page.getByText(/^Last update received \d+ seconds ago\.$/)).toBeVisible();
    await expect(page.getByText("4 devices found at last update")).toBeVisible();
    await expect(page.getByText(/still running/)).toHaveCount(0);
    await expect(stepRow(page, "Checking the router")).toContainText("Running");
    await expectNoAxeViolations(page);

    // Retry from the keyboard, and the live connection is back.
    const retry = page.getByRole("button", { name: "Retry connection" });
    await retry.focus();
    const before = mocked.connections();
    await page.keyboard.press("Enter");
    await expect.poll(() => mocked.connections()).toBeGreaterThan(before);
    await mocked.send([{ ...MIDWAY, version: 20 }]);
    await expect(page.getByText("Updates have stopped", { exact: true })).toHaveCount(0);
  });

  test("a poll that shows the check finished goes to the completion state", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await startScan(page);
    await mocked.send([MIDWAY]);
    mocked.setPoll(DONE_WITH_RESULT(RESULT));
    await mocked.drop();
    await expect(page.getByRole("heading", { level: 2, name: "Check complete" })).toBeFocused();
  });

  test("completion: a summary, focus on the heading, and no jumping away", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await startScan(page);
    await mocked.send(LIVE);
    const done = page.getByRole("heading", { level: 2, name: "Check complete" });
    await expect(done).toBeFocused();
    await expect(page.getByText("3 devices · 1 high, 3 medium findings")).toBeVisible();
    await expect(page.getByRole("heading", { level: 1, name: "Checking your room" })).toBeVisible(); // still here
    await expectNoAxeViolations(page);
    await page.keyboard.press("Tab");
    await expect(page.getByRole("button", { name: "See your results" })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { level: 1, name: "Results" })).toBeFocused();
  });

  test("top bar on a first check: only Verify, and it works during the check", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await startScan(page);
    await mocked.send([MIDWAY]);
    // Scanning: "Check in progress" and Help, and no navigation row yet.
    await expect(page.getByRole("navigation", { name: "Main" })).toHaveCount(0);
    await expect(page.getByRole("navigation", { name: "Help and tools" }).getByRole("button")).toHaveText(["Help"]);
    await expect(nav(page).getByText("Check in progress")).toBeVisible();
    await expect(page.getByText("The other pages open when the check is done")).toHaveCount(0);
    await nav(page).getByRole("button", { name: "Help", exact: true }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Help" })).toBeVisible();
    await nav(page).getByRole("button", { name: "Check in progress", exact: true }).click();
    await expect(page.locator("#current-task")).toHaveText("Checking the router"); // still live
  });

  test("top bar on a later check: the previous results stay usable, labelled with their date", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await startScan(page);
    await mocked.send(LIVE);
    await page.getByRole("button", { name: "See your results" }).click();
    // The header's New check is the only way to start another: it asks first.
    await page.getByRole("button", { name: "New check", exact: true }).click();
    await page.getByRole("button", { name: "Start without saving" }).click();
    await page.getByRole("radio", { name: "No, or I'm not sure", exact: true }).check();
    await page.getByRole("button", { name: START_BUTTON }).click();
    await expect.poll(() => mocked.connections()).toBeGreaterThan(1); // the new check's socket
    await mocked.send([MIDWAY]);
    await expect(nav(page).getByText("Check in progress")).toBeVisible(); // text here: you're on the check
    const names = await page.getByRole("navigation", { name: "Main" }).getByRole("button").allTextContents();
    const expected = (await isPhoneLayout(page))
      ? ["Results", "Nearby", "Handover", "More"]
      : ["Results", "Nearby", "Handover", "Compare", "Report", "Verify a report"];
    expect(names.map((n) => n.replace(/\s*·\s*\d+.*$/, ""))).toEqual(expected);
    await nav(page).getByRole("button", { name: "Results", exact: true }).click();
    await expect(page.getByText(/^These are your previous results, from .*2026.*\. A new check is running\.$/)).toBeVisible();
    await expect(page.getByRole("region", { name: "5 things to look at" })).toBeVisible();
    await expectNoAxeViolations(page);
    await page.getByRole("button", { name: "Back to the current check" }).click();
    await expect(page.locator("#current-task")).toHaveText("Checking the router");
  });

  test("Cancel is a proper button beside the stay-connected line, at least 24 by 24 px", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await startScan(page);
    await mocked.send([MIDWAY]);
    const cancel = page.getByRole("button", { name: "Cancel check" });
    const box = await cancel.boundingBox();
    expect(box && box.width >= 24 && box.height >= 24).toBe(true);
    // Beside the stay-connected line: the same row (it wraps under it on a phone).
    await expect(cancel.locator("xpath=ancestor::div[1]")).toContainText(
      "Stay connected to this Wi-Fi and keep your laptop in the room.",
    );
    await cancel.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("button", { name: "Keep checking" })).toBeFocused();
    await expectNoAxeViolations(page);
    await page.keyboard.press("Enter");
    await expect(cancel).toBeFocused();
    await page.keyboard.press("Enter");
    await page.keyboard.press("Tab");
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { level: 1, name: "Check cancelled" })).toBeFocused();
    expect(mocked.cancels()).toBe(1);
  });

  test("the spinner stops under reduced motion, and the word is always there", async ({ page }) => {
    await page.emulateMedia({ reducedMotion: "reduce" });
    const mocked = await mockBackend(page, RESULT);
    await startScan(page);
    await mocked.send([MIDWAY]);
    const spinner = stepRow(page, "Checking the router").locator(".motion-safe\\:animate-spin");
    await expect(spinner).toHaveCount(1);
    expect(await spinner.evaluate((el) => getComputedStyle(el).animationName)).toBe("none");
    await expect(stepRow(page, "Checking the router")).toContainText("Running");
    await page.emulateMedia({ reducedMotion: "no-preference" });
    expect(await spinner.evaluate((el) => getComputedStyle(el).animationName)).not.toBe("none");
  });

  test("a failed scan says what happened and what to do", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await startScan(page);
    await mocked.send([
      snapshot({
        state: "failed",
        current_step: null,
        current_index: null,
        error: "The check stopped because of an unexpected problem. Restart RoomCheck, then try again.",
        version: 5,
      }),
    ]);
    await expect(page.getByRole("heading", { level: 1, name: "The check didn't finish" })).toBeVisible();
    await expect(page.getByText(/Restart RoomCheck, then try again\./)).toBeVisible();
    await expectNoAxeViolations(page);
    await page.getByRole("button", { name: "Start again" }).click();
    await expect(page.getByRole("heading", { level: 1, name: /Check your room/ })).toBeFocused();
  });
});

test.describe("Results screen", () => {
  test("summary, then the four questions with their status lines, accessibly", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await toResults(page, mocked);
    await expect(page.getByRole("region", { name: "5 things to look at" })).toBeVisible();
    const groups = await page.getByRole("heading", { level: 2 }).allTextContents();
    expect(groups.slice(0, 5)).toEqual([
      "5 things to look at",
      "Is anything watching?",
      "Can someone else control things here?",
      "Can you trust this Wi-Fi?",
      "What's changed since move-in?",
    ]);
    await expect(page.getByRole("region", { name: "Can someone else control things here?" })).toContainText("Not detected by the checks that ran");
    // One section at the bottom for what ran, what didn't and what no check can see.
    await expect(page.getByRole("region", { name: "Network health" })).toHaveCount(0);
    await expect(page.locator("#coverage-limits")).toContainText("Coverage and limits");
    await expectNoAxeViolations(page);

    // With every disclosure open, too: coverage, evidence and the camera guidance.
    for (const summary of await page.locator("details:not([open]) > summary").elementHandles()) await summary.click();
    await expect(page.getByText("Runs a video-streaming server (RTSP) (port 554)")).toBeVisible();
    await expect(page.locator("#coverage-limits").getByText("Not checked: the second-address-server check took too long and was stopped")).toBeVisible();
    await expect(page.getByRole("heading", { level: 3, name: "What this scan can't see" })).toBeVisible();
    await expectNoAxeViolations(page);
    expect(mocked.outside).toEqual([]);
    expect(mocked.cspErrors).toEqual([]);
  });

  test("the evidence opens from the keyboard", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await toResults(page, mocked);
    const summary = page.getByText("Evidence and details").first();
    await summary.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByText("Answered a camera discovery request (ONVIF video transmitter)", { exact: true })).toBeVisible();
  });

  test("nothing found still shows what the scan can't see", async ({ page }) => {
    const mocked = await mockBackend(page, NOTHING_FOUND);
    await toResults(page, mocked);
    const banner = page.getByRole("region", { name: "Not detected by the checks that ran" });
    await expect(banner).toBeVisible();
    await expect(banner).toContainText(/\d+ of \d+ checks ran/); // the router checks were limited
    // Nothing to read above it: Coverage and limits is open, with what this scan can't see.
    await expect(page.locator("#coverage-limits")).toHaveAttribute("open", "");
    await expect(page.getByRole("heading", { level: 3, name: "What this scan can't see" })).toBeVisible();
    await expect(page.locator("body")).not.toContainText(/\bsafe\b/i);
    await expectNoAxeViolations(page);
  });
});

test.describe("Results screen at laptop and phone sizes", () => {
  for (const [name, size] of [
    ["laptop", { width: 1280, height: 800 }],
    ["phone", { width: 390, height: 844 }],
  ] as const) {
    test(`the first screenful answers what, what's missing and what next (${name})`, async ({ page }) => {
      await page.setViewportSize(size);
      const mocked = await mockBackend(page, RESULT);
      await toResults(page, mocked);
      const banner = page.getByRole("region", { name: "5 things to look at" });
      if (name === "laptop") {
        await expect(banner.getByRole("button", { name: "Review camera-like device" })).toBeInViewport();
        await expect(banner.getByRole("button", { name: "See what didn't" })).toBeInViewport();
      }
      await expectNoHorizontalScroll(page);
      await expectNoAxeViolations(page);
    });

    test(`works with the keyboard alone (${name})`, async ({ page }) => {
      await page.setViewportSize(size);
      const mocked = await mockBackend(page, RESULT);
      await toResults(page, mocked);
      const banner = page.getByRole("region", { name: "5 things to look at" });
      // A partial check: the link opens the coverage table and lands on it.
      await banner.getByRole("button", { name: "See what didn't" }).focus();
      await page.keyboard.press("Enter");
      await expect(page.locator("#coverage-limits").getByText("Not checked: the second-address-server check took too long and was stopped")).toBeVisible();
      await expect(page.locator("#coverage-limits > summary")).toBeFocused();
      // Review finding lands on the camera's card.
      await banner.getByRole("button", { name: "Review camera-like device" }).focus();
      await page.keyboard.press("Enter");
      const cam = page.getByRole("article", { name: /^Likely camera/ });
      await expect(cam).toBeFocused();
      // Every card is under its question: no filters to reset.
      await expect(page.getByRole("article")).toHaveCount(5);
      // Recognition: Host's, then the follow-up, from the keyboard.
      await cam.getByRole("radio", { name: "Host's" }).focus();
      await page.keyboard.press("Space");
      const yes = cam.getByRole("group", { name: "Has the host confirmed this?" }).getByRole("radio", { name: "Yes" });
      await yes.focus();
      await page.keyboard.press("Space");
      await expect(cam).toContainText("Host's, confirmed");
      // A name, then Enter to save it.
      await cam.getByRole("textbox", { name: "Your name for it (optional)" }).fill("Hallway camera");
      await page.keyboard.press("Enter");
      await expect(page.getByRole("article", { name: "Likely camera" })).toContainText("Hallway camera · Host's, confirmed");
      await expectNoAxeViolations(page);
      expect(mocked.layer6Calls.filter((c) => c.url !== "/api/baseline").map((c) => c.body)).toEqual([
        { subject: CAM_SUBJECT, answer: "landlord", confirmed: null },
        { subject: CAM_SUBJECT, answer: "landlord", confirmed: true },
        { subject: CAM_SUBJECT, name: "Hallway camera" },
      ]);
    });
  }

  test("Draft a message opens the handover message, with this item in it", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await toResults(page, mocked);
    await page.getByRole("article", { name: /^Likely camera/ }).getByRole("button", { name: "Draft a message to the host" }).click();
    await expect(page.locator("#host-message > summary")).toBeFocused();
    await expect(page.locator("#host-message")).toHaveAttribute("open", "");
    await expect(page.getByRole("textbox", { name: "Message" })).toHaveValue(/looks like a camera/);
  });
});

test.describe("Logo, favicon and wordmark font", () => {
  test("the header shows the mark and the Saira wordmark, and every font is served locally", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    const fonts: string[] = [];
    page.on("request", (r) => {
      if (/\.woff2?(\?|$)/.test(r.url())) fonts.push(r.url());
    });
    await page.goto("/");
    const header = page.getByRole("banner");
    const mark = header.locator("svg[data-logo='mark']");
    await expect(mark).toBeVisible();
    await expect(mark).toHaveAttribute("aria-hidden", "true");
    expect(await mark.boundingBox()).toMatchObject({ width: 28, height: 28 });
    const word = header.getByText("RoomCheck", { exact: true });
    await expect(word).toHaveCSS("font-family", /Saira/);
    await expect(word).toHaveCSS("font-weight", "600");
    await expect(word).toHaveCSS("color", "rgb(14, 43, 40)");
    await page.evaluate(() => document.fonts.ready);
    expect(await page.evaluate(() => document.fonts.check('600 21px "Saira"'))).toBe(true);
    // Every font came from RoomCheck itself; nothing from Google Fonts or anywhere else.
    expect(fonts.some((u) => /saira-latin-600-normal/.test(u))).toBe(true);
    expect(fonts.every((u) => u.startsWith("http://127.0.0.1:4173/"))).toBe(true);
    expect(mocked.outside).toEqual([]);
    expect(mocked.cspErrors).toEqual([]);
    expect(mocked.consoleErrors).toEqual([]);
    // Headings in Plus Jakarta Sans, body text in Atkinson Hyperlegible Next, both bundled.
    await expect(page.getByRole("heading", { level: 1 })).toHaveCSS("font-family", /^"Plus Jakarta Sans"/);
    await expect(page.locator("body")).toHaveCSS("font-family", /^"Atkinson Hyperlegible Next"/);
    expect(await page.evaluate(() => document.fonts.check('700 28px "Plus Jakarta Sans"'))).toBe(true);
    expect(await page.evaluate(() => document.fonts.check('400 16px "Atkinson Hyperlegible Next"'))).toBe(true);
    expect(fonts.some((u) => /plus-jakarta-sans-latin-700-normal/.test(u))).toBe(true);
    expect(fonts.some((u) => /atkinson-hyperlegible-next-latin-400-normal/.test(u))).toBe(true);
  });

  test("the favicon set is linked and served by RoomCheck", async ({ page, request }) => {
    await mockBackend(page, RESULT);
    await page.goto("/");
    const links = await page.locator("link[rel~='icon'], link[rel='apple-touch-icon']").evaluateAll((els) =>
      els.map((e) => (e as HTMLLinkElement).getAttribute("href")),
    );
    expect(links).toEqual(["/favicon.ico", "/favicon.svg", "/favicon-32.png", "/favicon-16.png", "/apple-touch-icon.png"]);
    for (const [path, type] of [
      ["/favicon.ico", /icon/],
      ["/favicon.svg", /svg/],
      ["/favicon-16.png", /png/],
      ["/favicon-32.png", /png/],
      ["/favicon-48.png", /png/],
      ["/apple-touch-icon.png", /png/],
      ["/icon-512.png", /png/],
    ] as const) {
      const r = await request.get(path);
      expect(r.status(), path).toBe(200);
      expect(r.headers()["content-type"], path).toMatch(type);
    }
    const svg = await (await request.get("/favicon.svg")).text();
    expect(svg).toContain('fill="#1BA9A6"');
  });
});

test.describe("Recheck this and Help identify this", () => {
  for (const [name, size] of [
    ["laptop", { width: 1280, height: 800 }],
    ["phone", { width: 390, height: 844 }],
  ] as const) {
    test(`a Resolved task offers a recheck and shows what changed, by keyboard (${name})`, async ({ page }) => {
      await page.setViewportSize(size);
      const mocked = await mockBackend(page, RESULT);
      await toResults(page, mocked);
      await nav(page).getByRole("button", { name: HANDOVER }).click();
      const wps = page.getByRole("article", { name: "Ask for WPS to be turned off on the router" });
      await wps.getByText("Questions, steps and notes").click();
      await expect(wps.getByRole("button", { name: "Recheck this" })).toHaveCount(0);
      await wps.getByRole("radio", { name: "Resolved" }).focus();
      await page.keyboard.press("Space");
      const recheck = wps.getByRole("button", { name: "Recheck this" });
      await expect(recheck).toBeVisible();
      await recheck.focus();
      await page.keyboard.press("Enter");
      await expect(wps.getByText("Observed by RoomCheck")).toBeVisible();
      await expect(wps).toContainText("WPS is now off on that router.");
      await expectNoHorizontalScroll(page);
      await expectNoAxeViolations(page);
    });

    test(`Help identify this guides an Unknown device, by keyboard (${name})`, async ({ page }) => {
      await page.setViewportSize(size);
      const unknown = {
        ...RESULT,
        devices: RESULT.devices.map((d) => (d.id === CAM_FINDING.device_ref ? { ...d, vendor: null, fingerprint: null } : d)),
      };
      const mocked = await mockBackend(page, unknown);
      await toResults(page, mocked);
      const card = page.getByRole("article", { name: /^Likely camera/ });
      const summary = card.getByText("Help identify this");
      await summary.focus();
      await page.keyboard.press("Enter");
      await expect(card.getByText("1. Its clues")).toBeVisible();
      await expect(card).toContainText("Its maker is unknown.");
      await card.getByRole("textbox", { name: "Your name for it (optional)" }).fill("Hallway box");
      await card.getByRole("textbox", { name: "Note (optional)" }).fill("Above the door");
      await card.getByRole("button", { name: "Save name and note" }).focus();
      await page.keyboard.press("Enter");
      const named = page.getByRole("article", { name: "Likely camera" });
      await expect(named).toContainText("Hallway box");
      await named.getByRole("radio", { name: "Host's" }).focus();
      await page.keyboard.press("Space");
      await expect(named.getByRole("group", { name: "Has the host confirmed this?" })).toBeVisible();
      await expectNoHorizontalScroll(page);
      await expectNoAxeViolations(page);
      expect(mocked.layer6Calls.find((c) => c.url === "/api/names")?.body).toEqual({
        subject: CAM_SUBJECT,
        name: "Hallway box",
        note: "Above the door",
      });
    });
  }

  test("a nearby card's panel offers Find it under the locator's rules", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await toResults(page, mocked);
    await nav(page).getByRole("button", { name: "Nearby", exact: true }).click();
    const tracker = page.getByRole("article", { name: "Item tracker nearby" });
    await tracker.getByText("Help identify this").click();
    await expect(tracker).toContainText("Heard nearby as: Tile tracker");
    await expectNoAxeViolations(page);
    await tracker.locator("details").getByRole("button", { name: "Locate signal" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Locate signal: Tile tracker" })).toBeVisible();
  });
});

test.describe("Trust fixes at laptop and phone sizes", () => {
  for (const [name, size] of [
    ["laptop", { width: 1280, height: 800 }],
    ["phone", { width: 390, height: 844 }],
  ] as const) {
    test(`questions, nearby cards and every discovered device, by keyboard (${name})`, async ({ page }) => {
      await page.setViewportSize(size);
      const mocked = await mockBackend(page, RESULT);
      await toResults(page, mocked);
      // One count across the questions; the tracker is on Results, under its question.
      await expect(page.getByRole("region", { name: "5 things to look at" })).toBeVisible();
      await expect(page.getByRole("button", { name: /Nearby signals/ })).toHaveCount(0);
      const tracker = page.getByRole("region", { name: "Is anything watching?" }).getByRole("article", { name: /^Item tracker nearby/ });
      await expect(tracker.getByRole("button", { name: "Find it on Nearby" })).toBeVisible();
      const devices = page.getByText(`View all discovered devices (${RESULT.devices.length})`);
      await devices.focus();
      await page.keyboard.press("Enter");
      await expect(page.getByRole("columnheader", { name: "Identification confidence" })).toBeVisible();
      await expect(page.locator("body")).not.toContainText(/\bsafe\b/i);
      await expectNoHorizontalScroll(page);
      await expectNoAxeViolations(page);
    });

    test(`Compare's one starting-point card, Handover evidence and autosave (${name})`, async ({ page }) => {
      await page.setViewportSize(size);
      const mocked = await mockBackend(page, RESULT);
      await toResults(page, mocked);
      await openPage(page, "Compare");
      await expect(page.getByRole("region", { name: "Save a starting point to compare future checks" })).toBeVisible();
      await expectNoAxeViolations(page);
      await nav(page).getByRole("button", { name: HANDOVER }).click();
      const cam = page.getByRole("article", { name: "Ask about the device that looks like a camera" });
      await cam.getByText("Questions, steps and notes").click();
      await cam.getByRole("checkbox", { name: "Host confirmed" }).focus();
      await page.keyboard.press("Space");
      await expect(cam.getByRole("checkbox", { name: "Host confirmed" })).toBeChecked();
      await cam.getByRole("textbox", { name: "Notes" }).focus();
      await page.keyboard.type("Asked by email");
      await expect(cam.getByText("Saved on this laptop")).toBeVisible();
      await expectNoHorizontalScroll(page);
      await expectNoAxeViolations(page);
    });

    test(`Verify explains a report that wasn't timestamped (${name})`, async ({ page }) => {
      await page.setViewportSize(size);
      const mocked = await mockBackend(page, RESULT);
      mocked.setVerify(NOT_TIMESTAMPED);
      await page.goto("/");
      await openPage(page, "Verify a report");
      await page.getByLabel(/^Report PDF/).setInputFiles({ name: "r.pdf", mimeType: "application/pdf", buffer: Buffer.from("%PDF made-up") });
      const check = page.getByRole("button", { name: "Check the report" });
      await check.focus();
      await page.keyboard.press("Enter");
      await expect(page.getByRole("heading", { name: "Not timestamped" })).toBeVisible();
      await expect(page.getByText("This report wasn't timestamped, so it can't be timestamp-verified.")).toBeVisible();
      await expect(page.locator("main")).not.toContainText(/altered|tampered/i);
      await expectNoAxeViolations(page);
    });
  }
});

test.describe("C1 follow-up at laptop and phone sizes", () => {
  for (const [name, size] of [
    ["laptop", { width: 1280, height: 800 }],
    ["phone", { width: 390, height: 844 }],
  ] as const) {
    test(`a status change can be undone by keyboard, and is announced (${name})`, async ({ page }) => {
      await page.setViewportSize(size);
      const mocked = await mockBackend(page, RESULT);
      await toResults(page, mocked);
      await nav(page).getByRole("button", { name: HANDOVER }).click();
      const cam = page.getByRole("article", { name: "Ask about the device that looks like a camera" });
      await cam.getByText("Questions, steps and notes").click();
      await cam.getByRole("radio", { name: "To do" }).focus();
      await page.keyboard.press("ArrowRight");
      await expect(cam.getByText("Status changed to Asked.")).toBeVisible();
      await page.keyboard.press("Tab"); // the next stop after the radios is Undo
      await expect(cam.getByRole("button", { name: "Undo" })).toBeFocused();
      await page.keyboard.press("Enter");
      await expect(cam.getByRole("radio", { name: "To do" })).toBeChecked();
      await expectNoHorizontalScroll(page);
      await expectNoAxeViolations(page);
    });

    test(`Help: delete all saved data, asked first, by keyboard (${name})`, async ({ page }) => {
      await page.setViewportSize(size);
      const mocked = await mockBackend(page, RESULT);
      await page.goto("/");
      await nav(page).getByRole("button", { name: "Help", exact: true }).click();
      await expect(page.getByRole("heading", { level: 1, name: "Help" })).toBeFocused();
      await expectNoAxeViolations(page);
      await page.getByRole("button", { name: "Delete all saved RoomCheck data" }).focus();
      await page.keyboard.press("Enter");
      await expect(page.getByText(/Reports you've already saved as files aren't affected\./)).toBeVisible();
      await expect(page.getByRole("button", { name: "Keep my data" })).toBeFocused();
      await expectNoAxeViolations(page);
      await page.keyboard.press("Tab");
      await page.keyboard.press("Enter"); // "Yes, delete all of it"
      await expect(page.getByText(/^All saved RoomCheck data was deleted from this laptop\./)).toBeVisible();
      expect(mocked.layer6Calls.filter((c) => c.url === "/api/data").map((c) => c.method)).toEqual(["DELETE"]);
      await expectNoHorizontalScroll(page);
    });

    test(`report privacy choices and the Nearby scope note (${name})`, async ({ page }) => {
      await page.setViewportSize(size);
      const mocked = await mockBackend(page, RESULT);
      await toResults(page, mocked);
      await openPage(page, "Report");
      await expect(page.getByRole("checkbox", { name: "Handover notes" })).not.toBeChecked();
      await page.getByRole("checkbox", { name: "Handover notes" }).focus();
      await page.keyboard.press("Space");
      await expect(page.getByRole("checkbox", { name: "Handover notes" })).toBeChecked();
      await expectNoAxeViolations(page);
      await nav(page).getByRole("button", { name: "Nearby", exact: true }).click();
      await page.getByText("Nearby coverage").click();
      await expect(page.getByText("Some signals may come from neighbouring rooms or buildings.")).toBeVisible();
      await expectNoHorizontalScroll(page);
      await expectNoAxeViolations(page);
    });
  }
});

test.describe("200% zoom and narrow screens", () => {
  // A 1280-pixel laptop window at 200% zoom is 640 CSS pixels wide; 320 is the WCAG reflow width.
  for (const width of [640, 320]) {
    test(`every screen reflows at ${width} px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 700 });
      const mocked = await mockBackend(page, RESULT);
      await page.goto("/");
      await expectNoHorizontalScroll(page);
      await startScan(page);
      await mocked.send([STARTING, MIDWAY]);
      await expectNoHorizontalScroll(page);
      mocked.setPoll(MIDWAY);
      await mocked.drop(); // with the quiet connection line showing, too
      await expect(page.locator("#current-task ~ p").filter({ hasText: "Live connection interrupted" })).toBeVisible();
      await expectNoHorizontalScroll(page);
      await expectNoAxeViolations(page);
      mocked.setPoll({ ...FINISHED, result: RESULT }); // the next poll sees it finished
      await expect(page.getByRole("heading", { level: 2, name: "Check complete" })).toBeVisible();
      await expectNoHorizontalScroll(page);
      await expectNoAxeViolations(page);
      await page.getByRole("button", { name: "See your results" }).click();
      await expect(page.getByRole("heading", { level: 1, name: "Results" })).toBeVisible();
      for (const summary of await page.locator("details:not([open]) > summary").elementHandles()) await summary.click();
      await expectNoHorizontalScroll(page);
      await expectNoAxeViolations(page);
    });
  }
});
