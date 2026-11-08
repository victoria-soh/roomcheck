// WCAG 2.2 contrast for RoomCheck's colour tokens. Run: node scripts/contrast.mjs
// Reads the hex colours from src/styles/tokens.css and checks every text/background pair the
// design uses (PAIRS below). AA: 4.5:1 for text, 3:1 for large text, icons and control edges.
// src/styles/contrast.test.ts runs the same check, so a token change can't break a pair.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export function hexToRgb(hex) {
  const h = hex.replace("#", "");
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
}

function channel(c) {
  const s = c / 255;
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

export function luminance(hex) {
  const [r, g, b] = hexToRgb(hex).map(channel);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

export function ratio(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** --color-name: #hex; from a CSS file. */
export function readTokens(css) {
  const out = {};
  for (const m of css.matchAll(/--color-([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\b/g)) out[m[1]] = m[2].toLowerCase();
  return out;
}

// [foreground, background, minimum, what it is]
export const PAIRS = [
  ["ink", "canvas", 4.5, "body text on the page"],
  ["ink", "surface", 4.5, "body text on cards"],
  ["ink", "aqua", 4.5, "text on tinted surfaces"],
  ["ink", "lagoon", 4.5, "primary button text"],
  ["ink", "lagoon-hover", 4.5, "primary button text, hovered"],
  ["muted", "canvas", 4.5, "secondary text on the page"],
  ["muted", "surface", 4.5, "secondary text on cards"],
  ["muted", "aqua", 4.5, "secondary text on tinted surfaces"],
  ["accent", "canvas", 4.5, "links and small teal text on the page"],
  ["accent", "surface", 4.5, "links and small teal text on cards"],
  ["accent", "aqua", 4.5, "teal text on tinted surfaces"],
  ["accent-hover", "surface", 4.5, "links, hovered"],
  ["focus", "canvas", 3, "focus ring on the page"],
  ["focus", "surface", 3, "focus ring on cards"],
  ["focus", "lagoon", 3, "focus ring around a primary button"],
  ["line-strong", "surface", 3, "control edges on cards"],
  ["line-strong", "canvas", 3, "control edges on the page"],
  ["accent", "surface", 3, "active-tab underline and selected-chip edge"],
  ["ink", "aqua", 4.5, "text in a selected chip (lagoon-tinted)"],
  ["sev-high", "surface", 4.5, "High priority text"],
  ["sev-high", "sev-high-tint", 4.5, "High badge"],
  ["sev-medium", "surface", 4.5, "Medium priority text"],
  ["sev-medium", "sev-medium-tint", 4.5, "Medium badge"],
  ["sev-low", "surface", 4.5, "Low priority text"],
  ["sev-low", "sev-low-tint", 4.5, "Low badge"],
  ["sev-info", "surface", 4.5, "Info text"],
  ["sev-info", "sev-info-tint", 4.5, "Info badge"],
  ["ink", "notice", 4.5, "text on a warning notice"],
  ["sev-medium", "notice", 3, "warning icon on its notice"],
  ["ink", "error-tint", 4.5, "text on an error notice"],
  ["sev-high", "error-tint", 3, "error icon on its notice"],
  ["ink", "info-tint", 4.5, "text on an info notice"],
  ["accent", "info-tint", 3, "info icon on its notice"],
  ["danger", "surface", 4.5, "destructive button text and edge"],
  ["on-danger", "danger", 4.5, "destructive button, confirmed"],
  ["muted", "disabled", 4.5, "unavailable button text"],
  ["wordmark", "surface", 4.5, "the wordmark on the header"],
];

export function check(tokens) {
  return PAIRS.map(([fg, bg, min, what]) => {
    if (!tokens[fg] || !tokens[bg]) return { fg, bg, min, what, value: 0, ok: false, missing: true };
    const value = ratio(tokens[fg], tokens[bg]);
    return { fg, bg, min, what, value, ok: value >= min };
  });
}

if (import.meta.url === `file:///${process.argv[1]?.replace(/\\/g, "/")}` || process.argv[1]?.endsWith("contrast.mjs")) {
  const here = dirname(fileURLToPath(import.meta.url));
  const tokens = readTokens(readFileSync(join(here, "../src/styles/tokens.css"), "utf8"));
  let failed = 0;
  for (const r of check(tokens)) {
    if (!r.ok) failed += 1;
    console.log(`${r.ok ? "ok  " : "FAIL"} ${r.value.toFixed(2).padStart(5)}:1 (min ${r.min})  ${r.fg} on ${r.bg}  ${r.what}${r.missing ? "  [missing token]" : ""}`);
  }
  process.exitCode = failed ? 1 : 0;
}
