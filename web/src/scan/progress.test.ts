import { describe, expect, it } from "vitest";

import { formatElapsed } from "./progress";

describe("formatElapsed", () => {
  it.each([
    [0, "0:00"],
    [9.9, "0:09"],
    [65.4, "1:05"],
    [600, "10:00"],
    [-3, "0:00"],
  ])("%s s is %s", (seconds, text) => {
    expect(formatElapsed(seconds)).toBe(text);
  });
});
