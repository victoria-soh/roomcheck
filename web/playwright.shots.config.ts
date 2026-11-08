import { defineConfig } from "@playwright/test";

// Screenshots of each screen for design review, from the same mocked data as the browser tests.
// Not part of `test:e2e`. Run: npm run shots (saves to SHOTS_DIR, default ../docs/screenshots/design-pass).
export default defineConfig({
  testDir: "./e2e-shots",
  reporter: [["list"]],
  // Full Chromium (not the headless shell), so the Report screen's PDF preview is drawn.
  use: { baseURL: "http://127.0.0.1:4173", channel: "chromium" },
  projects: [
    { name: "1280", use: { viewport: { width: 1280, height: 800 } } },
    { name: "390", use: { viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true } },
  ],
  webServer: {
    command: "npx vite preview",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
