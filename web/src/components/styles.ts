// The shared button and surface styles, now from the design system (src/ds/classes.ts), so
// every screen uses the same tokens and shapes.
import { buttonClass, cardClass } from "../ds/classes";

export const primaryButton = buttonClass("primary");
/** The look of a primary button that can't be used yet (with aria-disabled and a hint). */
export const unavailableButton = buttonClass("primary", "md", true);
export const secondaryButton = buttonClass("secondary");
/** A text button: links-style actions such as "Check again" or "Undo". */
export const quietButton = buttonClass("text", "sm");
export const card = cardClass;
/** A neutral tag, e.g. the scan mode. */
export const pill = "inline-flex items-center rounded-control bg-raised px-1 py-0.5 text-sm font-semibold text-ink";
