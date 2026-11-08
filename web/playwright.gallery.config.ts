import { defineConfig } from "@playwright/test";

// A screenshot of the component gallery, which exists only in the dev build (Vite dev server at
// /gallery). Run: npm run shots:gallery (saves to SHOTS_DIR, default ../docs/screenshots/design-pass).
export default defineConfig({
  testDir: "./e2e-shots",
  testMatch: "gallery.shots.ts",
  reporter: [["list"]],
  use: { baseURL: "http://127.0.0.1:5179", channel: "chromium" },
  projects: [{ name: "1280", use: { viewport: { width: 1280, height: 800 } } }],
  webServer: {
    command: "npx vite --host 127.0.0.1 --port 5179 --strictPort",
    url: "http://127.0.0.1:5179/gallery",
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
