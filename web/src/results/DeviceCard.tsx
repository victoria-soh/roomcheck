import type { TFunction } from "i18next";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import type { CameraLocation, Draft, Explanation, Finding, Task } from "../api/types";
import { AiTag } from "../components/AiTag";
import { ArrowIcon, ChevronIcon, SeverityIcon } from "../components/icons";
import { deviceName, findingAnchor } from "../components/links";
import { deviceClues, needsIdentifying } from "../components/identify";
import { IdentifyPanel } from "../components/IdentifyPanel";
import { Recognition } from "../components/Recognition";
import { SEVERITY_STRIPE, SEVERITY_TEXT } from "../components/severity";
import { SeverityBadge } from "../components/SeverityBadge";
import { quietButton, secondaryButton } from "../components/styles";
import { Bullets } from "../components/ui";
import { PlatformReport } from "../components/PermissionMessage";
import { choicePillClass } from "../ds/classes";
import type { RecognitionProps } from "../handover/useHandover";
import { CAMERA_RULES, groupId, onResults, type Group } from "./summary";

interface Props {
  group: Group;
  explanations: Explanation[];
  recognition?: RecognitionProps;
  tasks: Task[]; // the handover tasks for this card's findings
  onDraft: () => void;
  onViewHandover: (taskId: string) => void;
  /** Nearby signals: open Nearby, where the locator and the full signal list are. */
  onOpenNearby?: () => void;
  /** Camera cards: open the physical check with this device's places first. */
  onFindPhysically?: () => void;
}

/** One card per device, nearby signal or network finding, under its question. High and Medium:
 * the full card. Low: a compact one-line row (icon, title, priority) that opens to the same
 * full card.
 *
 * Full card, top to bottom: title and priority label; What we observed (the specific clues, one
 * fixed plain sentence each, or the rule's fixed sentence; then "Also found": the device's
 * other findings, and Info items); "Do you recognise this device?" (device cards only;
 * an answer changes What you can do at once); What it could mean (the rule's fixed risk
 * sentence); What you can do (the next step and its buttons); the hidden-camera expander
 * (camera cards only); Evidence and details. The finding itself never changes. */
export function DeviceCard(props: Props) {
  const { t } = useTranslation();
  const { group } = props;
  const top = group.findings[0]!;
  const id = groupId(group.key);
  const compact = top.severity === "Low" || top.severity === "Info";
  return (
    <article
      id={id}
      aria-labelledby={`${id}-title`}
      tabIndex={-1}
      className="relative overflow-hidden rounded-card border border-line bg-surface shadow-soft"
    >
      <span aria-hidden="true" className={`absolute inset-y-0 left-0 w-0.5 ${SEVERITY_STRIPE[top.severity]}`} />
      {compact ? (
        <details data-compact className="group">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-2 px-3 py-1.5 transition-colors hover:bg-canvas">
            <h3 id={`${id}-title`} className="flex min-w-0 flex-wrap items-center gap-x-1 gap-y-0.5 text-base">
              <span className={SEVERITY_TEXT[top.severity]}>
                <SeverityIcon level={top.severity} />
              </span>
              {/* The anchor of the top finding, for links to it. */}
              <span id={findingAnchor(top.id)} className="font-semibold">
                {top.title}
              </span>
              <span className="text-sm font-normal text-muted">{t("results.priority", { level: t(`results.severity.${top.severity}`) })}</span>
            </h3>
            <span className="text-muted transition-transform group-open:rotate-180">
              <ChevronIcon />
            </span>
          </summary>
          <div className="px-3 pb-3">
            <Body {...props} />
          </div>
        </details>
      ) : (
        <div className="p-3 sm:p-4">
          <h3 id={`${id}-title`} className="flex items-start gap-1 text-lg">
            <span className={`mt-0.5 ${SEVERITY_TEXT[top.severity]}`}>
              <SeverityIcon level={top.severity} />
            </span>
            <span id={findingAnchor(top.id)} className="min-w-0">
              {top.title}
            </span>
          </h3>
          <Body {...props} />
        </div>
      )}
    </article>
  );
}

