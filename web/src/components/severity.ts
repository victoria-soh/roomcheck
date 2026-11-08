import type { Severity } from "../api/types";

// Full class names, so Tailwind finds them. Severity colour is only used for the icon, the
// card's 4 px stripe and the severity tag, never for whole cards.
export const SEVERITY_TEXT: Record<Severity, string> = {
  High: "text-sev-high",
  Medium: "text-sev-medium",
  Low: "text-sev-low",
  Info: "text-sev-info",
};

export const SEVERITY_STRIPE: Record<Severity, string> = {
  High: "bg-sev-high",
  Medium: "bg-sev-medium",
  Low: "bg-sev-low",
  Info: "bg-sev-info",
};
