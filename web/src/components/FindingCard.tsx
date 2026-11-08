import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { Device, Explanation, Finding, NearbyItem } from "../api/types";
import type { RecognitionProps } from "../handover/useHandover";
import { AiTag } from "./AiTag";
import { ArrowIcon, ChevronIcon, SeverityIcon } from "./icons";
import { deviceName, findingAnchor } from "./links";
import { nearbyClues } from "./identify";
import { IdentifyPanel } from "./IdentifyPanel";
import { RecognitionChoices } from "./Recognition";
import { SEVERITY_STRIPE, SEVERITY_TEXT } from "./severity";
import { Bullets } from "./ui";

interface Props {
  finding: Finding;
  device?: Device;
  nearby?: NearbyItem;
  explanation?: Explanation;
  action?: ReactNode; // e.g. the Nearby screen's "Locate signal" button
  // Layer 6: "Do you recognise this?" for device and nearby findings.
  recognition?: RecognitionProps;
}

/** One finding, in the same template as the Results cards: the title (a statement) and the
 * plain "Identification confidence: … · Priority: …" line; What we observed; "Do you recognise
 * this?"; What it could mean (the rule's fixed sentence); What you can do (the next step and its
 * buttons, Locate signal among them); Evidence and details, collapsed. "Help identify this"
 * stays as its own expander below. */
export function FindingCard({ finding, device, nearby, explanation, action, recognition }: Props) {
  const { t } = useTranslation();
  const anchor = findingAnchor(finding.id);
  const kind =
    finding.scope === "nearby"
      ? t(`results.kind.${nearby?.kind ?? "wifi"}`)
      : t(`results.kind.${finding.scope}`);
  const what = recognition?.name || nearby?.label || deviceName(device, t);
  const text = explanation?.explanation || finding.standard_explanation;
  const why = explanation?.why_it_matters || finding.standard_why;
  const ai = explanation?.source === "ai";
  // An answer changes only the next step and guidance; everything above them stays the same.
  const nextStep = recognition?.adjusted?.next_step ?? finding.next_step;
  const guidance = recognition?.adjusted?.guidance ?? finding.guidance;
  const priority = t("results.priority", { level: t(`results.severity.${finding.severity}`) });

  return (
    <article
      id={anchor}
      aria-labelledby={`${anchor}-title`}
      tabIndex={-1}
      className="relative overflow-hidden rounded-card border border-line bg-surface shadow-soft"
    >
      <span aria-hidden="true" className={`absolute inset-y-0 left-0 w-0.5 ${SEVERITY_STRIPE[finding.severity]}`} />
      <div className="p-3 sm:p-4">
        <h3 id={`${anchor}-title`} className="flex items-start gap-1 text-lg">
          <span className={`mt-0.5 ${SEVERITY_TEXT[finding.severity]}`}>
            <SeverityIcon level={finding.severity} />
          </span>
          <span className="min-w-0">{finding.title}</span>
        </h3>
        <p className="mt-0.5 text-sm text-muted">
          {kind}
          {what ? ` · ${what}` : ""}
          {" · "}
          <span className="font-semibold text-ink">{priority}</span>
        </p>

        <Part id={`${anchor}-observed`} title={t("results.part.observed")}>
          <p>{finding.observed || finding.standard_explanation}</p>
        </Part>

        {recognition && finding.subject && finding.scope !== "network" && (
          <div className="mt-2 rounded-inner border border-line p-2">
            <RecognitionChoices props={recognition} />
          </div>
        )}

        <Part id={`${anchor}-meaning`} title={t("results.part.meaning")}>
          <p>{finding.could_mean || why}</p>
        </Part>

        <Part id={`${anchor}-action`} title={t("results.part.action")}>
          <div className="flex gap-1.5 rounded-inner bg-raised p-1.5">
            <span className="mt-0.5 text-accent">
              <ArrowIcon />
            </span>
            <p className="min-w-0">
              <span className="font-semibold">{t("results.nextAction")}: </span>
              {nextStep}
            </p>
          </div>
          {guidance.length > 0 && (
            <div className="mt-1 text-muted">
              <Bullets items={guidance} />
            </div>
          )}
          {action && <div className="mt-1">{action}</div>}
        </Part>

        <details className="group/details mt-2 rounded-inner border border-line">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-2 rounded-inner px-2 py-1 font-semibold transition-colors hover:bg-canvas">
            {t("results.details")}
            <span className="text-muted transition-transform group-open/details:rotate-180">
              <ChevronIcon />
            </span>
          </summary>
          <div className="space-y-1 px-2 pt-0.5 pb-2">
            <p>
              {text}
              {ai && <AiTag />}
            </p>
            {why && (
              <p>
                <span className="font-semibold">{t("results.whyItMatters")}: </span>
                {why}
                {ai && <AiTag />}
              </p>
            )}
            {/* The two scales, kept apart: identification confidence, and the priority. */}
            <p className="text-sm text-muted">
              {t("results.identification", { band: t(`results.band.${finding.confidence_band}`) })} ·{" "}
              {t("results.priorityTerm", { level: t(`results.severity.${finding.severity}`) })}
            </p>
            <Bullets items={finding.evidence} />
          </div>
        </details>

        {recognition && finding.subject && finding.scope === "nearby" && (
          <IdentifyPanel props={recognition} clues={nearbyClues(nearby, t)} find={action} withAnswer={false} />
        )}
      </div>
    </article>
  );
}

/** One labelled part of the card (as on Results): a group named by its heading. */
function Part({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <div role="group" aria-labelledby={id} className="mt-2">
      <h4 id={id} className="text-sm font-semibold text-muted">
        {title}
      </h4>
      <div className="mt-0.5">{children}</div>
    </div>
  );
}
