import { useQuery } from "@tanstack/react-query";
import { useId, useRef, useState, type FormEvent } from "react";
import { Trans, useTranslation } from "react-i18next";

import { getSetup } from "../api/client";
import type { StayType } from "../api/types";
import { InfoIcon } from "../components/icons";
import { Readiness } from "../components/Readiness";
import { PermissionMessage } from "../components/PermissionMessage";
import { ScreenHeading } from "../components/ScreenHeading";
import { Button } from "../ds/Button";
import { Notice } from "../ds/Feedback";
import { choicePillClass } from "../ds/classes";
import { RadioRow } from "../ds/Fields";
import { SETUP_KEY } from "../handover/keys";
import { SCAN_MINUTES } from "../scan/timing";

export type Permission = "yes" | "no";

interface Props {
  onStart: (consent: boolean, stay: StayType) => void;
  /** Opens Help at one of its sections ("help-cant", "help-online"), keeping Start as it is. */
  onOpenHelp?: (section: string) => void;
  /** Demo mode: a banner says the data is made up and nothing is scanned. */
  demo?: boolean;
  /** Results from an earlier check: a small link back to them, under the connection bar. */
  latest?: { when: string; onView: () => void };
  starting?: boolean;
  error?: string | null;
  focusHeading?: boolean; // true when coming back from another screen
}

// "No" and "I'm not sure" are one answer: both only listen.
const ANSWERS: Permission[] = ["yes", "no"];
const STAYS: StayType[] = ["short_stay", "rental", "hostel", "other"];

const link = "font-semibold text-accent underline underline-offset-4 hover:text-accent-hover";

/** Screen 1, top to bottom: the title and one line, the connection bar, the permission choice,
 * where you're staying, the start button, then one line on what to know (the detail is in
 * Help). Only "Yes" gives consent for active checks; "No, or I'm not sure" only listens.
 * Nothing is chosen at first. */
