import { useQuery } from "@tanstack/react-query";
import type { TFunction } from "i18next";
import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { cancelScan, getSetup } from "../api/client";
import type { DiscoveryResult, ScanSnapshot, StepStatus, StepView } from "../api/types";
import { ConfirmButton } from "../components/ConfirmButton";
import { ProblemIcon, StepIcon } from "../components/icons";
import { ScreenHeading } from "../components/ScreenHeading";
import { card, primaryButton, secondaryButton } from "../components/styles";
import { SETUP_KEY } from "../handover/keys";
import { formatElapsed, STEPS } from "../scan/progress";
import { SCAN_MINUTES, STOPPED_AFTER_MS } from "../scan/timing";
import { useLiveScan } from "../scan/useLiveScan";

interface Props {
  scanId: string;
  consent: boolean;
  onComplete: (result: DiscoveryResult) => void; // the check finished; its results exist now
  onShowResults: () => void;
  onRestart: () => void;
}

type Level = "live" | "fallback" | "stopped";

/** Screen 2. What's running now, every task's state, and the device count. If the live
 * connection drops, progress comes from polling; if every update stops, a panel says so. When
 * the check ends, the card says so and waits for you: it never jumps to another page. */
export function Scanning({ scanId, consent, onComplete, onShowResults, onRestart }: Props) {
  const { t } = useTranslation();
  const live = useLiveScan(scanId);
  // The network this check runs on, from the readiness check on Start (shown on this laptop only).
  const setup = useQuery({ queryKey: SETUP_KEY, queryFn: getSetup, retry: false }).data;
  const network =
    setup?.network.kind === "wifi" && setup.network.name
      ? setup.network.name
      : setup?.network.kind === "cable"
        ? t("compare.networkCable")
        : t("compare.networkUnknown");
  const { snapshot, interrupted } = live;
  const running = !snapshot || snapshot.state === "running";
  const now = useNow(running);

  const quietFor = live.receivedAt === null ? 0 : Math.max(0, now - live.receivedAt);
  const level: Level = !running ? "live" : quietFor > STOPPED_AFTER_MS ? "stopped" : interrupted ? "fallback" : "live";
  const announcement = useStepAnnouncement(snapshot?.steps);

  const result = snapshot?.state === "done" ? snapshot.result : null;
  useEffect(() => {
    if (result) onComplete(result);
  }, [result, onComplete]);

  if (snapshot?.state === "cancelled" || snapshot?.state === "failed" || live.failure) {
    const cancelled = snapshot?.state === "cancelled";
    // Until the cancelled check has really stopped, a new one can't start yet.
    const stopping = cancelled && Boolean(snapshot?.stopping);
    return (
      <div className="space-y-2">
        <ScreenHeading>
          {stopping ? t("scanning.stoppingTitle") : cancelled ? t("scanning.cancelledTitle") : t("scanning.failedTitle")}
        </ScreenHeading>
        <p className="text-lg text-muted" aria-live="polite">
          {stopping ? t("scanning.stoppingBody") : (snapshot?.error ?? live.failure)}
        </p>
        {cancelled && !stopping && <p className="max-w-measure">{t("scanning.cancelledKept")}</p>}
        {!stopping && (
          <button type="button" onClick={onRestart} className={primaryButton}>
            {t("scanning.startAgain")}
          </button>
        )}
      </div>
    );
  }

  const steps: StepView[] =
    snapshot?.steps ??
    STEPS.map((key) => ({ key, status: key === "services" && !consent ? ("skipped" as const) : ("upcoming" as const), problems: [] }));
  // Counted from the rows shown, so the numbers always match the list (a skipped task is done with).
  const finished = steps.filter((s) => s.status === "done" || s.status === "failed" || s.status === "skipped").length;
  const tasks = t("scanning.tasksDone", { done: finished, total: steps.length });
  const done = snapshot?.state === "done";
  const sinceReceived = running && live.receivedAt !== null ? (now - live.receivedAt) / 1000 : 0;
  const elapsed = snapshot ? snapshot.elapsed_seconds + sinceReceived : 0;

  return (
    <div className="space-y-2">
      <div>
        <ScreenHeading>{t("scanning.title")}</ScreenHeading>
        <p className="mt-0.5 text-sm text-muted">
          {t("scanning.context", { network, mode: consent ? t("scanning.modeFull") : t("scanning.modeListen") })}
        </p>
      </div>

      <section aria-labelledby="current-step" className={card}>
        {done ? (
          <Complete result={result} onShowResults={onShowResults} />
        ) : (
          <div className="border-b border-line pb-1.5">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-0.5">
              <h2 id="current-step" className="text-lg">
                {t("scanning.progressTitle")}
              </h2>
              <p className="text-sm font-semibold tabular-nums sm:text-base">
                {snapshot?.devices == null
                  ? t("scanning.devicesWaiting")
                  : level === "stopped"
                    ? t("scanning.devicesStale", { count: snapshot.devices })
                    : t("scanning.devices", { count: snapshot.devices })}
              </p>
            </div>
            {/* Tasks done, as a bar across the card: it moves only when a task finishes (no
                animation with reduced motion). */}
            <progress
              aria-labelledby="current-step"
              aria-valuetext={tasks}
              max={steps.length}
              value={snapshot ? finished : 0}
              className="scan-progress mt-1 mb-1"
            />
            <p id="current-task" className="font-semibold">
              {snapshot?.preparing ? t("scanning.preparing") : heading(steps, Boolean(snapshot), t)}
            </p>
            <p className="text-sm text-muted tabular-nums">
              {snapshot && <>{tasks} · </>}
              {elapsed > SCAN_MINUTES * 60
                ? t("scanning.overrun")
                : t("scanning.elapsed", { time: formatElapsed(elapsed), minutes: SCAN_MINUTES })}
            </p>
            {level === "fallback" && (
              <p className="mt-0.5 text-sm text-muted">
                {t("scanning.fallback")}{" "}
                <span className="tabular-nums">{t("scanning.lastUpdated", { count: Math.round(quietFor / 1000) })}</span>
              </p>
            )}
          </div>
        )}

        <ol aria-label={t("scanning.stepsLabel")} className="mt-1 divide-y divide-line">
          {steps.map((step) => (
            <TaskRow key={step.key} step={step} />
          ))}
        </ol>

        {level === "stopped" && (
          <div className="mt-2 rounded-inner border border-notice-line bg-notice p-2">
            <p className="flex items-center gap-1 font-semibold">
              <span className="text-sev-medium">
                <ProblemIcon />
              </span>
              {t("scanning.stopped")}
            </p>
            <p className="mt-0.5">{t("scanning.stoppedBody")}</p>
            {/* Not announced: it changes every second. */}
            <p className="text-sm text-muted tabular-nums">
              {t("scanning.lastReceived", { count: Math.round(quietFor / 1000) })}
            </p>
            <button type="button" onClick={live.retry} className={`mt-1 ${secondaryButton}`}>
              {t("scanning.retry")}
            </button>
          </div>
        )}
      </section>

      {/* Task changes and the two connection levels, read out only when they change. */}
      <p className="sr-only" aria-live="polite">
        {announcement}
      </p>
      <p className="sr-only" aria-live="polite">
        {level === "fallback"
          ? t("scanning.fallback")
          : level === "stopped"
            ? `${t("scanning.stopped")}. ${t("scanning.stoppedBody")}`
            : ""}
      </p>

      {!done && (
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
          <p className="text-muted">{t("scanning.stayConnected")}</p>
          <CancelCheck scanId={scanId} onCancelled={live.accept} />
        </div>
      )}
    </div>
  );
}

