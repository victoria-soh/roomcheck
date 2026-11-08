// The Results screen's logic, kept pure so it can be tested on its own: the summary headline
// and description from fixed templates, the counts, and coverage. Cards are grouped by the
// renter's questions (questions.ts). Nothing here uses AI text: the description comes from each
// rule's fixed "observed" sentence.
import type { TFunction } from "i18next";

import type { CheckStatus, CoverageItem, Device, DiscoveryResult, Finding, NearbyItem, Severity } from "../api/types";
import { NEARBY_CHECKS, NETWORK_CHECKS } from "../components/links";
import en from "../strings/en.json";
import { questionViews, shortPhrase, thingsToLookAt, type CardKind, type QuestionCard, type QuestionView } from "./questions";

export { shortPhrase };

export const SEVERITIES: Severity[] = ["High", "Medium", "Low", "Info"];
const RANK: Record<Severity, number> = { High: 0, Medium: 1, Low: 2, Info: 3 };
const BAND_RANK = { Likely: 0, Possible: 1, Unclear: 2 } as const;
export const CAMERA_RULES = new Set(["R-CAM", "R-NEW-CAMERA"]);

/** Most serious first; within a priority, the surer finding first. */
export function byPriority(a: Finding, b: Finding): number {
  return RANK[a.severity] - RANK[b.severity] || BAND_RANK[a.confidence_band] - BAND_RANK[b.confidence_band];
}

/** Your devices and your own network, rather than other nearby signals. Nearby lists the
 * others with the locator; Results shows every finding under its question. */
export function onResults(f: Finding): boolean {
  return (f.shown_on ?? (f.scope === "nearby" ? "nearby" : "results")) === "results";
}

/** One card: a device, a nearby signal or one network finding, under one question. */
export interface Group {
  key: string; // also the card's element id
  kind: CardKind;
  device?: Device;
  nearby?: NearbyItem;
  findings: Finding[]; // High, Medium or Low, most serious first
  also: Finding[]; // Info: shown as "Also found", not counted
}

export function groupId(key: string): string {
  return `card-${key.replace(/[^A-Za-z0-9_-]/g, "-")}`;
}

/** A question's card with the device or nearby item it's about. */
export function asGroup(card: QuestionCard, result: DiscoveryResult): Group {
  return {
    key: card.key,
    kind: card.kind,
    device: card.deviceRef ? result.devices.find((d) => d.id === card.deviceRef) : undefined,
    nearby: card.nearbyRef ? result.nearby_items.find((i) => i.ref === card.nearbyRef) : undefined,
    findings: card.findings,
    also: card.also,
  };
}

/** A card the summary can open: its element id and the finding that names it. */
export interface ReviewTarget {
  kind: "here";
  id: string;
  group: CardKind;
  finding: Finding;
}

export interface Headline {
  title: string;
  body: string;
  target: ReviewTarget | null; // what the main "Review …" button opens
}

/** "Review camera-like device": the fixed short name for the top finding's rule, or its fixed
 * title when the rule has none. Never AI text. */
export function reviewLabel(target: ReviewTarget | null, t: TFunction): string {
  if (!target) return t("results.review");
  const key = `results.reviewWhat.${target.finding.rule_id}`;
  const what = t(key); // i18next answers with the key itself when there's no short name
  return what && what !== key
    ? t("results.reviewNamed", { what })
    : t("results.reviewTitled", { title: target.finding.title });
}

/** "It offers…" -> "it offers…" after a colon; acronyms stay (app/questions.py lower_first). */
export function lowerFirst(sentence: string): string {
  return sentence.length > 1 && /[A-Z]/.test(sentence[0]!) && /[a-z]/.test(sentence[1]!) ? sentence[0]!.toLowerCase() + sentence.slice(1) : sentence;
}

/** The banner's one sentence: the top finding and its plainest clue (weights.yaml plain_rank),
 * e.g. "Likely camera: it offers a live video stream, the kind security cameras use." The rule's
 * observed sentence when there are no device clues. The same sentence as the PDF banner
 * (app/questions.py top_line). */
function describe(f: Finding, t: TFunction): string {
  const clue = f.lead_clue || f.clues?.[0] || f.observed || f.standard_explanation;
  return t("results.headline.topLine", { title: f.title, clue: lowerFirst(clue) });
}

/** The summary headline and one-line description, from fixed templates and real findings.
 * One counting rule, across every question: things to look at (cards with a High, Medium or
 * Low finding). Info items are never counted. */
export function headline(result: DiscoveryResult, t: TFunction, views: QuestionView[] = questionViews(result)): Headline {
  const things = thingsToLookAt(views);
  if (things > 0) {
    const top = views
      .flatMap((q) => q.cards)
      .sort((a, b) => byPriority(a.findings[0]!, b.findings[0]!))[0]!;
    return {
      title: t("results.headline.things", { count: things }),
      body: describe(top.findings[0]!, t),
      target: { kind: "here", id: groupId(top.key), group: top.kind, finding: top.findings[0]! },
    };
  }
  const info = views.reduce((n, q) => n + q.also.length + q.cards.reduce((m, c) => m + c.also.length, 0), 0);
  return {
    title: t("results.headline.none"),
    body: info > 0 ? t("results.headline.infoBody", { count: info }) : t("results.headline.noneBody"),
    target: null,
  };
}

