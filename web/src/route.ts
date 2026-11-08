// Hash routes for the main screens, so the browser's Back and Forward move between them and a
// refresh keeps the screen. The data behind them stays in memory (and on the server); only the
// screen's name, and the locator's item, are in the address.

export type Route =
  | { name: "start" }
  | { name: "check" }
  | { name: "results" }
  | { name: "nearby" }
  | { name: "locator"; ref: string }
  | { name: "handover" }
  | { name: "compare" }
  | { name: "report" }
  | { name: "verify" }
  | { name: "help" };

const SIMPLE = ["start", "check", "results", "nearby", "handover", "compare", "report", "verify", "help"] as const;

export function routeHash(route: Route): string {
  return route.name === "locator" ? `#/nearby/locate/${encodeURIComponent(route.ref)}` : `#/${route.name}`;
}

/** The route in an address's hash; Start for anything else. */
export function parseHash(hash: string): Route {
  const path = hash.replace(/^#\/?/, "");
  const locate = /^nearby\/locate\/(.+)$/.exec(path);
  if (locate) {
    try {
      return { name: "locator", ref: decodeURIComponent(locate[1]!) };
    } catch {
      return { name: "nearby" };
    }
  }
  const name = SIMPLE.find((n) => n === path);
  return name ? ({ name } as Route) : { name: "start" };
}

/** Screens that show a check's results: after a refresh they need that check back. */
export function needsResult(route: Route): boolean {
  return ["results", "nearby", "locator", "handover", "report"].includes(route.name);
}

// --- returning focus -----------------------------------------------------------------------

/** How to find the control that opened the next screen again, once Back returns to this one:
 * by its id, or else by its text inside the nearest element that has an id (a card). */
export interface FocusKey {
  id?: string;
  scope?: string;
  text?: string;
}

// React's useId values (e.g. "_r_5_") change when a screen is drawn again, so they can't find
// the same control later. Only ids written in the code are used.
const GENERATED_ID = /^(_r_|«|:r)/;

function stableId(el: Element | null | undefined): string | undefined {
  return el?.id && !GENERATED_ID.test(el.id) ? el.id : undefined;
}

export function focusKeyOf(el: Element | null): FocusKey | null {
  if (!(el instanceof HTMLElement) || el === document.body) return null;
  const id = stableId(el);
  if (id) return { id };
  let scopeEl = el.parentElement?.closest("[id]");
  while (scopeEl && !stableId(scopeEl)) scopeEl = scopeEl.parentElement?.closest("[id]");
  const scope = stableId(scopeEl);
  const text = el.textContent?.trim();
  return text ? { scope, text } : null;
}

function visible(el: HTMLElement): boolean {
  // Inside a closed <details> (other than its summary) a control can't take focus, though
  // Chrome still gives it an offsetParent.
  if (el.closest("details:not([open])") && !el.closest("summary")) return false;
  if (typeof el.checkVisibility === "function") return el.checkVisibility();
  return el.offsetParent !== null || el.getClientRects().length > 0;
}

export function findByKey(key: FocusKey): HTMLElement | null {
  if (key.id) {
    const el = document.getElementById(key.id);
    if (el instanceof HTMLElement) return el;
  }
  if (!key.text) return null;
  const root = (key.scope && document.getElementById(key.scope)) || document;
  const candidates = Array.from(root.querySelectorAll<HTMLElement>("button, a[href], summary"));
  const matches = candidates.filter((c) => c.textContent?.trim() === key.text);
  return matches.find(visible) ?? matches[0] ?? null;
}

// --- the check to restore after a refresh ----------------------------------------------------

const STORE_KEY = "roomcheck.check";

export interface StoredCheck {
  id: string;
  consent: boolean;
}

export function rememberCheck(check: StoredCheck): void {
  try {
    sessionStorage.setItem(STORE_KEY, JSON.stringify(check));
  } catch {
    // Storage off: a refresh just goes back to Start.
  }
}

export function storedCheck(): StoredCheck | null {
  try {
    const raw = sessionStorage.getItem(STORE_KEY);
    const v: unknown = raw ? JSON.parse(raw) : null;
    if (v && typeof v === "object" && "id" in v && typeof v.id === "string") {
      return { id: v.id, consent: "consent" in v && v.consent === true };
    }
  } catch {
    // unreadable: as if nothing was stored
  }
  return null;
}
