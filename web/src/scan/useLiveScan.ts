// Follows one check's live state. The WebSocket is the main source; while it's down, the
// page polls GET /api/scans/{id}, which returns the same snapshot, so progress never resets.
import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { followScan, getScan, type EventStream } from "../api/client";
import type { ScanMessage, ScanSnapshot } from "../api/types";
import { POLL_MS, RECONNECT_MS, STALE_AFTER_MS } from "./timing";

export interface LiveScan {
  snapshot: ScanSnapshot | null;
  /** When the newest snapshot arrived (ms since 1970), from either source. */
  receivedAt: number | null;
  /** The live connection is down (closed early, or silent for three heartbeats). */
  interrupted: boolean;
  /** While interrupted: polling has just confirmed the check is still running. */
  confirmedRunning: boolean;
  /** When the last successful poll answered (ms since 1970), or null. */
  polledAt: number | null;
  /** A message from the backend, if the check can't be followed at all. */
  failure: string | null;
  retry: () => void;
  /** Use a snapshot from elsewhere (the cancel response). */
  accept: (snapshot: ScanSnapshot) => void;
}

const CONFIRM_FRESH_MS = 3 * POLL_MS;

interface Received {
  snapshot: ScanSnapshot;
  at: number;
}

/** The newer of two snapshots. Heartbeats repeat a version; an older one (a slow poll) loses. */
function newer(a: Received | null, b: Received | null): Received | null {
  if (!a) return b;
  if (!b) return a;
  if (a.snapshot.version !== b.snapshot.version) return a.snapshot.version > b.snapshot.version ? a : b;
  return a.at >= b.at ? a : b;
}

/** Running, or cancelled but still stopping: either way, more updates are coming. */
function stillGoing(snapshot: ScanSnapshot | undefined): boolean {
  return !snapshot || snapshot.state === "running" || Boolean(snapshot.stopping);
}

export function useLiveScan(scanId: string, now: () => number = Date.now): LiveScan {
  const [pushed, setPushed] = useState<Received | null>(null); // WebSocket or cancel reply
  const [interrupted, setInterrupted] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0); // bump to reconnect now
  const backoff = useRef(0);

  const accept = useCallback(
    (snapshot: ScanSnapshot) => setPushed((cur) => newer(cur, { snapshot, at: now() })),
    [now],
  );

  // Polling while the live connection is interrupted.
  const poll = useQuery({
    queryKey: ["scan", scanId, "poll"],
    queryFn: () => getScan(scanId),
    enabled: interrupted,
    refetchInterval: (q) => (interrupted && stillGoing(q.state.data) ? POLL_MS : false),
    retry: false,
  });
  const polled: Received | null = poll.data ? { snapshot: poll.data, at: poll.dataUpdatedAt } : null;
  const known = newer(pushed, polled);
  // Once the check is done, one request for the full result (the WebSocket doesn't carry it).
  const done = known?.snapshot.state === "done";
  const final = useQuery({
    queryKey: ["scan", scanId, "result"],
    queryFn: () => getScan(scanId),
    enabled: done && !known?.snapshot.result,
    retry: 2,
  });
  const latest = newer(known, final.data ? { snapshot: final.data, at: final.dataUpdatedAt } : null);
  // A cancelled check that's still stopping is followed until it has stopped.
  const ended = latest !== null && !stillGoing(latest.snapshot);

  useEffect(() => {
    if (ended || failure) return;
    let stream: EventStream | null = null;
    let watchdog: ReturnType<typeof setTimeout> | undefined;
    let reconnect: ReturnType<typeof setTimeout> | undefined;

    const lost = () => {
      setInterrupted(true);
      stream?.close();
      const wait = RECONNECT_MS[Math.min(backoff.current, RECONNECT_MS.length - 1)] ?? 8_000;
      backoff.current += 1;
      reconnect = setTimeout(() => setAttempt((n) => n + 1), wait);
    };
    const resetWatchdog = () => {
      clearTimeout(watchdog);
      watchdog = setTimeout(lost, STALE_AFTER_MS);
    };

    stream = followScan(
      scanId,
      (message: ScanMessage) => {
        if (message.type === "failed") {
          setFailure(message.text);
          return;
        }
        backoff.current = 0;
        setInterrupted(false);
        accept(message);
        if (message.state === "running") resetWatchdog();
        else clearTimeout(watchdog);
      },
      (finished) => {
        clearTimeout(watchdog);
        if (!finished) lost();
      },
    );
    resetWatchdog();
    return () => {
      clearTimeout(watchdog);
      clearTimeout(reconnect);
      stream?.close();
    };
  }, [scanId, attempt, accept, ended, failure]);

  const confirmedRunning =
    interrupted &&
    !poll.isError &&
    poll.data?.state === "running" &&
    now() - poll.dataUpdatedAt < CONFIRM_FRESH_MS;

  const retry = useCallback(() => {
    backoff.current = 0;
    setAttempt((n) => n + 1);
  }, []);

  return {
    snapshot: latest?.snapshot ?? null,
    receivedAt: latest?.at ?? null,
    interrupted: interrupted && !ended,
    confirmedRunning,
    polledAt: poll.isSuccess ? poll.dataUpdatedAt : null,
    failure,
    retry,
    accept,
  };
}
