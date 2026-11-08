import { useQuery } from "@tanstack/react-query";
import { Fragment, useEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import { useTranslation } from "react-i18next";

import { getCompare } from "../api/client";
import type { DiscoveryResult, Finding } from "../api/types";
import { BaselineCard } from "../components/BaselineCard";
import { ArrowIcon, ChevronIcon, InfoIcon, NeutralIcon, ProblemIcon, SeverityIcon, StepIcon } from "../components/icons";
import { PermissionMessage } from "../components/PermissionMessage";
import { PhysicalCheck, type PhysicalFocus } from "../components/PhysicalCheck";
import type { PhysicalItemId } from "../api/types";
import { SEVERITY_TEXT } from "../components/severity";
import { ScreenHeading } from "../components/ScreenHeading";
import { SeverityBadge } from "../components/SeverityBadge";
import { primaryButton, secondaryButton } from "../components/styles";
import { formatWhen } from "../format";
import { COMPARE_KEY } from "../handover/keys";
import { useHandover, useRecognitionProps } from "../handover/useHandover";
import { DeviceCard, WhereIsIt } from "../results/DeviceCard";
import { questionViews, thingsToLookAt, type QuestionView } from "../results/questions";
import { asGroup, checkRows, rowText, totalRowAfter, coverageOf, headline, heardLine, onResults, recoveryStep, reviewLabel, SEVERITIES as SEVERITY_ORDER, type Group } from "../results/summary";

export type HandoverFocus = "message" | { task: string };

// Where a hidden camera is most often found, first when the check is opened from a camera card.
const CAMERA_PLACES: PhysicalItemId[] = ["lenses", "smoke_detector", "chargers", "clocks", "facing_bed", "tv_box", "purifier_speaker", "mirrors"];

export const LIMITS_ID = "coverage-limits";
const HIGHLIGHT = "review-highlight";
const HIGHLIGHT_MS = 2000;

/** Screen 3, top to bottom: the summary; one line saying device types are unconfirmed; the
 * renter's four questions (Is anything watching? Can someone else control things here? Can
 * you trust this Wi-Fi? What's changed since move-in?), each with a status line and its cards;
 * every discovered device; then Coverage and limits. Fixed rules set every priority, and
 * nothing here says the room is fine: a check that didn't fully run says so. */
export function Results({
  result,
  onOpenNearby,
  onOpenCompare,
  onOpenHandover,
  onOpenHelp,
}: {
  result: DiscoveryResult;
  onOpenNearby: () => void;
  onOpenCompare: () => void;
  onOpenHandover: (focus: HandoverFocus) => void;
  /** Open Help at one of its sections (an element id there). */
  onOpenHelp?: (section: string) => void;
}) {
  const { t } = useTranslation();
  const handover = useHandover().data;
  const recognition = useRecognitionProps();
  const limitsRef = useRef<HTMLDetailsElement>(null);
  // "Find it physically" on a camera card: the physical check, with that device's places first.
  const [physicalFor, setPhysicalFor] = useState<Group | null>(null);
  const explanations = result.explanations?.items ?? [];
  const views = questionViews(result);
  const things = thingsToLookAt(views);

  // "Review …": scroll to the card, open it if it's a compact row, focus it, and highlight it
  // briefly (a static ring under reduced motion, a fade otherwise; index.css).
  const highlightTimer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(highlightTimer.current), []);
  function review(id: string) {
    requestAnimationFrame(() => {
      const el = document.getElementById(id);
      if (!el) return;
      const compact = el.querySelector<HTMLDetailsElement>("details[data-compact]");
      if (compact) compact.open = true;
      el.scrollIntoView?.({ block: "start" });
      el.focus();
      el.classList.add(HIGHLIGHT);
      window.clearTimeout(highlightTimer.current);
      highlightTimer.current = window.setTimeout(() => el.classList.remove(HIGHLIGHT), HIGHLIGHT_MS);
    });
  }
  function findPhysically(g: Group) {
    setPhysicalFor(g);
    requestAnimationFrame(() => {
      const el = document.getElementById("physical-check") as HTMLDetailsElement | null;
      if (!el) return;
      el.open = true;
      el.scrollIntoView?.({ block: "start" });
      el.querySelector("summary")?.focus();
    });
  }
  const camRecognition = physicalFor ? recognition(physicalFor.findings[0]!) : undefined;
  const physicalFocus: PhysicalFocus | null = physicalFor
    ? {
        label: t("results.reviewWhat.R-CAM"),
        order: CAMERA_PLACES,
        where: camRecognition && camRecognition.answer !== "mine" ? <WhereIsIt id="physical-where" recognition={camRecognition} /> : undefined,
      }
    : null;

  function openLimits() {
    const el = limitsRef.current;
    if (!el) return;
    el.open = true;
    el.scrollIntoView?.({ block: "start" });
    el.querySelector("summary")?.focus();
  }

  const card_ = (g: Group) => {
    const ids = new Set([...g.findings, ...g.also].map((f) => f.id));
    const tasks = (handover?.tasks ?? []).filter((task) => ids.has(task.finding_id));
    return (
      <DeviceCard
        key={g.key}
        group={g}
        explanations={explanations.filter((e) => ids.has(e.finding_id))}
        // Devices, and nearby signals that aren't your own network (e.g. a tracker): the same
        // question as on Nearby, sharing the same saved answer.
        recognition={g.kind === "device" || (g.kind === "nearby" && !onResults(g.findings[0]!)) ? recognition(g.findings[0]!) : undefined}
        tasks={tasks}
        onDraft={() => onOpenHandover("message")}
        onViewHandover={(task) => onOpenHandover({ task })}
        onOpenNearby={onOpenNearby}
        onFindPhysically={() => findPhysically(g)}
      />
    );
  };

  return (
    <div className="space-y-4 sm:space-y-5">
      <ScreenHeading>{t("results.title")}</ScreenHeading>

      <div>
        <Summary result={result} views={views} onReview={review} onOpenLimits={openLimits} onOpenHelp={onOpenHelp} />
        {/* C8: a listening-only check says what it covered and what permission would add. */}
        {result.mode === "passive" && <ListeningOnly />}
      </div>

      {/* Nothing to look at: the physical check is offered straight away, open. */}
      {things === 0 && <PhysicalCheck open focus={physicalFocus} />}

      {views.map((view) => (
        <QuestionSection key={view.id} view={view}>
          {view.cards.map((c) => card_(asGroup(c, result)))}
          {view.also.length > 0 && <AlsoFound findings={view.also} id={`also-${view.id}`} />}
        </QuestionSection>
      ))}
      <ChangesSection onOpenCompare={onOpenCompare} />
      {things > 0 && <PhysicalCheck focus={physicalFocus} />}

      <AllDevices result={result} />
      {/* Collapsed while there are things to look at; open when there are none, so the limits
          of a quiet check are in plain view. */}
      <CoverageAndLimits result={result} detailsRef={limitsRef} startOpen={things === 0} />
    </div>
  );
}

