import { expect, test, type Page } from "@playwright/test";

import { BASELINE_UNREADABLE, CAM_SUBJECT, COMPARE_READY, LIVE, RESULT } from "../src/test/fixtures";
import { expectNoAxeViolations, expectNoHorizontalScroll, mockBackend, openPage, START_BUTTON, type Mocked } from "./mock";

async function toResults(page: Page, mocked: Mocked) {
  await page.goto("/");
  await page.getByRole("radio", { name: "No, or I'm not sure", exact: true }).check();
  await page.getByRole("button", { name: START_BUTTON }).click();
  await mocked.socket();
  await mocked.send(LIVE);
  await page.getByRole("button", { name: "See your results" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Results" })).toBeVisible();
}

function navTo(page: Page, name: string) {
  return openPage(page, name);
}

function expectClean(mocked: Mocked) {
  expect(mocked.outside).toEqual([]);
  expect(mocked.cspErrors).toEqual([]);
}

test.describe("Do you recognise this device?", () => {
  test("Mine changes the card's second line and next step; the finding stays put", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await toResults(page, mocked);
    const cam = page.getByRole("article", { name: /^Likely camera/ });
    const question = cam.getByRole("group", { name: "Do you recognise this device?" });
    await expect(question).toBeVisible();
    for (const radio of await question.getByRole("radio").all()) await expect(radio).not.toBeChecked();
    await expectNoAxeViolations(page);

    await question.getByRole("radio", { name: "Mine" }).click();
    await expect(cam).toContainText("Identified by you as yours");
    await expect(cam).toContainText("Priority: Look at this first");
    await expect(cam).toContainText("You said this is yours");
    await expect(cam).not.toContainText("Found a hidden camera? See what to do");
    await expect(page.getByRole("region", { name: "Is anything watching?" }).getByRole("article", { name: /^Likely camera/ })).toHaveCount(1);
    expect(mocked.layer6Calls.find((c) => c.url === "/api/answers")?.body).toEqual({
      subject: CAM_SUBJECT,
      answer: "mine",
      confirmed: null,
    });
    await expectNoAxeViolations(page);
    expectClean(mocked);
  });

  test("answering works with the keyboard alone", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await toResults(page, mocked);
    const cam = page.getByRole("article", { name: /^Likely camera/ });
    const mine = cam.getByRole("radio", { name: "Mine" });
    await mine.focus();
    await page.keyboard.press("Space");
    await expect(cam).toContainText("Identified by you as yours");
  });
});

test.describe("Handover screen", () => {
  test("tasks with status, notes and the bundled message, accessibly", async ({ page, context, browserName }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    const mocked = await mockBackend(page, RESULT);
    await toResults(page, mocked);
    await navTo(page, "Handover");
    await expect(page.getByRole("heading", { level: 1, name: "Handover" })).toBeFocused();
    await expect(page.getByRole("heading", { level: 2, name: "Tasks (4)" })).toBeVisible();
    await expectNoAxeViolations(page);

    await expect(page.getByText(/saved on this laptop as you go/)).toBeVisible();
    const cam = page.getByRole("article", { name: "Ask about the device that looks like a camera" });
    await cam.getByText("Questions, steps and notes").click(); // the card opens for the rest
    // Status (the workflow) and evidence (what the host said) are separate.
    await cam.getByRole("radio", { name: "Asked" }).click();
    await expect(cam.getByRole("radio", { name: "Asked" })).toBeChecked();
    await cam.getByRole("checkbox", { name: "Host confirmed" }).click(); // controlled: click, then wait
    await expect(cam.getByRole("checkbox", { name: "Host confirmed" })).toBeChecked();
    await expect(cam.getByText(/^Host confirmed .*2026/)).toBeVisible();
    await expect(cam).toContainText(/Changed .*2026/);
    // Notes save themselves when typing stops.
    await expect(cam.getByRole("button", { name: "Save notes" })).toHaveCount(0);
    await cam.getByRole("textbox", { name: "Notes" }).fill("The host said it's the hallway camera.");
    await expect(cam.getByText("Saved on this laptop")).toBeVisible();
    const patches = mocked.layer6Calls.filter((c) => c.method === "PATCH").map((c) => c.body);
    expect(patches).toEqual([
      { status: "asked" },
      { host_confirmed: true },
      { notes: "The host said it's the hallway camera." },
    ]);

    await page.getByText("Draft message to host").click();
    const box = page.getByRole("textbox", { name: "Message" });
    await box.fill("Hello, could you tell me what the camera records?");
    await page.getByRole("button", { name: "Copy message" }).click();
    await expect(page.getByText("Copied. Paste it into your email or chat.")).toBeVisible();
    if (browserName === "chromium") {
      expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
        "Hello, could you tell me what the camera records?",
      );
    }
    await expectNoAxeViolations(page);
    expectClean(mocked); // the support link isn't followed; nothing leaves the laptop
  });

  test("statuses change with the keyboard alone", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await toResults(page, mocked);
    await navTo(page, "Handover");
    const cam = page.getByRole("article", { name: "Ask about the device that looks like a camera" });
    const more = cam.getByText("Questions, steps and notes");
    await more.focus();
    await page.keyboard.press("Enter"); // opens the card from the keyboard
    await cam.getByRole("radio", { name: "To do" }).focus();
    await page.keyboard.press("ArrowRight"); // radios: arrow keys move and select
    await expect(cam.getByRole("radio", { name: "Asked" })).toBeChecked();
    expect(mocked.layer6Calls.some((c) => c.method === "PATCH")).toBe(true);
  });
});

