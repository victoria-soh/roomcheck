// The demo data for the component and browser tests and the screenshots. The checks, the
// comparison and the handover data are made by RoomCheck's own pipeline from made-up raw scan
// inputs (app/demo_data.py writes ./demo/*.json; tests/unit/test_demo_data.py checks each
// file is exactly the pipeline's output). Addresses are documentation ones (192.0.2.x,
// 00:00:5E:00:53:xx), the network is "Example-Home", makers and the CVE are made up.
import compareJson from "./demo/compare.json" with { type: "json" };
import handoverJson from "./demo/handover.json" with { type: "json" };
import handoverListeningJson from "./demo/handover_listening.json" with { type: "json" };
import handoverQuietFullJson from "./demo/handover_quiet_full.json" with { type: "json" };
import handoverMineJson from "./demo/handover_mine.json" with { type: "json" };
import resultAiOffJson from "./demo/result_ai_off.json" with { type: "json" };
import resultFullJson from "./demo/result_full.json" with { type: "json" };
import resultListeningJson from "./demo/result_listening.json" with { type: "json" };
import resultQuietFullJson from "./demo/result_quiet_full.json" with { type: "json" };
import type {
  BaselineInfo,
  CompareResponse,
  DiscoveryResult,
  HandoverState,
  ReportResponse,
  ScanSnapshot,
  Setup,
  StepView,
  Task,
} from "../api/types";

/** A short stay checked with permission: the pipeline's result, with the made-up AI layer. */
export const RESULT = resultFullJson as unknown as DiscoveryResult;
export const CANT_SEE = RESULT.summary!.cant_see;
/** The same check with AI explanations off (no API key): the standard wording everywhere. */
export const RESULT_AI_OFF = resultAiOffJson as unknown as DiscoveryResult;
/** Listening only, nothing flagged: what it heard, and the checks it skipped. */
export const NOTHING_FOUND = resultListeningJson as unknown as DiscoveryResult;
/** With permission, nothing flagged, every check ran. */
export const NOTHING_FOUND_COMPLETE = resultQuietFullJson as unknown as DiscoveryResult;

const byRule = (rule: string) => RESULT.findings.find((f) => f.rule_id === rule)!;
/** The camera's subject: what its answers, name and task attach to. */
export const CAM_SUBJECT = byRule("R-CAM").subject!;
export const CAM_FINDING = byRule("R-CAM");
export const WPS_FINDING = byRule("R-WPS");
export const TRACKER_FINDING = byRule("R-TRACKER");

const T0 = "2026-11-03T05:23:39Z";

type Status = StepView["status"];

/** The five tasks of a listening-only check: "services" is skipped from the start. */
function steps(
  listen: Status,
  router: Status,
  nearby: Status,
  explain: Status,
  problems: Partial<Record<StepView["key"], string[]>> = {},
  detail: Partial<Record<StepView["key"], Record<string, number>>> = {},
): StepView[] {
  return [
    { key: "listen", status: listen, problems: problems.listen ?? [], detail: detail.listen ?? null },
    { key: "nearby", status: nearby, problems: problems.nearby ?? [], detail: detail.nearby ?? null },
    { key: "services", status: "skipped", problems: [], reason: "needs_permission" },
    { key: "router", status: router, problems: problems.router ?? [], detail: detail.router ?? null },
    { key: "explain", status: explain, problems: problems.explain ?? [], detail: detail.explain ?? null },
  ];
}

export function snapshot(over: Partial<ScanSnapshot> = {}): ScanSnapshot {
  return {
    id: "job1",
    state: "running",
    steps: steps("active", "upcoming", "active", "upcoming"),
    current_step: "listen",
    current_index: 1,
    total_steps: 4,
    done_steps: 0,
    devices: null,
    started_at: T0,
    elapsed_seconds: 3,
    last_update_at: T0,
    version: 1,
    result: null,
    error: null,
    ...over,
  };
}

export const BLUETOOTH_OFF = "Turn on Bluetooth to check for nearby trackers.";
/** The known-issues lookup's note (app/discovery/messages.py). It runs only in a full check, so
 * it sits under the services step, never in the listening-only fixtures below. */
