import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, getBaseline, getHealth, getScan, saveBaseline, startScan } from "./api/client";
import type { DiscoveryResult, StayType } from "./api/types";
import { secondaryButton } from "./components/styles";
import { Hint, Notice } from "./components/ui";
import { AppHeader, type Page, type Stage } from "./ds/AppHeader";
import { ScanContext } from "./ds/scanContext";
import { useHandover } from "./handover/useHandover";
import { formatWhen } from "./format";
import { BASELINE_KEY, COMPARE_KEY, HANDOVER_KEY } from "./handover/keys";
import {
  findByKey,
  focusKeyOf,
  needsResult,
  parseHash,
  rememberCheck,
  routeHash,
  storedCheck,
  type FocusKey,
  type Route,
} from "./route";
import { Compare } from "./screens/Compare";
import { Handover } from "./screens/Handover";
import { Locator } from "./screens/Locator";
import { Nearby } from "./screens/Nearby";
import { Report } from "./screens/Report";
import { Results, type HandoverFocus } from "./screens/Results";
import { Scanning } from "./screens/Scanning";
import { Start } from "./screens/Start";
import { Help } from "./screens/Help";
import { Verify } from "./screens/Verify";
import { isOpen } from "./handover/message";

type Screen = Route;

// Which top-bar page each screen belongs to: the locator is part of Nearby.
const PAGE_OF: Partial<Record<Screen["name"], Page>> = {
  check: "check",
  results: "results",
  nearby: "nearby",
  locator: "nearby",
  handover: "handover",
  compare: "compare",
  report: "report",
  verify: "verify",
  help: "help",
};

// Pages kept as they are (just hidden) while Help is open, so no work is lost.
const KEPT_UNDER_HELP: Screen["name"][] = ["start", "handover", "report"];

// Pages that show the results of a check.
const RESULT_SCREENS: Screen["name"][] = ["results", "nearby", "locator", "handover", "report"];

interface Check {
  id: string;
  consent: boolean;
  finished: boolean; // its results are in; until then, the result pages show the previous check
}

/** The history entry's position, so focus can be returned to the right control on Back. */
function entryIndex(): number {
  const state: unknown = window.history.state;
  return state && typeof state === "object" && "rc" in state && typeof state.rc === "number" ? state.rc : 0;
}

