import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ChevronIcon, HelpIcon, NewCheckIcon, StepIcon } from "../components/icons";
import { LogoMark, Wordmark } from "../components/Logo";
import { Button } from "./Button";
import { insetClass } from "./classes";
import { PHONE_QUERY, useMediaQuery } from "./useMediaQuery";

export type Page = "check" | "results" | "nearby" | "handover" | "compare" | "report" | "verify" | "help";
export type Stage = "start" | "scanning" | "results";
const MAIN: Page[] = ["results", "nearby", "handover", "compare", "report"];
// On a phone: these three are tabs and the rest are in the "More" menu, so no label is cut off.
const PHONE_TABS: Page[] = ["results", "nearby", "handover"];
const PHONE_MORE: Page[] = ["compare", "report", "verify"];

interface Props {
  stage: Stage;
  current: Page | null;
  onNavigate: (page: Page) => void;
  hasResults: boolean; // results exist: the navigation row is shown
  baselineSaved: boolean;
  /** A saved scan exists, even an unreadable one: Compare is listed before a check, so it can be
   * looked at or replaced. */
  hasBaseline?: boolean;
  openTasks: number;
  onNewCheck: () => void;
  onSaveBaseline: () => Promise<unknown>;
  /** The logo: to Start, or to the check's progress while one is running. */
  onHome?: () => void;
  /** Demo mode (`python -m app --demo`): a "Demo data" tag on every page. */
  demo?: boolean;
}

/** The one header: a brand row (mark, wordmark, descriptor; quiet actions for the stage) and,
 * once there are results, a navigation row. Sticky, with a light shadow only once content
 * scrolls under it. The active page has a teal underline and bolder text, never a fill. On a
 * phone the row has three tabs and a "More" menu, so every label shows whole. */
export function AppHeader(props: Props) {
  const { t } = useTranslation();
  const { stage, current, onNavigate, hasResults, baselineSaved, hasBaseline = baselineSaved, openTasks } = props;
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 0);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  const showNav = hasResults;
  const phone = useMediaQuery(PHONE_QUERY);

  // compact: on a phone, just the icon (the label stays as its name), so the brand row fits.
  const tool = (page: Page, label: string, icon?: React.ReactNode, compact = false) => (
    <li key={page}>
      <NavItem page={page} current={current} onNavigate={onNavigate} quiet>
        {icon}
        <span className={compact ? "sr-only sm:not-sr-only" : undefined}>{label}</span>
      </NavItem>
    </li>
  );
  const tabLabel = (page: Page) => (
    <>
      {t(`nav.${page}`)}
      {page === "handover" && openTasks > 0 && (
        <>
          <span aria-hidden="true" className="tabular-nums">
            · {openTasks}
          </span>
          <span className="sr-only">, {t("nav.openTasks", { count: openTasks })}</span>
        </>
      )}
    </>
  );

  return (
    <header
      className={`sticky top-0 z-30 border-b border-line bg-surface transition-shadow ${scrolled ? "shadow-soft" : ""}`}
    >
      <div className="relative mx-auto flex max-w-content flex-wrap items-center justify-between gap-x-1 gap-y-0.5 px-1.5 py-1 sm:gap-x-2 sm:px-3">
        <p className="flex min-w-0 items-center gap-1">
          {/* The mark and wordmark go to Start (#/), with the app's focus ring. While a check
              runs they go to its progress instead: never cancelling or restarting it. */}
          <a
            href="#/"
            aria-label={t("app.home")}
            onClick={(e) => {
              e.preventDefault();
              props.onHome?.();
            }}
            className="flex shrink-0 items-center gap-1 rounded-control"
          >
            <LogoMark />
            <Wordmark>{t("app.name")}</Wordmark>
          </a>
          <span className="hidden truncate text-sm text-muted sm:inline">{t("app.tagline")}</span>
          {props.demo && (
            <span className="shrink-0 rounded-full border border-sev-medium bg-sev-medium-tint px-1 py-0.5 text-sm font-semibold text-ink">
              {t("app.demoTag")}
            </span>
          )}
        </p>
        <div className="flex flex-wrap items-center justify-end gap-0.5 sm:gap-1">
          {stage === "scanning" && <InProgress current={current} onNavigate={onNavigate} />}
          {stage === "results" && <NewCheck {...props} />}
          <nav aria-label={t("nav.tools")}>
            <ul className="flex items-center gap-1">
              {stage === "start" && hasBaseline && tool("compare", t("nav.compare"))}
              {stage === "start" && !showNav && tool("verify", t("nav.verify"))}
              {tool("help", t("nav.help"), <HelpIcon />, true)}
            </ul>
          </nav>
        </div>
      </div>
      {showNav && phone && (
        <nav aria-label={t("nav.label")} className="border-t border-line">
          <ul className="mx-auto flex max-w-content flex-wrap items-stretch justify-between px-1 max-[400px]:px-0.5">
            {PHONE_TABS.map((page) => (
              <li key={page} className="flex">
                <NavItem page={page} current={current} onNavigate={onNavigate} compact>
                  {tabLabel(page)}
                </NavItem>
              </li>
            ))}
            <li className="flex">
              <MoreMenu pages={PHONE_MORE} current={current} onNavigate={onNavigate} />
            </li>
          </ul>
        </nav>
      )}
      {showNav && !phone && (
        <nav aria-label={t("nav.label")} className="border-t border-line">
          <div className="mx-auto flex max-w-content items-stretch justify-between gap-2 px-2 sm:px-3">
            {/* Scrolls sideways on narrow screens; the fade at the edge says there's more. */}
            <ul className="scroll-cue flex min-w-0 scroll-px-3 items-stretch gap-0.5 overflow-x-auto">
              {MAIN.map((page) => (
                <li key={page} className="flex">
                  <NavItem page={page} current={current} onNavigate={onNavigate}>
                    {tabLabel(page)}
                  </NavItem>
                </li>
              ))}
            </ul>
            <ul className="flex shrink-0 items-stretch">
              <li className="flex">
                <NavItem page="verify" current={current} onNavigate={onNavigate}>
                  {t("nav.verify")}
                </NavItem>
              </li>
            </ul>
          </div>
        </nav>
      )}
    </header>
  );
}

