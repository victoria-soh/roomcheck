// Types for scripts/contrast.mjs, so the contrast test can import it.
export function hexToRgb(hex: string): number[];
export function luminance(hex: string): number;
export function ratio(a: string, b: string): number;
export function readTokens(css: string): Record<string, string>;
export const PAIRS: [string, string, number, string][];
export function check(tokens: Record<string, string>): {
  fg: string;
  bg: string;
  min: number;
  what: string;
  value: number;
  ok: boolean;
  missing?: boolean;
}[];