/** One question's status line, from fixed wording. */
function questionStatus(view: QuestionView, t: (key: string, values?: Record<string, unknown>) => string): string {
  if (view.state === "look") return t("results.questions.status.look", { count: view.things });
  if (view.state === "info") return t("results.questions.status.info", { count: view.also.length });
  if (view.state === "notDetected") return t("results.questions.status.notDetected");
  return t("results.questions.status.notChecked", { reason: view.notCheckedReason });
}

/** One question: its title, a one-line status (a neutral mark, never a tick), what wasn't
 * checked for it, then its cards. */
function QuestionSection({ view, children }: { view: QuestionView; children: ReactNode }) {
  const { t } = useTranslation();
  const id = `question-${view.id}`;
  const partly = view.state !== "notChecked" && view.notCheckedReason;
  const top = view.state === "look" ? SEVERITY_ORDER.find((level) => view.cards.some((c) => c.findings[0]!.severity === level)) : undefined;
  return (
    <section aria-labelledby={id} className="space-y-2">
      <div>
        <h2 id={id} className="text-lg">
          {t(`results.questions.${view.id}`)}
        </h2>
        <p className="mt-0.5 flex items-center gap-1 font-semibold">
          {/* Things to look at: the highest priority's icon. The neutral dot is only for Not
              detected and Not checked, so nothing reads as "passed". */}
          {top ? (
            <span className={SEVERITY_TEXT[top]}>
              <SeverityIcon level={top} />
            </span>
          ) : (
            <span className="text-muted">
              <NeutralIcon />
            </span>
          )}
          {questionStatus(view, t)}
        </p>
        {partly && <p className="text-sm text-muted">{t("results.questions.status.notChecked", { reason: view.notCheckedReason })}</p>}
        {/* A camera clue too weak to flag: said, not counted, and pointed at the physical check. */}
        {view.weakCamera.length > 0 && <p className="text-sm">{t("results.questions.weakCamera", { count: view.weakCamera.length })}</p>}
      </div>
      {children}
    </section>
  );
}

