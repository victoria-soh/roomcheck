// Small helpers for the scanning screen.
import type { StepKey } from "../api/types";

// The order tasks start in, as the backend lists them (app/scan.py): tasks that run at the same
// time sit next to each other.
export const STEPS: StepKey[] = ["listen", "nearby", "services", "router", "explain"];

/** 65.4 -> "1:05" */
export function formatElapsed(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}
