// The design system's class recipes: one place for every shared look, built only from the
// tokens in styles/tokens.css. Components in src/ds use these; screens use the components.
// Full class names, so Tailwind finds them.

export type ButtonVariant = "primary" | "secondary" | "text" | "destructive" | "destructive-confirm";
export type ButtonSize = "md" | "sm";

const BUTTON_BASE =
  "inline-flex items-center justify-center gap-1 rounded-control border font-semibold transition-colors disabled:cursor-wait";
const BUTTON_SIZE: Record<ButtonSize, string> = {
  md: "min-h-5 px-2.5 py-1 text-base",
  sm: "min-h-4 px-1.5 py-0.5 text-sm",
};
const BUTTON_VARIANT: Record<ButtonVariant, string> = {
  // Lagoon with ink text (5.21:1), lighter on hover (6.60:1).
  primary: "border-lagoon bg-lagoon text-ink hover:border-lagoon-hover hover:bg-lagoon-hover",
  secondary: "border-accent bg-surface text-accent hover:bg-raised hover:text-accent-hover",
  text: "border-transparent bg-transparent px-0.5 text-accent underline underline-offset-4 hover:text-accent-hover",
  destructive: "border-danger bg-surface text-danger hover:bg-sev-high-tint",
  "destructive-confirm": "border-danger bg-danger text-on-danger hover:bg-sev-high",
};
/** Can't be used yet: aria-disabled with a visible hint, never the disabled attribute. */
const BUTTON_UNAVAILABLE = "cursor-not-allowed border-line bg-disabled text-muted";
/** A primary button that can't be used yet keeps the primary look, only paler. */
const PRIMARY_UNAVAILABLE = "cursor-not-allowed border-lagoon bg-lagoon text-ink opacity-55";

export function buttonClass(variant: ButtonVariant = "secondary", size: ButtonSize = "md", unavailable = false): string {
  const look =
    unavailable && variant === "primary"
      ? PRIMARY_UNAVAILABLE
      : unavailable && variant !== "text"
        ? BUTTON_UNAVAILABLE
        : BUTTON_VARIANT[variant];
  const sizing = variant === "text" ? (size === "sm" ? "py-0.5 text-sm" : "py-0.5 text-base") : BUTTON_SIZE[size];
  return `${BUTTON_BASE} ${sizing} ${look}`;
}

export const cardClass = "rounded-card border border-line bg-surface p-3 shadow-soft sm:p-4";
/** A tinted box inside a card, e.g. the next step or a confirmation. */
export const insetClass = "rounded-inner bg-raised p-1.5 sm:p-2";

// Badges: one shape each, so the kinds never look alike.
export type BadgeKind = "status" | "evidence" | "source" | "confidence";
export const BADGE_BASE = "inline-flex items-center gap-0.5 text-sm font-semibold leading-tight";
export const BADGE: Record<BadgeKind, string> = {
  status: `${BADGE_BASE} rounded-control bg-raised px-1 py-0.5 text-ink`, // square-ish, neutral
  evidence: `${BADGE_BASE} rounded-full bg-aqua px-1 py-0.5 text-ink`, // aqua, with a shield
  source: `${BADGE_BASE} rounded-full border border-accent bg-surface px-1 py-0.5 text-accent`, // outlined teal
  confidence: `${BADGE_BASE} rounded-full border border-line-strong bg-surface px-1 py-0.5 font-medium text-muted`,
};
export const PRIORITY_BADGE = {
  High: `${BADGE_BASE} rounded-full bg-sev-high-tint px-1 py-0.5 text-sev-high`,
  Medium: `${BADGE_BASE} rounded-full bg-sev-medium-tint px-1 py-0.5 text-sev-medium`,
  Low: `${BADGE_BASE} rounded-full bg-sev-low-tint px-1 py-0.5 text-sev-low`,
  Info: `${BADGE_BASE} rounded-full bg-sev-info-tint px-1 py-0.5 text-sev-info`,
} as const;

/** A selectable chip or tile: filled teal only when selected. */
export function chipClass(selected: boolean): string {
  return selected
    ? "border-2 border-accent bg-lagoon text-ink"
    : "border border-line bg-surface text-ink hover:border-line-strong hover:bg-raised";
}

// Form controls.
export const fieldLabel = "block text-sm font-semibold text-ink";
export const fieldHint = "block text-sm text-muted";
export const inputClass =
  "mt-0.5 block w-full rounded-control border border-line-strong bg-surface px-1.5 py-1 text-base text-ink";
export const fileInputClass =
  "mt-0.5 block w-full rounded-control border border-line-strong bg-surface p-1 text-sm file:mr-1.5 file:rounded-control file:border file:border-accent file:bg-surface file:px-1.5 file:py-0.5 file:font-semibold file:text-accent";
/** A radio or checkbox row: the whole row is the target; the focus ring sits outside it. */
export function rowClass(selected: boolean): string {
  return `flex cursor-pointer items-start gap-1.5 rounded-control border px-2 py-0.5 transition-colors has-[:focus-visible]:outline-3 has-[:focus-visible]:outline-offset-3 has-[:focus-visible]:outline-focus ${
    selected ? "border-accent bg-aqua" : "border-line bg-surface hover:border-line-strong hover:bg-raised"
  }`;
}
/** A small choice pill (Mine / Host's / Unknown, task statuses): a filter chip. */
export function choicePillClass(selected: boolean): string {
  return `flex cursor-pointer items-center gap-1 rounded-full border px-1.5 py-0.5 text-sm font-semibold transition-colors has-[:focus-visible]:outline-3 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-focus ${
    selected ? "border-accent bg-aqua" : "border-line-strong bg-surface hover:bg-raised"
  }`;
}

// Notices: info (aqua), warning (amber), error (red). They never move.
export type NoticeTone = "info" | "warning" | "error";
export const NOTICE: Record<NoticeTone, { box: string; icon: string }> = {
  info: { box: "rounded-inner border border-line bg-info-tint p-2", icon: "text-accent" },
  warning: { box: "rounded-inner border border-notice-line bg-notice p-2", icon: "text-sev-medium" },
  error: { box: "rounded-inner border border-error-line bg-error-tint p-2", icon: "text-sev-high" },
};
