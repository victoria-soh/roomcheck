// Every text/background pair the design uses passes WCAG 2.2 AA, from the real token file.
/// <reference types="node" />
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { PAIRS, check, ratio, readTokens } from "../../scripts/contrast.mjs";

// Vitest runs from web/: read the token file itself, as scripts/contrast.mjs does.
const tokensCss = readFileSync("src/styles/tokens.css", "utf8");

const tokens = readTokens(tokensCss);

describe("Colour tokens", () => {
  it("has the brand colours the design asks for", () => {
    expect(tokens.lagoon).toBe("#1ba9a6");
    expect(tokens.canvas).toBe("#f1f9f8");
    expect(tokens.ink).toBe("#0e2b28");
  });

  it.each(check(tokens).map((r) => [`${r.fg} on ${r.bg} (${r.what})`, r]))("%s passes AA", (_name, r) => {
    expect(r.missing).toBeFalsy();
    expect(r.value).toBeGreaterThanOrEqual(r.min);
  });

  it("primary buttons are lagoon with ink text, because that passes AA", () => {
    expect(ratio(tokens.ink!, tokens.lagoon!)).toBeGreaterThanOrEqual(4.5);
  });

  it("lagoon is never used as a line or text on white (it's 2.89:1)", () => {
    expect(ratio(tokens.lagoon!, tokens.surface!)).toBeLessThan(3);
    expect(PAIRS.some(([fg, bg]) => fg === "lagoon" && bg === "surface")).toBe(false);
  });

  it("records each ratio in the token file", () => {
    for (const r of check(tokens)) {
      expect(r.ok).toBe(true);
    }
    expect(tokensCss).toMatch(/lagoon 5\.21 \(primary buttons\)/);
    expect(tokensCss).toMatch(/line-strong on surface 4\.07/);
  });
});