function NavItem({
  page,
  current,
  onNavigate,
  quiet = false,
  compact = false,
  children,
}: {
  page: Page;
  current: Page | null;
  onNavigate: (page: Page) => void;
  quiet?: boolean;
  compact?: boolean; // the phone's tab row: less padding, so every label fits whole
  children: React.ReactNode;
}) {
  const here = page === current;
  // Tabs: a 3 px underline in deep teal (6.33:1) and bolder text when current; a lighter
  // underline on hover; the ink focus ring when focused. Brand-row links are quiet text.
  const look = quiet
    ? `rounded-control px-1 py-0.5 text-sm ${here ? "font-bold text-ink underline decoration-accent decoration-3 underline-offset-6" : "font-semibold text-accent hover:text-accent-hover hover:underline"}`
    : `whitespace-nowrap border-b-3 ${compact ? "px-1 max-[400px]:px-0.5 max-[400px]:text-sm" : "px-1.5"} py-1 text-base ${here ? "border-accent font-bold text-ink" : "border-transparent font-medium text-muted hover:border-line-strong hover:text-ink"}`;
  return (
    <button
      type="button"
      // A stable id, so Back can return focus to the tab that was used (App's history).
      id={quiet ? `tool-${page}` : `nav-${page}`}
      aria-current={here ? "page" : undefined}
      onClick={() => !here && onNavigate(page)}
      // In the sideways-scrolling tab row, bring a tab fully into view when it gets focus: the
      // browser leaves a half-visible one where it is, partly under the fade.
      onFocus={(e) => !quiet && e.currentTarget.scrollIntoView?.({ block: "nearest", inline: "nearest" })}
      className={`inline-flex items-center gap-0.5 transition-colors ${look}`}
    >
      {children}
    </button>
  );
}

/** The phone's "More" menu: Compare, Report and Verify a report. A button that opens a list
 * (aria-expanded). Escape closes it and returns focus to the button; so do a click outside it
 * and moving focus out of it. Choosing a page closes it. While one of its pages is open, the
 * button is underlined like a current tab, and that page is marked as current in the list. */