/** The one count Results, the report summary and the PDF share: things to look at per
 * question, and their total. */
export function pageCounts(result: DiscoveryResult): { things: number; perQuestion: { id: QuestionView["id"]; things: number }[] } {
  const views = questionViews(result);
  return { things: thingsToLookAt(views), perQuestion: views.map((q) => ({ id: q.id, things: q.things })) };
}

// The one recovery step for a partial check, by the reason's code, most useful first. Only
// reasons with a real fix are here: a timeout or an error has no step to offer.
const RECOVERY_ORDER = ["no_network", "npcap_missing", "location_off", "no_wifi", "bluetooth_off", "passive_mode", "nmap_missing"];

/** The key of the single most useful recovery step for what wasn't checked, or null. */
export function recoveryStep(rows: CoverageItem[]): string | null {
  const codes = new Set(rows.filter((r) => r.state !== "completed").map((r) => r.reason_code));
  const code = RECOVERY_ORDER.find((c) => codes.has(c));
  return code ? `results.recover.${code}` : null;
}

export function coverageOf(result: DiscoveryResult): CoverageItem[] {
  return result.coverage ?? [];
}

export function isPartial(rows: CoverageItem[]): boolean {
  return rows.some((r) => r.state !== "completed");
}

export type RowState = "checked" | "notDetected" | "notChecked";
export interface CheckRow {
  check: CheckStatus;
  state: RowState;
  reason: string | null;
}

// The checks that look for something to flag (and the rules they feed): one that ran and
// flagged nothing reads "Not detected". Every other check that ran reads "Checked".
const DETECTING: Record<string, string[]> = { ...NETWORK_CHECKS, ...NEARBY_CHECKS };

/** One row per check, from the real check statuses. */
export function checkRows(result: DiscoveryResult): CheckRow[] {
  const flagged = (c: CheckStatus) => result.findings.some((f: Finding) => DETECTING[c.name]?.includes(f.rule_id));
  return result.checks.map((check) => {
    if (check.status !== "ran") {
      const text = check.short_reason ?? check.reason;
      return { check, state: "notChecked", reason: text ? shortPhrase(text) : null };
    }
    const state: RowState = check.name in DETECTING && !flagged(check) ? "notDetected" : "checked";
    return { check, state, reason: null };
  });
}

// Checks that count what they heard: their row says so, whatever was flagged (app/coverage.py).
/** The checks that find devices (app/coverage.py FINDING): the total row follows them. */
const FINDING = new Set(["passive_listen", "mdns", "arp_sweep", "ssdp", "onvif"]);

/** Where the "Devices heard in all" row goes in the Coverage and limits table (after the last
 * device-finding check), or -1 when no device check ran. It isn't a check, so "N checks"
 * never counts it. The same row as app/coverage.py table_rows, and the summary's number. */
export function totalRowAfter(result: DiscoveryResult): number {
  if (!result.checks.some((c) => FINDING.has(c.name) && c.status === "ran")) return -1;
  return result.checks.reduce((last, c, i) => (FINDING.has(c.name) ? i : last), -1);
}

const COUNTING = new Set(["passive_listen", "mdns", "arp_sweep", "ssdp", "onvif", "vendor_lookup", "port_check", "identity_check", "nearby_wifi", "bluetooth"]);
const ROWS = en.results.limits.rows as Record<string, string>;
const hasRow = (name: string) => name in ROWS || `${name}_one` in ROWS;

/** A check that ran, in its own words (results.limits.rows; the PDF says the same): what it
 * heard, or what "nothing flagged" means for it. A check that ran with a note shows the note;
 * one that flagged something says "Checked", since its finding is above. */
export function rowText(row: CheckRow, t: TFunction): string {
  const { check } = row;
  if (check.reason) {
    const note = shortPhrase(check.reason);
    return note.charAt(0).toUpperCase() + note.slice(1);
  }
  const key = `results.limits.rows.${check.name}`;
  if ((COUNTING.has(check.name) || row.state === "notDetected") && hasRow(check.name)) return t(key, { count: check.found });
  return t("results.limits.checked");
}


/** Device types with their own words in "Heard 9 devices: …" (results.heardType). Anything
 * else, or a guess below Possible, counts as an unidentified device. */
const HEARD_TYPES = ["router", "computer_phone", "tv", "speaker", "hub", "smart_plug", "camera", "lock_doorbell"] as const;

/** "Heard 9 devices: a router, 2 phones or computers and a TV." Device types only: never
 * names, makers or addresses. In a fixed order (the router first, unidentified last); null
 * when nothing was heard. */
export function heardLine(result: DiscoveryResult, t: TFunction): string | null {
  const n = result.devices.length;
  if (n === 0) return null;
  const tally = new Map<string, number>();
  for (const d of result.devices) {
    const fp = d.fingerprint;
    const known = fp && fp.band !== "Unclear" && (HEARD_TYPES as readonly string[]).includes(fp.type);
    const type = known ? fp.type : "unknown";
    tally.set(type, (tally.get(type) ?? 0) + 1);
  }
  const order = [...HEARD_TYPES, "unknown"];
  const parts = [...tally.entries()]
    .sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0]))
    .map(([type, count]) => t(`results.heardType.${type}`, { count }));
  const list = new Intl.ListFormat("en-GB", { style: "long", type: "conjunction" }).format(parts);
  return t("results.headline.heard", { count: n, list });
}
