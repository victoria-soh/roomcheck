// How long a check takes, for the Start and Scanning screens. The last consented check with the
// nearby check alongside took 93 s end to end on 3 Nov (60 s of listening, the router checks,
// explanations and a PDF), so "about 2 minutes".
export const SCAN_MINUTES = 2;

// The backend sends a snapshot at least every 5 s (app/main.py SCAN_HEARTBEAT_SECONDS). Three
// missed heartbeats mean the live connection is gone even if the socket hasn't said so.
export const STALE_AFTER_MS = 15_000;
// No successful update at all (WebSocket or polling) for this long: updates have stopped.
export const STOPPED_AFTER_MS = 20_000;
export const POLL_MS = 2_000;
export const RECONNECT_MS = [1_000, 2_000, 4_000, 8_000];
