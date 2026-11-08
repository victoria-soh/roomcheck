import { useEffect, useState } from "react";

/** Below Tailwind's `sm` breakpoint (640 px): the phone layout. */
export const PHONE_QUERY = "(max-width: 639.98px)";

/** Whether a media query matches now, following changes. False where matchMedia is missing
 * (e.g. jsdom), so tests get the laptop layout unless they ask for the phone one. */
export function useMediaQuery(query: string): boolean {
  const get = () => typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia(query).matches;
  const [matches, setMatches] = useState(get);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const list = window.matchMedia(query);
    const onChange = () => setMatches(list.matches);
    onChange();
    list.addEventListener?.("change", onChange);
    return () => list.removeEventListener?.("change", onChange);
  }, [query]);
  return matches;
}