function joinList(items: string[], and: string): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")}${and}${items[items.length - 1]}`;
}

/** The heading from the real step states: one running task by name, several combined. */
function heading(steps: StepView[], started: boolean, t: TFunction): string {
  const active = steps.filter((s) => s.status === "active");
  if (active.length === 1) return t(`scanning.steps.${active[0]!.key}`);
  if (active.length > 1) {
    return t("scanning.combined", { list: joinList(active.map((s) => t(`scanning.short.${s.key}`)), t("scanning.and")) });
  }
  return started ? t("scanning.between") : t("scanning.starting");
}

const STATUS_STYLE: Record<StepStatus, string> = {
  done: "text-accent",
  active: "text-accent",
  failed: "text-sev-medium",
  skipped: "text-muted",
  upcoming: "text-muted",
};

function TaskRow({ step }: { step: StepView }) {
  const { t } = useTranslation();
  const { status } = step;
  const detail = status === "active" ? detailText(step, t) : null;
  return (
    <li className="flex flex-wrap items-start justify-between gap-x-2 py-1">
      <div className="min-w-0 flex-1">
        <p className={status === "upcoming" || status === "skipped" ? "text-muted" : "font-semibold"}>
          {t(`scanning.steps.${step.key}`)}
        </p>
        {detail && <p className="text-sm text-muted tabular-nums">{detail}</p>}
        {status === "skipped" && step.reason && (
          <p className="text-sm text-muted">{t(`scanning.reason.${step.reason}`)}</p>
        )}
      </div>
      {/* Always an icon and a word: the spinner is never the only signal. */}
      <span className={`flex items-center gap-0.5 text-sm font-semibold whitespace-nowrap ${STATUS_STYLE[status]}`}>
        {status === "failed" ? (
          <ProblemIcon />
        ) : (
          <StepIcon state={status === "active" ? "running" : status === "done" ? "done" : status === "skipped" ? "skipped" : "waiting"} />
        )}
        {t(`scanning.state.${status}`)}
      </span>
      {/* The plain message, across the whole row, so it reads easily on a phone too. */}
      {step.problems.length > 0 && (
        <div className="mt-0.5 w-full rounded-inner border border-notice-line bg-notice px-1.5 py-1 text-sm">
          <ul className="space-y-0.5">
            {step.problems.map((text) => (
              <li key={text}>{text}</li>
            ))}
          </ul>
          <p className="mt-0.5 text-muted">{t("scanning.carriesOn")}</p>
        </div>
      )}
    </li>
  );
}

