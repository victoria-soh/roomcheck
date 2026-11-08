import { defineConfig, devices } from "@playwright/test";

// Demo mode end to end: the real server (`uv run python -m app --demo`) serving the built
// dashboard, with made-up data and no scans. Run: npm run test:demo (builds the dashboard
// first). Uses port 8765, so stop any running RoomCheck first.
export default defineConfig({
  testDir: "./e2e-demo",
  reporter: [["list"]],
  timeout: 90_000,
  use: { baseURL: "http://127.0.0.1:8765" },
  projects: [
    { name: "laptop", use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 800 } } },
    { name: "phone", use: { ...devices["Pixel 7"] } },
  ],
  workers: 1, // one demo server, one check at a time
  webServer: {
    command: "uv run python -m app --demo",
    cwd: "..",
    url: "http://127.0.0.1:8765/api/health",
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
