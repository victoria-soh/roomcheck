import "@testing-library/jest-dom/vitest";
import "../i18n";

import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

// jsdom has no ResizeObserver; Recharts' ResponsiveContainer needs one.
class NoResize {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= NoResize as unknown as typeof ResizeObserver;

afterEach(() => {
  cleanup();
  // The screen is in the address (App's hash routes) and the check in sessionStorage: start
  // every test from a fresh page.
  window.history.replaceState(null, "", "/");
  sessionStorage.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