/** The card's content under its title. */
function Body({ group, explanations, recognition, tasks, onDraft, onViewHandover, onOpenNearby, onFindPhysically }: Props) {
  const { t } = useTranslation();
  const top = group.findings[0]!;
  // The device's other findings for this question, then Info items (not counted).
  const others = [...group.findings.slice(1), ...group.also];
  const clues = top.clues ?? [];
  // A signal that isn't your own network: it has an identification confidence, and Nearby has
  // its locator. Findings about your own router (e.g. WPS) are like network findings.
  const otherSignal = group.kind === "nearby" && !onResults(top);
  // Which message the next step calls for: from the answer to "Where is it?", or the rule.
  const draft: Draft = recognition?.adjusted?.draft ?? top.draft ?? "host";
  const id = groupId(group.key);
  const nextStep = recognition?.adjusted?.next_step ?? top.next_step;
  const guidance = recognition?.adjusted?.guidance ?? top.guidance;
  const camera = group.findings.some((f) => CAMERA_RULES.has(f.rule_id)) && guidance.length > 0;
  const toAsk = tasks.find((task) => task.who !== "you" && (task.status === "todo" || task.status === "asked"));
  const physical = Boolean(top.asks_location && onFindPhysically);
  const nearby = Boolean(otherSignal && onOpenNearby);
  const hostDraft = Boolean(toAsk && draft === "host");
  // The title is the type only ("Likely camera"); the device's name and maker come first here.
  const who =
    group.kind === "network"
      ? null
      : group.kind === "nearby"
        ? group.nearby?.label ?? null
        : recognition?.name || deviceName(group.device, t) || t("results.unknownDevice");

  return (
    <>
      {/* The priority is a label on the card; fixed rules set it. Then who it is, how sure the
          identification is (devices and signals only), and the user's answer. */}
      <p className="mt-0.5 flex flex-wrap items-center gap-x-1 gap-y-0.5 text-sm text-muted">
        <SeverityBadge level={top.severity} />
        <span>
          {[
            who,
            recognition?.answer ? recognised(recognition, t) : null,
          ]
            .filter(Boolean)
            .join(" · ")}
        </span>
      </p>

      <Part id={`${id}-observed`} title={t("results.part.observed")}>
        {clues.length > 0 ? <Bullets items={clues} /> : <p>{top.observed || top.standard_explanation}</p>}
        {others.length > 0 && (
          <div className="mt-1">
            <h5 className="text-sm font-semibold">{t("results.alsoFound")}</h5>
            <ul className="mt-0.5 space-y-0.5">
              {others.map((f) => (
                <li key={f.id} id={findingAnchor(f.id)} className="flex flex-wrap items-center gap-1">
                  <SeverityBadge level={f.severity} />
                  <span>{f.title}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </Part>

      {/* Device cards: the answer changes "What you can do" straight away. */}
      {recognition && otherSignal && <Recognition props={recognition} />}
      {recognition &&
        group.kind === "device" &&
        (needsIdentifying(group.device, recognition) ? (
          <IdentifyPanel
            props={recognition}
            clues={deviceClues(group.device, t)}
            find={<p className="text-sm text-muted">{t("identify.findDevice")}</p>}
          />
        ) : (
          <Recognition props={recognition} />
        ))}

      <Part id={`${id}-meaning`} title={t("results.part.meaning")}>
        <p>{top.could_mean || top.standard_why}</p>
      </Part>

      <Part id={`${id}-action`} title={t("results.part.action")}>
        <div className="flex gap-1.5 rounded-inner bg-raised p-1.5">
          <span className="mt-0.5 text-accent">
            <ArrowIcon />
          </span>
          <p className="min-w-0">
            <span className="font-semibold">{t("results.nextAction")}: </span>
            {nextStep}
          </p>
        </div>
        {/* A camera: "Where is it?" picks the next step for the stay type (rules.yaml). */}
        {top.asks_location && recognition && recognition.answer !== "mine" && <WhereIsIt id={`${id}-where`} recognition={recognition} />}
        {(physical || nearby || hostDraft || tasks[0]) && (
          // Every card's buttons sit side by side on a laptop; stacked, full width, on a phone.
          <div className="mt-1 flex flex-col gap-1 sm:flex-row sm:flex-wrap" data-testid="card-actions">
            {physical && (
              <button type="button" onClick={onFindPhysically} className={`${secondaryButton} w-full sm:w-auto`}>
                {t("results.findPhysically")}
              </button>
            )}
            {nearby && (
              <button type="button" onClick={onOpenNearby} className={`${secondaryButton} w-full sm:w-auto`}>
                {t("results.questions.seeOnNearby")}
              </button>
            )}
            {/* The button matches the step: a report to the platform, or a message to the host. */}
            {hostDraft && (
              <button type="button" onClick={onDraft} className={`${secondaryButton} w-full sm:w-auto`}>
                {t("results.draft")}
              </button>
            )}
            {tasks[0] && (
              <button type="button" onClick={() => onViewHandover(tasks[0]!.id)} className={`${secondaryButton} w-full sm:w-auto`}>
                {t("results.viewHandover")}
              </button>
            )}
          </div>
        )}
        {draft === "platform" && (
          <div className="mt-1">
            <PlatformReport id={`${id}-platform`} />
          </div>
        )}
      </Part>

      {camera && (
        // The hidden-camera warning lives only in here.
        <details className="group/camera mt-1.5">
          <summary className={`inline-flex cursor-pointer list-none items-center gap-0.5 ${quietButton} px-0 text-accent no-underline hover:underline`}>
            {t("results.camera")}
            <span className="transition-transform group-open/camera:rotate-180">
              <ChevronIcon />
            </span>
          </summary>
          <div className="mt-1 rounded-inner border border-notice-line bg-notice px-2 py-1.5">
            <Bullets items={guidance} />
          </div>
        </details>
      )}

      <details className="group/details mt-2 rounded-inner border border-line">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-2 rounded-inner px-2 py-1 font-semibold transition-colors hover:bg-canvas">
          {t("results.details")}
          <span className="text-muted transition-transform group-open/details:rotate-180">
            <ChevronIcon />
          </span>
        </summary>
        <div className="space-y-2 px-2 pt-0.5 pb-2">
          {[...group.findings, ...group.also].map((f, _, all) => (
            <Details
              key={f.id}
              finding={f}
              explanation={explanations.find((e) => e.finding_id === f.id)}
              // One finding: the card's title already says what it is.
              titled={all.length > 1}
            />
          ))}
        </div>
      </details>
    </>
  );
}

/** "Where is it?": inside, outside or a shared area, or can't find it. Saved like the other
 * answers; it changes the next step (and which message is offered), never the finding. */
export function WhereIsIt({ id, recognition }: { id: string; recognition: RecognitionProps }) {
  const { t } = useTranslation();
  const choices: CameraLocation[] = ["inside", "outside", "unknown"];
  return (
    <fieldset aria-describedby={`${id}-hint`} className="mt-1">
      <legend className="font-semibold">{t("results.where.question")}</legend>
      <p id={`${id}-hint`} className="text-sm text-muted">
        {t("results.where.hint")}
      </p>
      <div className="mt-0.5 flex flex-wrap gap-1">
        {choices.map((c) => (
          <label key={c} className={choicePillClass(recognition.location === c)}>
            <input
              type="radio"
              name={`${id}-location`}
              checked={recognition.location === c}
              onChange={() => recognition.onLocation(c)}
              className="size-2 accent-accent"
            />
            {t(`results.where.${c}`)}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/** One labelled part of the card: a group named by its heading (not a landmark, since every
 * card has the same three). */
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

/** A finding's explanation (with its AI label), why it matters, and its evidence. */
function Details({ finding, explanation, titled }: { finding: Finding; explanation?: Explanation; titled: boolean }) {
  const { t } = useTranslation();
  const text = explanation?.explanation || finding.standard_explanation;
  const why = explanation?.why_it_matters || finding.standard_why;
  const ai = explanation?.source === "ai";
  return (
    <section className="space-y-1">
      {titled && (
        <h4 className="flex flex-wrap items-center gap-1">
          <SeverityBadge level={finding.severity} />
          {finding.title}
        </h4>
      )}
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
      {/* The two scales, kept apart: how sure the identification is, and the priority. */}
      <p className="text-sm text-muted">
        {/* Devices and other nearby signals only; not network findings or your own router. */}
        {(finding.scope === "device" || (finding.scope === "nearby" && !onResults(finding))) && (
          <>{t("results.identification", { band: t(`results.band.${finding.confidence_band}`) })} · </>
        )}
        {t("results.priorityTerm", { level: t(`results.severity.${finding.severity}`) })}
      </p>
      <Bullets items={finding.evidence} />
    </section>
  );
}

function recognised(r: RecognitionProps, t: TFunction): string {
  if (r.answer === "mine") return t("results.recognised.mine");
  if (r.answer === "landlord") return t(r.confirmed ? "results.recognised.landlordConfirmed" : "results.recognised.landlordPending");
  return t("results.recognised.unknown");
}
