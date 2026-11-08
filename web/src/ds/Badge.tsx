import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { Band, Severity, TaskStatus } from "../api/types";
import { EvidenceIcon, NearbyIcon, RouterIcon, SeverityIcon } from "../components/icons";
import { BADGE, PRIORITY_BADGE } from "./classes";

/** Priority: tinted severity colour, its own icon shape and the word. Heard as "Priority: Look at this first". */
export function PriorityBadge({ level }: { level: Severity }) {
  const { t } = useTranslation();
  const word = t(`results.severity.${level}`);
  return (
    <span className={PRIORITY_BADGE[level]}>
      <SeverityIcon level={level} />
      <span className="sr-only">{t("results.severityLabel", { level: word })}</span>
      <span aria-hidden="true">{word}</span>
    </span>
  );
}

/** Identification confidence: an outlined, quiet badge. */
export function ConfidenceBadge({ band }: { band: Band }) {
  const { t } = useTranslation();
  return <span className={BADGE.confidence}>{t("results.confidence", { band: t(`results.band.${band}`) })}</span>;
}

/** A task's workflow status: square-ish and neutral. */
export function StatusBadge({ status }: { status: TaskStatus }) {
  const { t } = useTranslation();
  return <span className={BADGE.status}>{t(`handover.statusValue.${status}`)}</span>;
}

/** Evidence: "Host confirmed" or "Observed by RoomCheck", aqua with a shield. */
export function EvidenceBadge({ children }: { children: ReactNode }) {
  return (
    <span className={BADGE.evidence}>
      <span className="text-accent">
        <EvidenceIcon />
      </span>
      {children}
    </span>
  );
}

/** Where a finding comes from: This network, or Nearby. Outlined teal with an icon. */
export function SourceBadge({ source }: { source: "network" | "nearby" }) {
  const { t } = useTranslation();
  return (
    <span className={BADGE.source}>
      {source === "network" ? <RouterIcon /> : <NearbyIcon />}
      {t(source === "network" ? "results.network" : "nav.nearby")}
    </span>
  );
}