function MoreMenu({ pages, current, onNavigate }: { pages: Page[]; current: Page | null; onNavigate: (page: Page) => void }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const first = useRef<HTMLButtonElement>(null);
  const id = useId();
  const inside = current !== null && pages.includes(current);

  useEffect(() => {
    if (!open) return;
    first.current?.focus();
    const onDown = (e: PointerEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", onDown);
    return () => document.removeEventListener("pointerdown", onDown);
  }, [open]);

  return (
    <div
      ref={box}
      className="relative flex"
      onKeyDown={(e) => {
        if (e.key === "Escape" && open) {
          e.stopPropagation();
          setOpen(false);
          button.current?.focus();
        }
      }}
      onBlur={(e) => {
        if (open && !e.currentTarget.contains(e.relatedTarget as Node | null)) setOpen(false);
      }}
    >
      <button
        ref={button}
        id="nav-more"
        type="button"
        aria-expanded={open}
        aria-controls={`${id}-menu`}
        onClick={() => setOpen((o) => !o)}
        className={`inline-flex items-center gap-0.5 whitespace-nowrap border-b-3 px-1 py-1 text-base transition-colors max-[400px]:px-0.5 max-[400px]:text-sm ${inside ? "border-accent font-bold text-ink" : "border-transparent font-medium text-muted hover:border-line-strong hover:text-ink"}`}
      >
        {t("nav.more")}
        <span className={`transition-transform ${open ? "rotate-180" : ""}`}>
          <ChevronIcon />
        </span>
      </button>
      {open && (
        <ul
          id={`${id}-menu`}
          aria-label={t("nav.moreLabel")}
          className="absolute top-full right-0 z-40 mt-px min-w-40 rounded-inner border border-line bg-surface py-0.5 shadow-soft"
        >
          {pages.map((page, i) => (
            <li key={page}>
              <button
                ref={i === 0 ? first : undefined}
                id={`nav-${page}`}
                type="button"
                aria-current={page === current ? "page" : undefined}
                onClick={() => {
                  setOpen(false);
                  if (page !== current) onNavigate(page);
                }}
                className={`block w-full px-2 py-1 text-left whitespace-nowrap transition-colors hover:bg-canvas ${page === current ? "font-bold text-ink underline decoration-accent decoration-3 underline-offset-6" : "font-medium text-ink"}`}
              >
                {t(`nav.${page}`)}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** During a check: a quiet indicator, which takes you back to the check from other pages. */
function InProgress({ current, onNavigate }: { current: Page | null; onNavigate: (page: Page) => void }) {
  const { t } = useTranslation();
  const body = (
    <>
      <span className="text-accent">
        <StepIcon state="running" />
      </span>
      {t("nav.inProgress")}
    </>
  );
  if (current === "check") {
    return <p className="flex items-center gap-0.5 text-sm font-semibold text-muted">{body}</p>;
  }
  return (
    <button
      type="button"
      id="tool-check"
      onClick={() => onNavigate("check")}
      className="flex items-center gap-0.5 rounded-control px-1 py-0.5 text-sm font-semibold text-accent hover:text-accent-hover hover:underline"
    >
      {body}
    </button>
  );
}

/** "New check", which asks first. It says the current results will be replaced, and that the
 * handover data is kept; without a saved move-in scan, it offers to save one first. */
function NewCheck({ baselineSaved, onNewCheck, onSaveBaseline }: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [failed, setFailed] = useState(false);
  const keep = useRef<HTMLButtonElement>(null);
  const opener = useRef<HTMLButtonElement>(null);
  const id = useId();
  const was = useRef(false);
  useEffect(() => {
    if (open) keep.current?.focus();
    else if (was.current) opener.current?.focus();
    was.current = open;
  }, [open]);

  async function saveThenStart() {
    setSaving(true);
    setFailed(false);
    try {
      await onSaveBaseline();
      setOpen(false);
      onNewCheck();
    } catch {
      setFailed(true);
    } finally {
      setSaving(false);
    }
  }

  return (
    // The panel hangs from the header row (not the button), so on a phone it spans the screen
    // instead of running off its left edge.
    <div>
      <Button ref={opener} variant="secondary" size="sm" icon={<NewCheckIcon />} aria-expanded={open} aria-controls={`${id}-panel`} onClick={() => setOpen((o) => !o)}>
        {t("newCheck.button")}
      </Button>
      {open && (
        <div
          id={`${id}-panel`}
          role="group"
          aria-labelledby={`${id}-title`}
          onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
          className={`absolute inset-x-2 top-full z-40 border border-line bg-surface shadow-soft sm:left-auto sm:right-3 sm:w-48 ${insetClass}`}
        >
          <p id={`${id}-title`} className="font-semibold">
            {t("newCheck.title")}
          </p>
          <p className="mt-0.5 text-sm">{t("newCheck.body")}</p>
          {!baselineSaved && <p className="mt-0.5 text-sm">{t("newCheck.noBaseline")}</p>}
          <div className="mt-1 flex flex-wrap gap-1">
            <Button ref={keep} variant="secondary" size="sm" onClick={() => setOpen(false)}>
              {t("newCheck.cancel")}
            </Button>
            {!baselineSaved && (
              <Button variant="primary" size="sm" loading={saving} onClick={() => void saveThenStart()}>
                {saving ? t("newCheck.saving") : t("newCheck.save")}
              </Button>
            )}
            <Button
              variant={baselineSaved ? "primary" : "text"}
              size="sm"
              onClick={() => {
                setOpen(false);
                onNewCheck();
              }}
            >
              {baselineSaved ? t("newCheck.start") : t("newCheck.startAnyway")}
            </Button>
          </div>
          {failed && (
            <p role="alert" className="mt-1 text-sm font-semibold text-sev-high">
              {t("newCheck.saveFailed")}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
