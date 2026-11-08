import type { ReactNode } from "react";

import { PageHeader } from "../ds/PageHeader";

/** Each screen's heading: the design system's page header (title, then the scan-context line
 * after a check). Focus moves here when the user moves to a new screen. */
export function ScreenHeading({ children, focus = true, context = true }: { children: ReactNode; focus?: boolean; context?: boolean }) {
  return (
    <PageHeader focus={focus} context={context}>
      {children}
    </PageHeader>
  );
}
