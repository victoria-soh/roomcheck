import type { Severity } from "../api/types";
import { PriorityBadge } from "../ds/Badge";

/** The priority badge, from the design system. Screen readers hear "Priority: Look at this first". */
export function SeverityBadge({ level }: { level: Severity }) {
  return <PriorityBadge level={level} />;
}
