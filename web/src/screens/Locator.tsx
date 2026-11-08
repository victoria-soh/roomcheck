import { useEffect, useId, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Line, LineChart, ResponsiveContainer, XAxis, YAxis } from "recharts";

import { locateUrl } from "../api/client";
import type { LocatorMessage, LocatorReading, NearbyItem } from "../api/types";
import { ScreenHeading } from "../components/ScreenHeading";
import { card, primaryButton, secondaryButton } from "../components/styles";
import { Hint, Notice } from "../components/ui";

const WINDOW_MS = 30_000;

type Phase = "connecting" | "live" | "stopped" | "ended" | "error";

interface Point {
  at: number;
  level: number;
}

/** Screen 5, opened from "Find it". Only items flagged in the latest check can be located;
 * the backend refuses anything else. Readings live in this screen only and are gone when
 * you stop or leave: the WebSocket is closed and nothing is stored. */
export function Locator({ item, onBack }: { item: NearbyItem; onBack: () => void }) {
  const { t } = useTranslation();
  const [session, setSession] = useState(0);
  const [speak, setSpeak] = useState(false);
  const canSpeak = typeof window !== "undefined" && "speechSynthesis" in window;
  const speakHint = useId();

  return (
    <div className="space-y-3">
      <div className="space-y-1">
        <ScreenHeading>{t("locator.title", { label: item.label })}</ScreenHeading>
        <p className="text-lg text-muted">{t("locator.intro")}</p>
      </div>

      <LocatorSession key={session} item={item} speak={speak && canSpeak} onRestart={() => setSession((n) => n + 1)} onBack={onBack} />

      <div className={card}>
        <label className="flex cursor-pointer items-start gap-1.5">
          <input
            type="checkbox"
            checked={speak}
            aria-disabled={!canSpeak}
            aria-describedby={speakHint}
            onChange={(e) => canSpeak && setSpeak(e.target.checked)}
            className="mt-0.5 size-2.5 shrink-0 cursor-pointer accent-accent"
          />
          <span>
            <span className="block font-semibold">{t("locator.speak")}</span>
            <span id={speakHint} className="block text-sm text-muted">
              {canSpeak ? t("locator.speakHint") : t("locator.speakUnavailable")}
            </span>
          </span>
        </label>
      </div>
      <Hint>{t("locator.onlyFlagged")}</Hint>
    </div>
  );
}