/** A listening-only check: what it covered, what permission would add, and a message to ask
 * the host for it in writing. */
function ListeningOnly() {
  const { t } = useTranslation();
  return (
    <section aria-labelledby="listening-only" className="mt-1.5 rounded-card border border-line bg-surface px-2 py-1.5 shadow-soft sm:px-3">
      <h2 id="listening-only" className="font-semibold">
        {t("results.listening.title")}
      </h2>
      <p className="mt-0.5 max-w-measure text-sm">{t("results.listening.covered")}</p>
      <p className="max-w-measure text-sm">{t("results.listening.adds")}</p>
      <div className="mt-1">
        <PermissionMessage />
      </div>
    </section>
  );
}

/** Info findings with no card to sit in: listed, labelled, not counted. */
function AlsoFound({ findings, id }: { findings: Finding[]; id: string }) {
  const { t } = useTranslation();
  return (
    <div role="group" aria-labelledby={id} className="rounded-card border border-line bg-surface px-3 py-2 shadow-soft">
      <h3 id={id} className="font-semibold">
        {t("results.questions.alsoTitle")}
      </h3>
      <p className="text-sm text-muted">{t("results.questions.alsoIntro")}</p>
      <ul className="mt-1 space-y-1">
        {findings.map((f) => (
          <li key={f.id} className="flex flex-wrap items-center gap-1">
            <SeverityBadge level={f.severity} />
            <span>{f.title}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** "What's changed since move-in?": a summary from Compare, or how to start one. */
function ChangesSection({ onOpenCompare }: { onOpenCompare: () => void }) {
  const { t } = useTranslation();
  const compare = useQuery({ queryKey: COMPARE_KEY, queryFn: getCompare });
  const data = compare.data;
  const c = data?.state === "ready" ? data.comparison : null;
  const differences = c ? c.new.length + c.gone.length + c.changed.length : 0;
  // Only with a comparison: otherwise the Move-in scan card below says what to do.
  const status = c
    ? differences > 0
      ? t("results.questions.differences", { count: differences })
      : t("results.questions.noDifferences")
    : null;
  return (
    <section aria-labelledby="question-changes" className="space-y-2">
      <div>
        <h2 id="question-changes" className="text-lg">
          {t("results.questions.changes")}
        </h2>
        {status && (
          <p className="mt-0.5 flex items-center gap-1 font-semibold">
            <span className="text-muted">
              <NeutralIcon />
            </span>
            {status}
          </p>
        )}
        {c && <p className="text-sm text-muted">{t("results.questions.savedOn", { when: formatWhen(c.baseline_saved_at) })}</p>}
        {c?.ran_differently && <p className="text-sm text-muted">{t("compare.ranDifferently")}</p>}
      </div>
      {c ? (
        <button type="button" onClick={onOpenCompare} className={secondaryButton}>
          {t("results.questions.openCompare")}
        </button>
      ) : (
        <BaselineCard onOpenCompare={onOpenCompare} />
      )}
    </section>
  );
}

function Summary({
  result,
  views,
  onReview,
  onOpenLimits,
  onOpenHelp,
}: {
  result: DiscoveryResult;
  views: QuestionView[];
  onReview: (id: string) => void;
  onOpenLimits: () => void;
  onOpenHelp?: (section: string) => void;
}) {
  const { t } = useTranslation();
  const h = headline(result, t, views);
  // Nothing to look at: say what was heard (device types only), so "not detected" is concrete.
  const heard = h.target === null ? heardLine(result, t) : null;
  const ai = (result.explanations?.items ?? []).some((e) => e.source === "ai");
  const ran = checkRows(result);
  const notChecked = ran.filter((r) => r.state === "notChecked").length;
  const partial = notChecked > 0;
  const recover = recoveryStep(coverageOf(result));
  return (
    <div>
      {/* Compact: the headline, one sentence, the coverage line and the one next action. */}
      <section aria-labelledby="summary-title" className="summary-glow rounded-card border border-line bg-surface px-2 py-2 shadow-soft sm:px-3">
        <h2 id="summary-title" className="text-lg font-semibold tracking-tight sm:text-xl">
          {h.title}
        </h2>
        <p className="mt-0.5 max-w-measure text-muted">{h.body}</p>
        {heard && <p className="mt-0.5 max-w-measure text-muted">{heard}</p>}
        {ran.length > 0 && (
          <p className="mt-1 flex flex-wrap items-center gap-x-1 gap-y-0.5 text-sm">
            {/* Neutral when every part ran: a tick here would read as "passed". */}
            <span className={partial ? "text-sev-medium" : "text-muted"}>{partial ? <ProblemIcon /> : <NeutralIcon />}</span>
            <span className="font-semibold">
              {partial
                ? t("results.coverageLine.partial", { checked: ran.length - notChecked, total: ran.length })
                : t("results.coverageLine.full", { count: ran.length })}
            </span>
            <span aria-hidden="true">·</span>
            <button type="button" onClick={onOpenLimits} className="font-semibold text-accent underline underline-offset-4 hover:text-accent-hover">
              {partial ? t("results.viewPartial") : t("results.coverageLine.see")}
            </button>
          </p>
        )}
        {/* The one step that would let the next check cover more, for the actual reason. */}
        {partial && recover && !(result.mode === "passive" && recover.endsWith("passive_mode")) && (
          <p className="mt-0.5 flex items-start gap-1 text-sm">
            <span className="mt-0.5 text-accent">
              <ArrowIcon />
            </span>
            <span>
              <span className="font-semibold">{t("results.recoverLabel")}: </span>
              {t(recover)}
            </span>
          </p>
        )}
        {h.target && (
          <div className="mt-1.5">
            <button type="button" id="summary-review" onClick={() => h.target && onReview(h.target.id)} className={primaryButton}>
              {reviewLabel(h.target, t)}
            </button>
          </div>
        )}
      </section>
      <p className="mt-1 flex items-start gap-1 text-sm text-muted">
        <span className="text-accent">
          <InfoIcon />
        </span>
        <span>
          {ai ? t("results.ai") : t("results.aiStandard")}{" "}
          {onOpenHelp ? (
            <button type="button" onClick={() => onOpenHelp("help-priority")} className="font-semibold text-accent underline underline-offset-4 hover:text-accent-hover">
              {t("results.rulesLink")}
            </button>
          ) : (
            t("results.rulesLink")
          )}
        </span>
      </p>
    </div>
  );
}

/** Every device these checks heard, including ones with no findings. Never called safe. */
function AllDevices({ result }: { result: DiscoveryResult }) {
  const { t } = useTranslation();
  const handover = useHandover().data;
  if (result.devices.length === 0) return null;
  return (
    <details id="all-devices" className="group rounded-card border border-line bg-surface shadow-soft">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 rounded-card px-3 py-2 font-semibold transition-colors hover:bg-canvas">
        {t("results.allDevices.summary", { count: result.devices.length })}
        <span className="text-muted transition-transform group-open:rotate-180">
          <ChevronIcon />
        </span>
      </summary>
      <div className="px-3 pb-2">
        <p className="text-sm text-muted">{t("results.allDevices.intro")}</p>
        <div className="mt-1 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-line">
                <th scope="col" className="py-0.5 pr-2">{t("results.allDevices.device")}</th>
                <th scope="col" className="py-0.5 pr-2">{t("results.allDevices.type")}</th>
                <th scope="col" className="py-0.5 pr-2">{t("results.allDevices.confidence")}</th>
                <th scope="col" className="py-0.5 pr-2">{t("results.allDevices.maker")}</th>
                <th scope="col" className="py-0.5">{t("results.allDevices.findings")}</th>
              </tr>
            </thead>
            <tbody>
              {result.devices.map((d) => {
                const found = result.findings.filter((f) => f.device_ref === d.id);
                const subject = found[0]?.subject;
                const name = (subject && handover?.names?.[subject]) || d.hostnames[0] || d.ip || t("results.unknownDevice");
                const known = d.fingerprint && d.fingerprint.type !== "unknown";
                return (
                  <tr key={d.id} className="border-b border-line align-top last:border-0">
                    <th scope="row" className="py-0.5 pr-2 font-semibold">{name}</th>
                    <td className="py-0.5 pr-2">{known ? d.fingerprint!.label : t("results.allDevices.typeUnknown")}</td>
                    <td className="py-0.5 pr-2">{known ? t(`results.band.${d.fingerprint!.band}`) : "—"}</td>
                    <td className="py-0.5 pr-2">{d.vendor ?? t("results.allDevices.makerUnknown")}</td>
                    <td className="py-0.5">
                      {found.length ? t("results.allDevices.findingsCount", { count: found.length }) : t("results.allDevices.noFindings")}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </details>
  );
}

/** "Coverage and limits": every check in one list (Checked, Not detected, or Not checked with a
 * short reason), then what no check can see. */
function CoverageAndLimits({
  result,
  detailsRef,
  startOpen,
}: {
  result: DiscoveryResult;
  detailsRef: RefObject<HTMLDetailsElement | null>;
  startOpen: boolean;
}) {
  const { t } = useTranslation();
  // Only the first render decides; after that the person opens and closes it.
  const [initiallyOpen] = useState(startOpen);
  const rows = checkRows(result);
  const totalAfter = totalRowAfter(result);
  const notChecked = rows.filter((r) => r.state === "notChecked").length;
  const cantSee = result.summary?.cant_see ?? [];
  return (
    <details id={LIMITS_ID} ref={detailsRef} open={initiallyOpen} className="group rounded-card border border-line bg-surface shadow-soft">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 rounded-card px-3 py-2 transition-colors hover:bg-canvas">
        <span>
          <h2 className="text-lg">{t("results.limits.title")}</h2>
          <span className="block text-sm text-muted">
            {notChecked > 0
              ? t("results.coverageLine.partial", { checked: rows.length - notChecked, total: rows.length })
              : t("results.coverageLine.full", { count: rows.length })}
          </span>
        </span>
        <span className="text-muted transition-transform group-open:rotate-180">
          <ChevronIcon />
        </span>
      </summary>
      <div className="px-3 pb-3">
        <table className="w-full text-left">
          <thead className="sr-only">
            <tr>
              <th scope="col">{t("results.limits.check")}</th>
              <th scope="col">{t("results.limits.result")}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ check, state, reason }, i) => (
              <Fragment key={check.name}>
              <tr className="border-t border-line align-top">
                <th scope="row" className="py-1 pr-2 font-medium">
                  {check.label}
                </th>
                <td className="py-1">
                  <span className="inline-flex items-start gap-0.5">
                    {/* A tick only where a check ran and has something to show. "Not detected"
                        gets a neutral mark, so it never reads as "passed". */}
                    <span className={state === "notChecked" ? "text-sev-medium" : state === "notDetected" ? "text-muted" : "text-accent"}>
                      {state === "notChecked" ? <ProblemIcon /> : state === "notDetected" ? <NeutralIcon /> : <StepIcon state="done" />}
                    </span>
                    <span>
                      {state === "checked" || state === "notDetected"
                        ? rowText({ check, state, reason }, t)
                          : reason
                            ? t("results.limits.notChecked", { reason })
                            : t("results.limits.notCheckedBare")}
                    </span>
                  </span>
                </td>
              </tr>
              {/* Every device heard, each counted once: the summary's number, so the rows
                  above visibly add up to it. */}
              {i === totalAfter && (
                <tr className="border-t border-line align-top" data-testid="devices-total">
                  <th scope="row" className="py-1 pr-2 font-semibold">
                    {t("results.limits.totalLabel")}
                  </th>
                  <td className="py-1 font-semibold">{t("results.limits.total", { count: result.devices.length })}</td>
                </tr>
              )}
              </Fragment>
            ))}
          </tbody>
        </table>
        {cantSee.length > 0 && (
          <>
            <h3 className="mt-2 font-semibold">{t("results.limits.cantSee")}</h3>
            <ul className="mt-1 space-y-1 text-muted">
              {cantSee.map((line) => (
                <li key={line} className="flex gap-1.5">
                  <span aria-hidden="true" className="mt-1 size-0.75 shrink-0 rounded-full bg-muted" />
                  <span>{line}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </details>
  );
}