export function Start({ onStart, onOpenHelp, demo = false, latest, starting = false, error = null, focusHeading = false }: Props) {
  const { t } = useTranslation();
  const [answer, setAnswer] = useState<Permission | null>(null);
  // Optional: nothing chosen counts as "Other", which uses each rule's default next steps.
  const [stay, setStay] = useState<StayType | null>(null);
  // "Choose an answer to continue" appears only once Start is pressed with no answer.
  const [tried, setTried] = useState(false);
  const [whatCounts, setWhatCounts] = useState(false);
  const answers = useRef<HTMLDivElement>(null);
  const id = useId();
  const needsAnswer = tried && answer === null;
  // The one start button. If anything the chosen check needs is missing (from the readiness
  // strip), it says so: never "full check" when parts of it can't run.
  const setup = useQuery({ queryKey: SETUP_KEY, queryFn: getSetup, retry: false }).data;
  const missing = (setup?.items ?? []).filter((i) => !i.ready && (answer === "yes" || i.name !== "nmap"));
  const limited = Boolean(setup) && (missing.length > 0 || setup?.network.kind === "none");
  const label = starting
    ? t("start.starting")
    : answer && limited
      ? t("start.startLimited")
      : answer === "yes"
        ? t("start.startFull")
        : answer
          ? t("start.startListen")
          : t("start.startButton");

  function submit(e: FormEvent) {
    e.preventDefault();
    if (starting) return;
    if (answer === null) {
      // Nothing starts without an answer: say so, and put the focus on the first answer.
      setTried(true);
      answers.current?.querySelector("input")?.focus();
      return;
    }
    onStart(answer === "yes", stay ?? "other");
  }

  return (
    <div className="space-y-1.5">
      <div className="space-y-0.5">
        <ScreenHeading focus={focusHeading}>
          {/* <nw> keeps "Wi-Fi" on one line instead of breaking at its hyphen. */}
          <Trans i18nKey="start.title" components={{ nw: <span className="whitespace-nowrap" /> }} />
        </ScreenHeading>
        <p className="text-muted">{t("start.intro", { minutes: SCAN_MINUTES })}</p>
      </div>

      {demo && (
        <div role="note" aria-label={t("start.demo.title")}>
          <Notice tone="warning" title={t("start.demo.title")}>
            {t("start.demo.body")}
          </Notice>
        </div>
      )}

      <Readiness />
      {latest && (
        <p className="text-sm">
          <button type="button" onClick={latest.onView} className={link}>
            {t("start.latest", { when: latest.when })}
          </button>
        </p>
      )}

      <form onSubmit={submit} noValidate className="rounded-card border border-line bg-surface px-2 py-2 shadow-soft sm:px-3">
        <fieldset aria-describedby={`${id}-hint${needsAnswer ? ` ${id}-required` : ""}`}>
          <legend className="text-card font-semibold">{t("start.permission.legend")}</legend>
          <p id={`${id}-hint`} className="mt-0.5 text-sm">
            {t("start.permission.hint")}{" "}
            <button
              type="button"
              aria-expanded={whatCounts}
              aria-controls={`${id}-counts`}
              onClick={() => setWhatCounts((open) => !open)}
              className={link}
            >
              {t("start.permission.whatCounts")}
            </button>
          </p>
          {/* The explanation, the legal line included, one click away. */}
          <div id={`${id}-counts`} hidden={!whatCounts} className="mt-0.5 rounded-inner bg-raised px-1.5 py-1 text-sm">
            <ul className="space-y-0.5">
              <li>{t("start.permission.whatCountsBody.own")}</li>
              <li>{t("start.permission.whatCountsBody.said")}</li>
              <li>{t("start.permission.legal")}</li>
              <li className="text-muted">{t("start.permission.whatCountsBody.advice")}</li>
            </ul>
          </div>
          <div ref={answers} className="mt-1 space-y-0.5">
            {ANSWERS.map((a) => (
              <RadioRow
                key={a}
                name="permission"
                value={a}
                checked={answer === a}
                onChange={() => setAnswer(a)}
                label={t(`start.permission.${a}`)}
                hint={t(`start.permission.${a}Hint`)}
              />
            ))}
          </div>
          {/* Only after Start was pressed without an answer, and announced. */}
          <div aria-live="polite">
            {needsAnswer && (
              <p id={`${id}-required`} className="mt-0.5 flex items-center gap-1 text-sm font-semibold">
                <span className="text-accent">
                  <InfoIcon />
                </span>
                {t("start.permission.required")}
              </p>
            )}
          </div>
          {/* Listening only: a way to get permission in writing for next time. */}
          {answer === "no" && (
            <div className="mt-1">
              <PermissionMessage />
            </div>
          )}
        </fieldset>

        <fieldset aria-describedby={`${id}-stay-hint`} className="mt-1">
          <legend className="font-semibold">
            {t("start.stay.legend")} <span className="ml-0.5 text-sm font-normal text-muted">{t("start.stay.optional")}</span>
          </legend>
          <p id={`${id}-stay-hint`} className="sr-only">
            {t("start.stay.hint")}
          </p>
          {/* Compact pills with short names; each one's full description is its tooltip and is
              read out with it. */}
          <div className="mt-0.5 flex flex-wrap gap-1">
            {STAYS.map((s) => (
              <label key={s} className={choicePillClass(stay === s)} title={t(`start.stay.${s}Description`)}>
                <input
                  type="radio"
                  name="stay"
                  value={s}
                  checked={stay === s}
                  onChange={() => setStay(s)}
                  aria-describedby={`${id}-stay-${s}`}
                  className="size-2 accent-accent"
                />
                {t(`start.stay.${s}`)}
              </label>
            ))}
          </div>
          {/* Outside the labels, so each name stays short; aria-describedby reads them. */}
          <div hidden>
            {STAYS.map((s) => (
              <span key={s} id={`${id}-stay-${s}`}>
                {t(`start.stay.${s}Description`)}
              </span>
            ))}
          </div>
        </fieldset>

        <div className="mt-1 flex flex-col gap-1 sm:flex-row sm:items-center sm:gap-2">
          <Button
            type="submit"
            variant="primary"
            loading={starting}
            aria-describedby={needsAnswer ? `${id}-required` : undefined}
            className="w-full text-lg sm:w-auto"
          >
            {label}
          </Button>
          <p className="text-sm text-muted">{t("start.meta")}</p>
        </div>
        {error && (
          <p role="alert" className="mt-1 font-semibold text-sev-high">
            {error}
          </p>
        )}
      </form>

      {/* One line. What it can't see, and the full list of outside calls, are in Help. */}
      <p className="pt-0.5 text-sm text-muted">
        <Trans
          i18nKey="start.footer"
          components={{
            cant: <button type="button" onClick={() => onOpenHelp?.("help-cant")} className={link} />,
            sent: <button type="button" onClick={() => onOpenHelp?.("help-online")} className={link} />,
          }}
        />
      </p>
    </div>
  );
}