function LocatorSession({
  item,
  speak,
  onRestart,
  onBack,
}: {
  item: NearbyItem;
  speak: boolean;
  onRestart: () => void;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const [phase, setPhase] = useState<Phase>("connecting");
  const [reading, setReading] = useState<LocatorReading | null>(null);
  const [points, setPoints] = useState<Point[]>([]);
  const [error, setError] = useState<string | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const stoppedRef = useRef(false);
  const speakRef = useRef(speak);
  const lastSpoken = useRef<string | null>(null);

  useEffect(() => {
    speakRef.current = speak;
    if (!speak && typeof window !== "undefined" && "speechSynthesis" in window) window.speechSynthesis.cancel();
  }, [speak]);

  useEffect(() => {
    const socket = new WebSocket(locateUrl(item.ref));
    socketRef.current = socket;
    socket.onmessage = (event: MessageEvent) => {
      let message: LocatorMessage;
      try {
        message = JSON.parse(String(event.data)) as LocatorMessage;
      } catch {
        return;
      }
      if ("error" in message) {
        setError(message.error);
        setPhase("error");
        return;
      }
      setPhase("live");
      setReading(message);
      const now = Date.now();
      if (message.level !== null) {
        const level = message.level;
        setPoints((old) => [...old.filter((p) => now - p.at <= WINDOW_MS), { at: now, level }]);
      }
      // The spoken cue: only when the word changes, never on every reading.
      const word = message.trend === "warmer" || message.trend === "colder" ? message.trend : null;
      if (word && word !== lastSpoken.current && speakRef.current) {
        window.speechSynthesis.cancel();
        window.speechSynthesis.speak(new SpeechSynthesisUtterance(t(`locator.trend.${word}`)));
      }
      lastSpoken.current = word ?? lastSpoken.current;
    };
    socket.onclose = () => {
      if (!stoppedRef.current) setPhase((p) => (p === "error" ? p : "ended"));
    };
    // Leaving the screen closes the connection; the backend stops reading at once.
    return () => {
      stoppedRef.current = true;
      socket.close();
      if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    };
  }, [item.ref, t]);

  function stop() {
    stoppedRef.current = true;
    socketRef.current?.close();
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    setPhase("stopped");
  }

  const running = phase === "connecting" || phase === "live";
  const level = reading?.level ?? null;
  const words = reading?.unstable || !reading?.heard ? null : reading?.trend ?? null;
  const headline =
    phase === "connecting"
      ? t("locator.connecting")
      : words
        ? t(`locator.trend.${words}`)
        : (reading?.message ?? t("locator.connecting"));

  return (
    <section
      aria-labelledby={phase === "error" ? undefined : "locator-now"}
      aria-label={phase === "error" ? t("locator.meterLabel") : undefined}
      className={card}
    >
      {phase === "error" && error ? (
        <Notice title={error} />
      ) : (
        <>
          {/* Announced when the words change; React leaves the text alone between readings. */}
          <p id="locator-now" className="text-2xl font-semibold" aria-live="polite">
            {running ? headline : phase === "stopped" ? t("locator.stopped") : t("locator.ended")}
          </p>
          {running && reading?.unstable && reading.message && <p className="mt-1">{reading.message}</p>}

          <div
            role="meter"
            aria-label={t("locator.meterLabel")}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={level === null ? 0 : Math.round(level * 100)}
            aria-valuetext={headline}
            className="mt-2"
          >
            {/* Drawn as SVG, so the width is an attribute, not an inline style. */}
            <svg viewBox="0 0 100 10" preserveAspectRatio="none" aria-hidden="true" className="h-4 w-full">
              <rect x="0" y="0" width="100" height="10" rx="5" className="fill-raised" />
              {level !== null && (
                <rect
                  x="0"
                  y="0"
                  width={Math.max(4, level * 100)}
                  height="10"
                  rx="5"
                  className={reading?.unstable ? "fill-line-strong" : "fill-accent"}
                />
              )}
            </svg>
            <div aria-hidden="true" className="mt-0.5 flex justify-between text-sm text-muted">
              <span>{t("locator.weaker")}</span>
              <span>{t("locator.stronger")}</span>
            </div>
          </div>

          {reading?.note && (
            <div className="mt-1">
              <Hint>{reading.note}</Hint>
            </div>
          )}

          <SignalChart points={points} />
        </>
      )}

      <div className="mt-2 flex flex-wrap gap-1">
        {running ? (
          <button type="button" onClick={stop} className={primaryButton}>
            {t("locator.stop")}
          </button>
        ) : (
          <button type="button" onClick={onRestart} className={primaryButton}>
            {t("locator.startAgain")}
          </button>
        )}
        <button type="button" onClick={onBack} className={secondaryButton}>
          {t("locator.back")}
        </button>
      </div>
    </section>
  );
}

/** The last 30 s of signal. The line is decorative; the sentence under it says the same. */
function SignalChart({ points }: { points: Point[] }) {
  const { t } = useTranslation();
  const last = points[points.length - 1];
  const data = last ? points.map((p) => ({ x: (p.at - last.at) / 1000, y: p.level })) : [];
  const first = points[0];
  const change = first && last ? last.level - first.level : 0;
  const summary =
    points.length < 3
      ? t("locator.chartEmpty")
      : change > 0.04
        ? t("locator.chartRising")
        : change < -0.04
          ? t("locator.chartFalling")
          : t("locator.chartSteady");
  return (
    <figure className="mt-2">
      <figcaption className="text-sm font-semibold">{t("locator.chartTitle")}</figcaption>
      <div aria-hidden="true" className="mt-1 h-20 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 8 }} accessibilityLayer={false}>
            <XAxis dataKey="x" type="number" domain={[-30, 0]} tick={false} stroke="#d7ece9" height={1} />
            <YAxis domain={[0, 1]} hide />
            <Line type="monotone" dataKey="y" stroke="#1b6f68" strokeWidth={3} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div aria-hidden="true" className="mt-0.5 flex justify-between text-sm text-muted">
        <span>{t("locator.axisPast")}</span>
        <span>{t("locator.axisNow")}</span>
      </div>
      <p className="mt-0.5 text-sm text-muted">{summary}</p>
    </figure>
  );
}
