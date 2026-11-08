// The parts of the backend's JSON the dashboard uses. Mirrors the Pydantic models in
// app/discovery/models.py, app/rules/models.py, app/explain/models.py and app/jobs.py.

export type Severity = "High" | "Medium" | "Low" | "Info";
export type Band = "Likely" | "Possible" | "Unclear";
export type Scope = "device" | "network" | "nearby";
export type SummaryStatus =
  | "Needs attention"
  | "Check these items"
  | "Not detected by these checks";

/** The renter's questions Results and the report are organised by (rules.yaml, questions). */
export type Question = "watching" | "control" | "wifi";

export interface Finding {
  id: string;
  rule_id: string;
  scope: Scope;
  // Where it's shown: Results (your devices and your own network, including its router or
  // access point) or Nearby (other signals). Older data: Nearby for scope "nearby".
  shown_on?: "results" | "nearby";
  question?: Question; // the renter's question it answers (rules.yaml); older data: by rule
  severity: Severity;
  confidence_band: Band;
  device_ref: string | null;
  title: string;
  observed?: string; // one fixed sentence from rules.yaml saying what was seen (never AI text)
  clues?: string[]; // the specific clues, one fixed plain sentence each (never AI text)
  lead_clue?: string; // the plainest of them, for the summary sentence
  asks_location?: boolean; // camera findings ask "Where is it?"
  draft?: Draft; // the message its next step calls for: to the host, or to the platform
  could_mean?: string; // one fixed sentence from rules.yaml: what it could mean, the risk (never AI text)
  evidence: string[];
  next_step: string;
  guidance: string[];
  nearby_ref: string | null;
  standard_explanation: string;
  standard_why: string;
  subject?: string | null; // what recognition answers and handover tasks attach to
}

export interface Fingerprint {
  type: string;
  label: string;
  band: Band;
  confidence?: number;
  other_types?: { type: string; score: number }[]; // other types with any evidence
  weak_types?: { type: string; score: number }[];
}

export interface Device {
  id: string;
  ip: string | null;
  vendor: string | null;
  hostnames: string[];
  is_gateway: boolean;
  fingerprint: Fingerprint | null;
  mac_is_random?: boolean;
  notes?: string[]; // plain notes from discovery, e.g. "Private address, probably a phone or laptop."
}

export interface CheckStatus {
  name: string;
  label: string;
  status: "ran" | "skipped" | "failed";
  reason: string | null;
  found: number;
  short_reason?: string | null; // a few words on why it didn't run (app/coverage.py)
}

export interface RoomSummary {
  status: SummaryStatus;
  high: number;
  medium: number;
  other: number;
  not_checked: string[];
  cant_see: string[];
}

export interface NearbyItem {
  ref: string; // salted, for the locator; never an address
  kind: "wifi" | "bluetooth";
  label: string;
  ssid: string | null;
  maker: string | null;
  security?: string | null;
  band?: string | null;
  signal_dbm?: number;
  rule_ids?: string[];
  connected?: boolean;
}

/** Counts of what was heard and then discarded (app/wireless/models.py HeardCounts). */
export interface HeardCounts {
  wifi_access_points: number;
  bluetooth_devices: number;
  bluetooth_by_category: Record<string, number>;
}

export interface Explanation {
  finding_id: string;
  explanation: string;
  why_it_matters: string;
  source: "ai" | "standard";
}

export interface LandlordMessage {
  text: string;
  source: "ai" | "standard";
  label: string;
  note: string;
}

export interface Explanations {
  items: Explanation[];
  ai_status: string;
  landlord_message?: LandlordMessage | null; // none when there's nothing to ask about
}

export interface DiscoveryResult {
  started_at: string;
  finished_at: string;
  mode: "full" | "passive";
  stay_type?: StayType | null; // where the user is staying, chosen on Start
  devices: Device[];
  checks: CheckStatus[];
  messages: string[];
  findings: Finding[];
  summary: RoomSummary | null;
  nearby_items: NearbyItem[];
  nearby_heard?: HeardCounts | null; // null when the nearby check didn't run
  room_network?: string | null;
  network?: { cidr: string } | null; // null: not connected to a network
  explanations: Explanations | null;
  coverage?: CoverageItem[]; // what each part of the check managed to do (app/coverage.py)
}

export type CoverageState = "completed" | "limited" | "not_run";