test.describe("Compare screen", () => {
  test("save a move-in scan, then New, Changed and Not seen this time, and delete it in Help after confirming", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await toResults(page, mocked);
    const card = page.getByRole("region", { name: "Move-in scan" });
    await card.getByRole("button", { name: "Save as my move-in scan" }).click();
    await expect(card).toContainText(/Your move-in scan from .*2026.* is saved\./);
    mocked.setCompare(COMPARE_READY);
    await card.getByRole("button", { name: "Compare with it" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Compare with your move-in scan" })).toBeFocused();
    await expect(page.getByRole("region", { name: "New (1)" })).toContainText(
      "Camera-like device that appeared since your move-in scan",
    );
    await expect(page.getByRole("region", { name: "Changed (1)" })).toContainText("New finding: Cloud-linked smart device");
    const notSeen = page.getByRole("region", { name: "Not seen this time (1)" });
    await expect(notSeen).toContainText("Smart speaker");
    await expect(notSeen).toContainText("Devices can be asleep or out of range");
    await expectNoAxeViolations(page);

    // Deleting lives in Help now: Compare has only a small link to it.
    await expect(page.getByRole("button", { name: "Delete move-in scan" })).toHaveCount(0);
    await page.getByRole("button", { name: "Manage saved data" }).click();
    await expect(page.getByRole("heading", { level: 3, name: "Delete your data" })).toBeFocused();
    const del = page.getByRole("button", { name: "Delete move-in scan" });
    await del.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("button", { name: "Keep it" })).toBeFocused();
    await expectNoAxeViolations(page);
    await page.keyboard.press("Tab");
    await page.keyboard.press("Enter"); // "Yes, delete it"
    await expect(page.getByText(/^Your starting point was deleted from this laptop\./)).toBeVisible();
    await expect(page.getByRole("button", { name: "Delete move-in scan" })).toHaveCount(0); // nothing left to delete
    const changes = mocked.layer6Calls.filter((c) => c.url === "/api/baseline" && c.method !== "GET");
    expect(changes.map((c) => c.method)).toEqual(["POST", "DELETE"]);
    expectClean(mocked);
  });

  test("the DPAPI failure message and no baseline yet", async ({ page }) => {
    const mocked = await mockBackend(page, RESULT);
    await toResults(page, mocked); // with no saved scan, Compare is listed only after a check
    await navTo(page, "Compare");
    const start = page.getByRole("region", { name: "Save a starting point to compare future checks" });
    await expect(start).toContainText("Save this check so RoomCheck can show you anything new that appears later.");
    await expect(start).toContainText("Network: Example-Home");
    await expect(start.getByRole("button", { name: "Save as my move-in scan" })).toBeVisible();
    await expectNoAxeViolations(page);
    // An unreadable saved scan still lists Compare before any check, so it can be replaced.
    mocked.setBaseline(BASELINE_UNREADABLE);
    mocked.setCompare({ state: "unreadable", baseline: BASELINE_UNREADABLE, comparison: null });
    await page.reload();
    await navTo(page, "Compare");
    await expect(
      page.getByText("This saved scan belongs to another account or install. Start a new move-in scan."),
    ).toBeVisible();
    await expectNoAxeViolations(page);
  });
});

test.describe("Layer 6 at 200% zoom and narrow screens", () => {
  for (const width of [640, 320]) {
    test(`Handover and Compare reflow at ${width} px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 700 });
      const mocked = await mockBackend(page, RESULT);
      await toResults(page, mocked);
      await expectNoHorizontalScroll(page);
      await navTo(page, "Handover");
      await expect(page.getByRole("heading", { level: 2, name: "Tasks (4)" })).toBeVisible();
      await expectNoHorizontalScroll(page);
      await expectNoAxeViolations(page);
      mocked.setCompare(COMPARE_READY);
      await navTo(page, "Compare");
      await expect(page.getByRole("region", { name: "New (1)" })).toBeVisible();
      await expectNoHorizontalScroll(page);
      await expectNoAxeViolations(page);
    });
  }
});
