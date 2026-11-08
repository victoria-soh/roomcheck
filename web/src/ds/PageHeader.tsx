import { useContext, useEffect, useRef, type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { formatWhen } from "../format";
import { ScanContext } from "./scanContext";

/** Each page's title, with the scan-context line after a check (network · date and time ·
 * mode). When the user moves to a new page, focus moves to the title, so keyboard and
 * screen-reader users start at the top of it; not on first load, where the skip link is first. */
export function PageHeader({
  children,
  intro,
  focus = true,
  context = true,
}: {
  children: ReactNode;
  intro?: ReactNode;
  focus?: boolean;
  /** Off on pages that aren't about the latest check (Verify checks a saved report). */
  context?: boolean;
}) {
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (focus) ref.current?.focus();
  }, [focus]);
  // One block, so a page's section spacing doesn't push the context line away from the title.
  return (
    <div>
      <h1 ref={ref} tabIndex={-1} className="scroll-mt-0 text-xl font-bold tracking-tight text-balance focus:outline-none focus-visible:outline-none sm:text-2xl">
        {children}
      </h1>
      {context && <ScanContextLine />}
      {intro && <p className="mt-1 max-w-measure text-lg text-muted">{intro}</p>}
    </div>
  );
}

function ScanContextLine() {
  const { t } = useTranslation();
  const result = useContext(ScanContext);
  if (!result) return null;
  const network = result.room_network
    ? result.room_network
    : result.network
      ? t("compare.networkCable")
      : t("compare.networkUnknown");
  return (
    <p className="mt-0.5 text-sm text-muted">
      <span className="sr-only">{t("scanContext.label")}: </span>
      {t("scanContext.line", { network, when: formatWhen(result.finished_at), mode: t(`compare.mode.${result.mode}`) })}
    </p>
  );
}