export interface CoverageItem {
  area: string;
  label: string;
  state: CoverageState;
  reason: string | null; // plain words, without the "Limited:" / "Not run:" prefix
  reason_code?: string | null; // the message code behind it, e.g. "location_off"
}

/** One locator reading (app/wireless/locator.py LocatorReading), or an error message. */
export interface LocatorReading {
  ref: string;
  heard: boolean;
  raw_dbm: number | null;
  smoothed_dbm: number | null;
  level: number | null; // 0..1, for the bar
  trend: "warmer" | "colder" | "same" | null; // null while starting, lost or unstable
  unstable: boolean;
  message: string | null;
  note: string | null;
}

export type LocatorMessage = LocatorReading | { error: string };

export interface ReportResponse {
  pdf: string;
  sha256_file: string;
  tsr: string | null;
  bundle: string; // a ZIP of the PDF, the .sha256 and the .tsr (if there is one)
  sha256: string;
  timestamped_at: string | null;
  timestamp_message: string | null; // why there's no trusted timestamp
  explanations: Explanations;
  ai: ServiceOutcome;
  timestamp: ServiceOutcome;
}

/** What really happened with one optional service after the report was made. */
export interface ServiceOutcome {
  state: "added" | "unavailable" | "not_requested";
  reason: string | null;
}

export interface VerifyResult {
  sha256: string;
  hash_file: "match" | "mismatch" | "missing";
  token: "valid" | "mismatch" | "invalid" | "missing";
  timestamped_at: string | null;
  pinned_authority: boolean | null;
  outcome: "verified" | "mismatch" | "couldnt_verify" | "not_timestamped";
  reason: string | null; // couldnt_verify: the specific reason
  ok: boolean;
  message: string;
}

export type StepKey = "listen" | "services" | "router" | "nearby" | "explain";
export type SkipReason = "needs_permission" | "no_network" | "not_chosen";
// failed: the step finished, but something in it didn't work (its problems say what).
export type StepStatus = "upcoming" | "active" | "done" | "failed" | "skipped";
export type ScanState = "running" | "done" | "failed" | "cancelled";

export interface StepView {
  key: StepKey;
  status: StepStatus;
  problems: string[];
  reason?: SkipReason | null; // why it was skipped
  detail?: Record<string, number> | null; // live counts while it runs: {devices} or {wifi, bluetooth}
}

/** The live state of a check (app/jobs.py ScanSnapshot): sent over the WebSocket, and
 * returned by GET /api/scans/{id}, which also carries the result once it's done. */
export interface ScanSnapshot {
  id: string;
  state: ScanState;
  steps: StepView[];
  current_step: StepKey | null;
  current_index: number | null;
  total_steps: number; // tasks this check does (skipped ones don't count)
  done_steps: number;
  devices: number | null; // null until discovery has reported a count
  started_at: string;
  elapsed_seconds: number;
  last_update_at: string;
  version: number;
  result: DiscoveryResult | null;
  error: string | null;
  /** Cancelled, but still finishing (its last tasks, or the scanner restarting). */
  stopping?: boolean;
  /** Waiting for the previous check's scanner work to end before starting. */
  preparing?: boolean;
}

export type ScanMessage = ({ type: "state" } & ScanSnapshot) | { type: "failed"; text: string };

export interface ScanStarted {
  id: string;
}

// --- Layer 6 ----------------------------------------------------------------------------------

export type Answer = "mine" | "landlord" | "unknown";
// Workflow status only; "Host confirmed" and "Observed by RoomCheck" are evidence.
export type TaskStatus = "todo" | "asked" | "resolved";
export type Who = "landlord_or_host" | "booking_platform" | "you";

export type RecheckOffer = "available" | "needs_status" | "unobservable" | "none";

export interface Recheck {
  outcome: "fixed" | "gone" | "still_there" | "couldnt_check" | "needs_permission";
  text: string; // fixed words from app/handover/recheck.py
  checked_at: string;
}

export interface Task {
  id: string;
  finding_id: string;
  rule_id: string;
  subject: string;
  severity: Severity;
  finding_title: string;
  title: string;
  ask: string;
  who: Who;
  steps: string[];
  support: { name: string; url: string } | null;
  status: TaskStatus;
  notes: string;
  changed_at: string | null;
  check_at?: string | null; // when the check this task came from started
  optional?: { text: string; reason: string }[]; // not required by the finding; never in the message
  // Evidence, shown alongside the status.
  host_confirmed?: boolean; // the user recorded the host's answer
  host_confirmed_at?: string | null;
  recheck_offer?: RecheckOffer; // a recheck once Resolved or Host confirmed, where RoomCheck can see the fix
  rechecks?: Recheck[]; // every recheck, oldest first
  recheck?: Recheck | null; // the latest one
  observed?: boolean; // "Observed by RoomCheck": the latest recheck saw the fix
  observed_at?: string | null;
}

