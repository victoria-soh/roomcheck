/** A date and time in the user's own format and time zone, e.g. "3 Nov 2026, 13:25". */
export function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