export const NVD_SKIPPED = "Not checked: the vulnerability database didn't answer this time.";

/** The start of a check: listening and looking at nearby Wi-Fi at the same time. */
export const STARTING = snapshot();
/** Still listening, with live counts from real data. */
export const LISTENING = snapshot({
  steps: steps("active", "upcoming", "active", "upcoming", {}, { listen: { devices: 3 }, nearby: { wifi: 12 } }),
  devices: 3,
  elapsed_seconds: 42,
  version: 4,
});
/** Mid-check: discovery done with 4 devices, the router being checked, one failure each. */
export const MIDWAY = snapshot({
  steps: steps("done", "active", "failed", "upcoming", { nearby: [BLUETOOTH_OFF] }),
  current_step: "router",
  current_index: 4,
  done_steps: 2,
  devices: 4,
  elapsed_seconds: 64,
  version: 9,
});
/** Past the two-minute estimate. */
export const SLOW = { ...MIDWAY, elapsed_seconds: 150, version: 10 };
export const FINISHED = snapshot({
  state: "done",
  steps: steps("done", "done", "failed", "done", { nearby: [BLUETOOTH_OFF] }),
  current_step: null,
  current_index: null,
  done_steps: 4,
  devices: 4,
  elapsed_seconds: 70,
  version: 12,
});
export const DONE_WITH_RESULT = (result: DiscoveryResult): ScanSnapshot => ({ ...FINISHED, result });
export const CANCELLED = snapshot({
  state: "cancelled",
  current_step: null,
  current_index: null,
  error: "You cancelled this check. Nothing from it was kept.",
  version: 10,
});

/** A whole check as the WebSocket sends it: start, midway, then the final state. */
export const LIVE = [STARTING, MIDWAY, FINISHED];

/** Locator readings as the backend sends them: getting steadier and warmer. */
export const READINGS = [-78, -76, -75, -72, -70, -68, -66, -64, -61, -60].map((dbm, i) => ({
  ref: "bluetooth:def",
  heard: true,
  raw_dbm: dbm,
  smoothed_dbm: dbm,
  level: Math.round(((dbm + 100) / 70) * 1000) / 1000,
  trend: i < 3 ? null : ("warmer" as const),
  unstable: false,
  message: i < 3 ? "Getting a steady reading. Hold the laptop the same way throughout." : null,
  note: null,
}));

export const VERIFIED = {
  sha256: "3f7a9c1e5b2d8f4a6c0e9b7d1f3a5c7e9b1d3f5a7c9e1b3d5f7a9c1e3b5d7f9a",
  hash_file: "missing" as const,
  token: "valid" as const,
  timestamped_at: "2026-11-03T05:25:12Z",
  pinned_authority: true,
  outcome: "verified" as const,
  reason: null,
  ok: true,
  message:
    "This PDF matches its timestamp: it existed, unchanged, on 03 Nov 2026, 05:25:12 UTC, as signed by FreeTSA.",
};

export const TAMPERED = {
  ...VERIFIED,
  sha256: "9b1d3f5a7c9e1b3d5f7a9c1e3b5d7f9a3f7a9c1e5b2d8f4a6c0e9b7d1f3a5c7e",
  token: "mismatch" as const,
  timestamped_at: null,
  outcome: "mismatch" as const,
  ok: false,
  message: "This PDF doesn't match its timestamp. It has changed since it was timestamped, or the files don't belong together.",
};

/** A report that wasn't timestamped: explained, never called altered. */
export const NOT_TIMESTAMPED = {
  ...VERIFIED,
  token: "missing" as const,
  timestamped_at: null,
  pinned_authority: null,
  outcome: "not_timestamped" as const,
  ok: false,
  message: "This report wasn't timestamped, so it can't be timestamp-verified.",
};
/** A timestamp that can't be trusted here. */
export const COULDNT_VERIFY = {
  ...VERIFIED,
  pinned_authority: false,
  outcome: "couldnt_verify" as const,
  reason: "The timestamp wasn't signed by the timestamp service RoomCheck uses, so it can't be trusted here.",
  ok: false,
};