export interface HandoverState {
  answers: Record<string, Answer>;
  confirmed?: Record<string, boolean>; // "Host's" only: has the host confirmed it?
  names?: Record<string, string>; // the user's own short device names (plain text)
  notes?: Record<string, string>; // their short notes from "Help identify this" (plain text)
  adjusted: Record<string, { next_step: string; guidance: string[]; draft?: Draft }>; // by finding id
  locations?: Record<string, CameraLocation>; // a camera's "Where is it?", by subject
  tasks: Task[];
  message: LandlordMessage | null;
  saved: boolean; // a move-in scan is saved
  storage?: "saved" | "not_saved"; // whether the handover data is saved on this laptop
  storage_reason?: string | null; // "not_saved": why
  physical?: PhysicalCheck; // the guided physical check
}

/** The places in the guided physical check (app/handover/models.py PHYSICAL_ITEMS). */
export const PHYSICAL_ITEMS = [
  "smoke_detector",
  "chargers",
  "clocks",
  "tv_box",
  "purifier_speaker",
  "facing_bed",
  "mirrors",
  "lenses",
] as const;
export type PhysicalItemId = (typeof PHYSICAL_ITEMS)[number];

export interface PhysicalCheck {
  items: Partial<Record<PhysicalItemId, { looked: boolean; note: string }>>;
  done_at: string | null; // when the user pressed Done
}

/** A camera's answer to "Where is it?". */
export type CameraLocation = "inside" | "outside" | "unknown";
/** The message a next step calls for: to the host, or a report to the platform. */
export type Draft = "host" | "platform";

/** Where the user is staying (Start); it changes some next steps (rules.yaml). */
export type StayType = "short_stay" | "rental" | "hostel" | "other";

export interface BaselineInfo {
  state: "none" | "saved" | "unreadable";
  saved_at: string | null;
  devices: number;
  nearby: number;
  message: string | null;
}

export interface BaselineFinding {
  rule_id: string;
  severity: Severity;
  title: string;
}

export type MatchDecision = "same" | "different";

export interface CompareItem {
  kind: "device" | "nearby" | "network";
  status: "new" | "gone" | "changed" | "unchanged"; // unchanged: only "possibly the same" pairs
  match: "exact" | "possible" | null;
  label: string;
  maker: string | null;
  changes: string[];
  findings: BaselineFinding[];
  device_ref: string | null;
  subject?: string | null; // what names and answers attach to
  match_id?: string | null; // a "possibly the same device" pair
  decision?: MatchDecision | null; // the user's answer to it
  band?: Band | null; // the type guess's band: the higher of the two when only that varied
  identification_varied?: boolean; // same type and clues, only Likely / Possible moved
}

export interface Comparison {
  baseline_saved_at: string;
  scan_at: string;
  baseline_mode?: "full" | "passive" | null;
  scan_mode?: "full" | "passive" | null;
  new: CompareItem[];
  gone: CompareItem[];
  changed: CompareItem[];
  unchanged: number;
  unchanged_possible: number; // of those, not answered yet
  possible?: CompareItem[]; // unchanged "possibly the same device" pairs, to answer
  varied?: CompareItem[]; // unchanged devices whose identification varied between checks
  not_compared: number;
  ran_differently?: boolean; // one check had permission, the other only listened
  warnings?: string[]; // parts of this check that were limited or didn't run
  not_checked?: string[]; // found at move-in, but this check couldn't look for them
}

export interface CompareResponse {
  state: "none" | "unreadable" | "no_check" | "ready";
  baseline: BaselineInfo;
  comparison: Comparison | null;
}

// --- the Start screen's readiness strip (app/setup_check.py) -----------------------------------

export type SetupName = "wifi" | "bluetooth" | "location" | "npcap" | "nmap";

export interface Setup {
  network: { kind: "wifi" | "cable" | "none"; name: string | null }; // shown on this laptop only
  items: { name: SetupName; ready: boolean }[];
  all_ready: boolean;
  outside: { ai: boolean; known_issues: boolean; timestamp: string | null };
}