/** Live counts for a running task, from real data only. The nearby task says it's scanning
 * until the Wi-Fi survey reports (about 25 s in), then how many networks it heard. */
function detailText(step: StepView, t: TFunction): string | null {
  const d = step.detail;
  if (step.key === "nearby" && !d) return t("scanning.detailNearbyScanning");
  if (!d) return null;
  if (d.devices !== undefined) return t("scanning.detailDevices", { count: d.devices });
  if (d.wifi !== undefined) {
    const bt = d.bluetooth !== undefined ? t("scanning.detailBluetooth", { count: d.bluetooth }) : "";
    return `${t("scanning.detailWifi", { count: d.wifi })}${bt}`;
  }
  if (d.bluetooth !== undefined) return t("scanning.detailBluetoothOnly", { count: d.bluetooth });
  return null;
}

function Complete({ result, onShowResults }: { result: DiscoveryResult | null; onShowResults: () => void }) {
  const { t } = useTranslation();
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    ref.current?.focus(); // keyboard and screen-reader users land on the news
  }, []);
  const summary = result ? summaryLine(result, t) : null;
  return (
    <div className="border-b border-line pb-2">
      <h2 id="current-step" ref={ref} tabIndex={-1} className="text-xl focus:outline-none">
        {t("scanning.complete")}
      </h2>
      <p className="mt-0.5" aria-live="polite">
        {summary ?? <span className="text-muted">{t("scanning.completeLoading")}</span>}
      </p>
      {result && (
        <button type="button" onClick={onShowResults} className={`mt-1.5 ${primaryButton}`}>
          {t("scanning.seeResults")}
        </button>
      )}
    </div>
  );
}

function summaryLine(result: DiscoveryResult, t: TFunction): string {
  const devices = t("scanning.summaryDevices", { count: result.devices.length });
  const high = result.summary?.high ?? 0;
  const medium = result.summary?.medium ?? 0;
  const findings =
    high + medium === 0 ? t("scanning.summaryNone") : t("scanning.summaryFindings", { high, medium, count: high + medium });
  return `${devices} · ${findings}`;
}

function CancelCheck({ scanId, onCancelled }: { scanId: string; onCancelled: (s: ScanSnapshot) => void }) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);

  async function confirm() {
    setBusy(true);
    setError(false);
    try {
      onCancelled(await cancelScan(scanId));
    } catch {
      setError(true);
      setBusy(false);
    }
  }

  return (
    <ConfirmButton
      label={t("scanning.cancel")}
      question={t("scanning.cancelConfirm")}
      yes={busy ? t("scanning.cancelling") : t("scanning.cancelYes")}
      no={t("scanning.cancelNo")}
      busy={busy}
      error={error ? t("scanning.cancelFailed") : null}
      onConfirm={() => void confirm()}
    />
  );
}

/** A clock for the elapsed time and "N seconds ago"; ticks once a second while running. */
function useNow(running: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, [running]);
  return now;
}

/** "Checking the router: Running", only when a task's status really changes, so polls and
 * heartbeats that repeat the same state aren't read out again. */
function useStepAnnouncement(steps: StepView[] | undefined): string {
  const { t } = useTranslation();
  const previous = useRef<Record<string, StepStatus> | null>(null);
  const [text, setText] = useState("");
  useEffect(() => {
    if (!steps) return;
    const before = previous.current;
    previous.current = Object.fromEntries(steps.map((s) => [s.key, s.status]));
    const said = steps
      .filter((s) => (before ? before[s.key] !== s.status : s.status === "active"))
      .map((s) => `${t(`scanning.steps.${s.key}`)}: ${t(`scanning.state.${s.status}`)}`);
    if (said.length) setText(said.join(". "));
  }, [steps, t]);
  return text;
}