export const REPORT: ReportResponse = {
  pdf: "roomcheck-report-20261103-132509.pdf",
  sha256_file: "roomcheck-report-20261103-132509.sha256",
  tsr: "roomcheck-report-20261103-132509.tsr",
  bundle: "roomcheck-report-20261103-132509.zip",
  sha256: VERIFIED.sha256,
  timestamped_at: "2026-11-03T05:25:12Z",
  timestamp_message: null,
  explanations: RESULT.explanations ?? { items: [], ai_status: "none" },
  ai: { state: "added", reason: null }, // AI explanations are on in the demo (SETUP_READY)
  timestamp: { state: "added", reason: null },
};
/** The report made with AI explanations off (RESULT_AI_OFF, SETUP_NO_AI). */
export const REPORT_AI_OFF: ReportResponse = {
  ...REPORT,
  explanations: RESULT_AI_OFF.explanations!,
  ai: { state: "not_requested", reason: null },
};

// --- Layer 6: handover data from a real (temporary) handover session ----------------------------

export const HANDOVER = handoverJson as unknown as HandoverState;
const CAMERA_TASK: Task = HANDOVER.tasks.find((t) => t.rule_id === "R-CAM")!;
const WPS_TASK: Task = HANDOVER.tasks.find((t) => t.rule_id === "R-WPS")!;
export { CAMERA_TASK, WPS_TASK };
/** The same, after saying the camera is yours: next step changed, no camera task. */
export const HANDOVER_CAMERA_MINE = handoverMineJson as unknown as HandoverState;
/** Each nothing-found check's own handover data (the pipeline's, nothing answered yet). */
export const HANDOVER_LISTENING = handoverListeningJson as unknown as HandoverState;
export const HANDOVER_QUIET_FULL = handoverQuietFullJson as unknown as HandoverState;

/** The handover data that belongs to a demo check, so "Handover · N" matches its findings. */
export function handoverFor(result: DiscoveryResult): HandoverState {
  if (result === NOTHING_FOUND) return HANDOVER_LISTENING;
  if (result === NOTHING_FOUND_COMPLETE) return HANDOVER_QUIET_FULL;
  return HANDOVER;
}

export const BASELINE_NONE: BaselineInfo = { state: "none", saved_at: null, devices: 0, nearby: 0, message: null };
export const BASELINE_SAVED: BaselineInfo = {
  state: "saved",
  saved_at: "2026-11-03T05:30:00Z",
  devices: 6,
  nearby: 1,
  message: null,
};
export const BASELINE_UNREADABLE: BaselineInfo = {
  state: "unreadable",
  saved_at: null,
  devices: 0,
  nearby: 0,
  message: "This saved scan belongs to another account or install. Start a new move-in scan.",
};

export const COMPARE_READY = compareJson as unknown as CompareResponse;
export const COMPARE_NONE: CompareResponse = { state: "none", baseline: BASELINE_NONE, comparison: null };

// The Start screen's readiness strip. "Example-Home" is a made-up network name.
export const NETWORK_NAME = "Example-Home";
const ALL_ITEMS = (["wifi", "bluetooth", "location", "npcap", "nmap"] as const).map((name) => ({ name, ready: true }));
export const SETUP_READY: Setup = {
  network: { kind: "wifi", name: NETWORK_NAME },
  items: ALL_ITEMS,
  all_ready: true,
  outside: { ai: true, known_issues: true, timestamp: "freetsa.org" }, // AI on: the demo's story
};
export const SETUP_MISSING: Setup = {
  ...SETUP_READY,
  items: ALL_ITEMS.map((i) => (i.name === "bluetooth" || i.name === "nmap" ? { ...i, ready: false } : i)),
  all_ready: false,
};
export const SETUP_OFFLINE: Setup = { ...SETUP_READY, network: { kind: "none", name: null } };
export const SETUP_CABLE: Setup = { ...SETUP_READY, network: { kind: "cable", name: null } };
export const SETUP_WITH_AI: Setup = SETUP_READY;
/** No API key: AI explanations off (the template-wording state). */
export const SETUP_NO_AI: Setup = { ...SETUP_READY, outside: { ...SETUP_READY.outside, ai: false } };
export const SETUP_NO_CALLS: Setup = {
  ...SETUP_READY,
  outside: { ai: false, known_issues: false, timestamp: null },
};