export function App() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [screen, setScreen] = useState<Screen>(() => parseHash(window.location.hash));
  // Opening Help from Start, Handover or Report keeps that page (hidden) underneath, so going
  // back finds every choice and everything typed as it was.
  const [behindHelp, setBehindHelp] = useState<Screen | null>(null);
  const [handoverFocus, setHandoverFocus] = useState<HandoverFocus | undefined>(undefined);
  const [helpSection, setHelpSection] = useState<string | undefined>(undefined);
  const [result, setResult] = useState<DiscoveryResult | null>(null); // the latest finished check
  const [check, setCheck] = useState<Check | null>(null); // the check started from this page
  const [returned, setReturned] = useState(false); // back on Start after another screen
  const [lost, setLost] = useState(false); // a refresh asked for a page whose data is gone
  // After a refresh: is the stored check still on the server? Until we know, show nothing.
  const [restoring, setRestoring] = useState(() => needsResult(parseHash(window.location.hash)) || parseHash(window.location.hash).name === "check");
  const health = useQuery({ queryKey: ["health"], queryFn: getHealth, retry: false });
  const demoMode = health.data?.demo === true; // made-up data: said on every page
  const baseline = useQuery({ queryKey: BASELINE_KEY, queryFn: getBaseline, retry: false });
  const handover = useHandover().data;

  // --- history ---------------------------------------------------------------------------
  const index = useRef(entryIndex());
  const focusBy = useRef(new Map<number, FocusKey>()); // entry -> the control that left it
  // After Back or Forward: the control to focus again, or the page title.
  const pendingFocus = useRef<FocusKey | "title" | null>(null);
  const screenRef = useRef(screen);
  const backToTitle = useRef(false); // Help's own Back button: focus the page title
  const checkRef = useRef(check);
  // The latest screen and check, for the history handlers (set after each render).
  useLayoutEffect(() => {
    screenRef.current = screen;
    checkRef.current = check;
  });

  const enter = useCallback((next: Screen, from: Screen, lost = false) => {
    setBehindHelp(next.name === "help" && KEPT_UNDER_HELP.includes(from.name) ? from : null);
    if (next.name !== "help") setHelpSection(undefined); // the next visit opens at the top
    setLost(lost);
    setScreen(next);
  }, []);

  /** Go to a screen as a new history entry, remembering which control left this one. */
  const go = useCallback(
    (next: Screen, opts: { replace?: boolean; lost?: boolean } = {}) => {
      const key = focusKeyOf(document.activeElement);
      if (key) focusBy.current.set(index.current, key);
      const hash = routeHash(next);
      if (opts.replace || hash === window.location.hash) {
        window.history.replaceState({ rc: index.current }, "", hash);
      } else {
        index.current += 1;
        window.history.pushState({ rc: index.current }, "", hash);
      }
      enter(next, screenRef.current, opts.lost);
    },
    [enter],
  );

  useEffect(() => {
    // The first entry gets an index, and an address if it had none.
    window.history.replaceState({ rc: index.current }, "", routeHash(screenRef.current));
    const onPop = () => {
      const leaving = focusKeyOf(document.activeElement);
      if (leaving) focusBy.current.set(index.current, leaving);
      index.current = entryIndex();
      let next = parseHash(window.location.hash);
      // During a check, Back to Start returns to the check's progress instead: the check is
      // never lost or started again by Back.
      const running = checkRef.current && !checkRef.current.finished;
      if (running && next.name === "start") {
        next = { name: "check" };
        window.history.replaceState({ rc: index.current }, "", routeHash(next));
      }
      pendingFocus.current = backToTitle.current ? "title" : (focusBy.current.get(index.current) ?? null);
      backToTitle.current = false;
      enter(next, screenRef.current);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [enter]);

  // Back or Forward: once the screen is drawn (and has focused its own title), return focus to
  // the control that was used to leave it, e.g. "Locate signal" on Nearby.
  // A passive effect: the screens' own (title) effects run first, as children, so this one wins;
  // once more on the next tick, for anything that focuses itself a moment later.
  useEffect(() => {
    const key = pendingFocus.current;
    if (!key) return;
    pendingFocus.current = null;
    const restore = () =>
      (key === "title" ? document.querySelector<HTMLElement>("main > div:not([hidden]) h1, main > * h1") : findByKey(key))?.focus();
    restore();
    const id = window.setTimeout(restore, 0);
    return () => window.clearTimeout(id);
  }, [screen]);

  // --- a refresh: get the stored check back from the server, if it still has it -------------
  useEffect(() => {
    if (!restoring) return;
    const stored = storedCheck();
    const giveUp = () => {
      setRestoring(false);
      go({ name: "start" }, { replace: true, lost: true });
    };
    if (!stored) {
      giveUp();
      return;
    }
    getScan(stored.id)
      .then((snap) => {
        if (snap.state === "done" && snap.result) {
          setResult(snap.result);
          const route = screenRef.current;
          const item = route.name === "locator" ? snap.result.nearby_items.find((i) => i.ref === route.ref) : true;
          if (route.name === "check" || !item) go({ name: "results" }, { replace: true });
          setRestoring(false);
        } else if (snap.state === "running") {
          setCheck({ id: stored.id, consent: stored.consent, finished: false });
          go({ name: "check" }, { replace: true });
          setRestoring(false);
        } else {
          giveUp();
        }
      })
      .catch(giveUp);
    // Only once, for the page as it was loaded.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // A screen whose data isn't here (e.g. an old address typed in): Start, with a message.
  useEffect(() => {
    if (restoring) return;
    const missing = (needsResult(screen) && !result) || (screen.name === "check" && !check);
    if (missing) {
      go({ name: "start" }, { replace: true, lost: true });
    } else if (screen.name === "locator" && result && !result.nearby_items.some((i) => i.ref === screen.ref)) {
      go({ name: "nearby" }, { replace: true });
    }
  }, [screen, result, check, restoring, go]);

  const kept = screen.name === "help" ? behindHelp?.name : undefined;
  const showing = (name: Screen["name"]) => screen.name === name || kept === name;

  const start = useMutation({
    mutationFn: ({ consent, stay }: { consent: boolean; stay: StayType }) => startScan(consent, stay),
    onSuccess: (started, { consent }) => {
      rememberCheck({ id: started.id, consent });
      setCheck({ id: started.id, consent, finished: false });
      go({ name: "check" });
    },
  });
  const startError = start.error
    ? start.error instanceof ApiError && start.error.detail
      ? start.error.detail
      : t("start.startFailed")
    : null;

  // The check finished: its results replace the previous ones, but the page stays put.
  const complete = useCallback(
    (r: DiscoveryResult) => {
      setResult(r);
      setCheck((c) => (c ? { ...c, finished: true } : c));
      for (const key of [HANDOVER_KEY, BASELINE_KEY, COMPARE_KEY]) void queryClient.invalidateQueries({ queryKey: key });
    },
    [queryClient],
  );
  const showResults = useCallback(() => {
    setCheck(null);
    go({ name: "results" });
  }, [go]);
  const restart = useCallback(() => {
    start.reset();
    setCheck(null);
    setReturned(true);
    go({ name: "start" });
  }, [start, go]);

  // The logo: Start, as a new history entry (Back returns here). While a check is running, its
  // progress page instead: the check is never cancelled or started again from here.
  const home = useCallback(() => {
    if (checkRef.current && !checkRef.current.finished) {
      go({ name: "check" });
      return;
    }
    setReturned(true); // Start's title takes focus, as when coming back to it
    go({ name: "start" });
  }, [go]);

  // The header adapts to the stage: Start (brand row only), a check running, then results. On
  // a later check, the previous results stay usable, labelled with their date.
  const has = result !== null;
  const saved = baseline.data?.state === "saved";
  const running = Boolean(check && !check.finished);
  const stage: Stage = running ? "scanning" : has ? "results" : "start";
  const openTasks = (handover?.tasks ?? []).filter(isOpen).length;
  const save = useMutation({
    mutationFn: saveBaseline,
    onSuccess: (info) => {
      queryClient.setQueryData(BASELINE_KEY, info);
      void queryClient.invalidateQueries({ queryKey: COMPARE_KEY });
    },
  });
  const showingPrevious = Boolean(check && !check.finished && result && RESULT_SCREENS.includes(screen.name));
  const locatorItem = screen.name === "locator" ? result?.nearby_items.find((i) => i.ref === screen.ref) : undefined;

  return (
    <ScanContext.Provider value={result}>
      <a
        href="#main"
        onClick={(e) => {
          // A plain jump to the content: the address (and history) stays on this screen.
          e.preventDefault();
          document.getElementById("main")?.focus();
        }}
        className="sr-only rounded-control bg-lagoon px-2 py-1 font-semibold text-ink focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50"
      >
        {t("app.skipToContent")}
      </a>
      <AppHeader
        stage={stage}
        current={PAGE_OF[screen.name] ?? null}
        onNavigate={(page) => go({ name: page } as Screen)}
        hasResults={has}
        baselineSaved={saved}
        hasBaseline={baseline.data !== undefined && baseline.data.state !== "none"}
        openTasks={openTasks}
        onNewCheck={restart}
        onSaveBaseline={() => save.mutateAsync()}
        onHome={home}
        demo={demoMode}
      />
      <main id="main" tabIndex={-1} className="mx-auto max-w-content px-2 pt-3 pb-10 outline-none sm:px-3">
        {health.data?.stale && (
          <div className="mb-3">
            <Notice title={t("app.stale")} />
          </div>
        )}
        {restoring && (
          <p role="status" className="text-muted">
            {t("app.restoring")}
          </p>
        )}
        {lost && screen.name === "start" && (
          <div className="mb-3" role="status">
            <Notice title={t("app.lostTitle")}>{t("app.lostBody")}</Notice>
          </div>
        )}
        {showingPrevious && result && (
          <div className="mb-3 flex flex-wrap items-center justify-between gap-1 rounded-inner bg-raised px-2 py-1.5">
            <Hint>{t("scanning.previous", { when: formatWhen(result.finished_at) })}</Hint>
            <button type="button" onClick={() => go({ name: "check" })} className={secondaryButton}>
              {t("scanning.backToCheck")}
            </button>
          </div>
        )}
        {!restoring && showing("start") && (
          <div hidden={screen.name !== "start"}>
            <Start
              onStart={(consent, stay) => start.mutate({ consent, stay })}
              onOpenHelp={(section) => {
                setHelpSection(section);
                go({ name: "help" });
              }}
              demo={demoMode}
              latest={result && !(check && !check.finished) ? { when: formatWhen(result.finished_at), onView: () => go({ name: "results" }) } : undefined}
              starting={start.isPending}
              error={startError}
              focusHeading={returned}
            />
          </div>
        )}
        {/* Kept mounted (just hidden) while you look at other pages, so the live connection
            and the completion state survive; it never takes you away by itself. */}
        {check && (
          <div hidden={screen.name !== "check"}>
            <Scanning
              key={check.id}
              scanId={check.id}
              consent={check.consent}
              onComplete={complete}
              onShowResults={showResults}
              onRestart={restart}
            />
          </div>
        )}
        {screen.name === "results" && result && (
          <Results
            result={result}
            onOpenNearby={() => go({ name: "nearby" })}
            onOpenCompare={() => go({ name: "compare" })}
            onOpenHandover={(focus) => {
              setHandoverFocus(focus);
              go({ name: "handover" });
            }}
            onOpenHelp={(section) => {
              setHelpSection(section);
              go({ name: "help" });
            }}
          />
        )}
        {screen.name === "nearby" && result && <Nearby result={result} onFind={(item) => go({ name: "locator", ref: item.ref })} />}
        {screen.name === "locator" && locatorItem && (
          <Locator key={locatorItem.ref} item={locatorItem} onBack={() => window.history.back()} />
        )}
        {showing("handover") && result && (
          <div hidden={screen.name !== "handover"}>
            <Handover focus={screen.name === "handover" ? handoverFocus : undefined} onOpenReport={() => go({ name: "report" })} />
          </div>
        )}
        {screen.name === "compare" && (
          <Compare
            result={result}
            onOpenHelp={(section) => {
              setHelpSection(section);
              go({ name: "help" });
            }}
          />
        )}
        {showing("report") && result && (
          <div hidden={screen.name !== "report"}>
            <Report
              result={result}
              onOpenHandover={() => {
                setHandoverFocus(undefined);
                go({ name: "handover" });
              }}
            />
          </div>
        )}
        {screen.name === "verify" && <Verify onBack={result === null && !check ? restart : undefined} />}
        {screen.name === "help" && (
          <Help
            section={helpSection}
            back={
              // From Handover or Report, a Back button returns to it as it was. From Start there
              // is none (the browser's Back and the header still return to it, as it was).
              behindHelp && behindHelp.name !== "start"
                ? {
                    label: t(`help.back.${behindHelp.name}`),
                    // The page underneath is the previous history entry: Back returns to it as
                    // it was, and moves focus to its title as a new page does.
                    onBack: () => {
                      backToTitle.current = true;
                      window.history.back();
                    },
                  }
                : undefined
            }
          />
        )}
      </main>
    </ScanContext.Provider>
  );
}
