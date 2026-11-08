// Results organised by the renter's questions: the same grouping and status as the PDF
// (app/questions.py), with the same one counting rule. A "thing to look at" is a card with a
// High, Medium or Low finding; Info findings never count. They sit inside the card for the
// same device or signal ("Also found"), or are listed at the end of their question.
//
// QUESTION_CHECKS and QUESTION_OF_RULE copy rules.yaml (tests/unit/test_questions.py keeps them
// equal), and the demo check's numbers are held to the PDF's in Consistency.test.tsx.
import type { Device, DiscoveryResult, Finding, Question } from "../api/types";

export const QUESTIONS: Question[] = ["watching", "control", "wifi"];

// The checks each question's status line depends on (rules.yaml, questions).
export const QUESTION_CHECKS: Record<Question, string[]> = {
  watching: ["passive_listen", "mdns", "arp_sweep", "ssdp", "onvif", "port_check", "identity_check", "nearby_wifi", "bluetooth"],
  control: ["passive_listen", "mdns", "arp_sweep", "ssdp", "vendor_lookup", "port_check", "identity_check", "cve"],
  wifi: ["wifi_encryption", "dns", "arp", "dhcp", "upnp", "nearby_wifi", "lookalike", "wps"],
};

// Each rule's question (rules.yaml), for findings saved before they carried one.
export const QUESTION_OF_RULE: Record<string, Question> = {
  "R-CAM": "watching",
  "R-NEW-CAMERA": "watching",
  "R-CAMHOT": "watching",
  "R-TRACKER": "watching",
  "R-LOCK": "control",
  "R-CLOUD": "control",
  "R-TELNET": "control",
  "R-CVE": "control",
  "R-WIFI-ENC": "wifi",
  "R-UPNP": "wifi",
  "R-DNS": "wifi",
  "R-ARP": "wifi",
  "R-DHCP": "wifi",
  "R-TWIN": "wifi",
  "R-TWIN-VENDOR": "wifi",
  "R-TWIN-DOWNGRADE": "wifi",
  "R-WPS": "wifi",
  "R-HIDDEN": "wifi",
  "R-OPEN": "wifi",
};

export function questionOf(f: Finding): Question {
  return f.question ?? QUESTION_OF_RULE[f.rule_id] ?? "wifi";
}

const RANK = { High: 0, Medium: 1, Low: 2, Info: 3 } as const;
const BAND = { Likely: 0, Possible: 1, Unclear: 2 } as const;

/** Most serious first; within a priority, the surer finding first; otherwise as given. */
function byRank(a: Finding, b: Finding): number {
  return RANK[a.severity] - RANK[b.severity] || BAND[a.confidence_band] - BAND[b.confidence_band];
}

export type CardKind = "device" | "nearby" | "network";

/** One card under a question. */
export interface QuestionCard {
  key: string; // unique on the page; also the card's element id
  kind: CardKind;
  question: Question;
  deviceRef: string | null;
  nearbyRef: string | null;
  findings: Finding[]; // High, Medium or Low, most serious first
  also: Finding[]; // Info: "Also found", not counted
}

export type QuestionState = "look" | "info" | "notDetected" | "notChecked";

// R-CAM's flag threshold (rules.yaml): a camera score below it isn't flagged.
export const CAMERA_THRESHOLD = 0.5;

function cameraScore(d: Device): number {
  const fp = d.fingerprint;
  if (!fp) return 0;
  if (fp.type === "camera") return fp.confidence ?? 0;
  return [...(fp.other_types ?? []), ...(fp.weak_types ?? [])].find((t) => t.type === "camera")?.score ?? 0;
}

/** Devices that gave a camera clue too weak to flag (above zero, below the threshold): one
 * line under "Is anything watching?", never counted (app/questions.py weak_camera_devices). */
export function weakCameraDevices(result: DiscoveryResult): string[] {
  const flagged = new Set(result.findings.filter((f) => f.rule_id === "R-CAM" || f.rule_id === "R-NEW-CAMERA").map((f) => f.device_ref));
  return result.devices.filter((d) => !flagged.has(d.id) && cameraScore(d) > 0 && cameraScore(d) < CAMERA_THRESHOLD).map((d) => d.id);
}

export interface QuestionView {
  id: Question;
  things: number; // cards: the only number the headline adds up
  state: QuestionState;
  notCheckedReason: string | null; // set whenever any of its checks didn't run
  cards: QuestionCard[];
  also: Finding[]; // Info findings with no card to sit in
  weakCamera: string[]; // "Is anything watching?" only: devices with a weak camera clue
}

function subject(f: Finding): [CardKind, string] {
  if (f.scope === "device" && f.device_ref) return ["device", f.device_ref];
  if (f.scope === "nearby" && f.nearby_ref) return ["nearby", f.nearby_ref];
  return ["network", f.id];
}

function cardId(text: string): string {
  return text.replace(/[^A-Za-z0-9_-]/g, "-");
}

/** Every question with its cards and status, in order. */
export function questionViews(result: DiscoveryResult): QuestionView[] {
  const findings = [...result.findings].sort(byRank);
  const cards: Record<Question, Map<string, QuestionCard>> = { watching: new Map(), control: new Map(), wifi: new Map() };
  for (const f of findings) {
    if (f.severity === "Info") continue;
    const q = questionOf(f);
    const [kind, ref] = subject(f);
    const id = `${kind}:${ref}`;
    let card = cards[q].get(id);
    if (!card) {
      card = {
        key: cardId(`q-${q}-${kind}-${ref}`),
        kind,
        question: q,
        deviceRef: kind === "device" ? f.device_ref : null,
        nearbyRef: kind === "nearby" ? f.nearby_ref : null,
        findings: [],
        also: [],
      };
      cards[q].set(id, card);
    }
    card.findings.push(f);
  }

  const orphans: Record<Question, Finding[]> = { watching: [], control: [], wifi: [] };
  for (const f of findings) {
    if (f.severity !== "Info") continue;
    const own = questionOf(f);
    const [kind, ref] = subject(f);
    const id = `${kind}:${ref}`;
    const order = [own, ...QUESTIONS.filter((q) => q !== own)];
    const hostQ = kind === "network" ? undefined : order.find((q) => cards[q].has(id));
    if (hostQ) cards[hostQ].get(id)!.also.push(f);
    else orphans[own].push(f);
  }

  const byName = new Map(result.checks.map((c) => [c.name, c]));
  return QUESTIONS.map((q) => {
    const relevant = QUESTION_CHECKS[q].map((n) => byName.get(n)).filter((c) => c !== undefined);
    const missed = relevant.filter((c) => c.status !== "ran");
    let reason: string | null = null;
    if (missed.length > 0) {
      const first = missed.find((c) => c.status === "skipped") ?? missed[0]!;
      const text = first.short_reason ?? (first.reason ? shortPhrase(first.reason) : null);
      reason = text || "it wasn't checked this time";
    }
    const things = cards[q].size;
    let state: QuestionState;
    if (things > 0) state = "look";
    else if (orphans[q].length > 0) state = "info";
    else if (relevant.length > 0 && missed.length < relevant.length) state = "notDetected";
    else {
      state = "notChecked";
      reason = reason ?? "it wasn't checked this time";
    }
    return {
      id: q,
      things,
      state,
      notCheckedReason: reason,
      cards: [...cards[q].values()],
      also: orphans[q],
      weakCamera: q === "watching" ? weakCameraDevices(result) : [],
    };
  });
}

/** The headline's one number: cards across every question. */
export function thingsToLookAt(views: QuestionView[]): number {
  return views.reduce((n, q) => n + q.things, 0);
}

/** A reason as a short phrase for "Not checked: <reason>" (app/coverage.py short_phrase): its
 * first sentence without its own "Not checked" opening or the full stop, so a row never says
 * "Not checked" twice. */
export function shortPhrase(message: string): string {
  const first = message.trim().split(/(?<=\.)\s/)[0] ?? "";
  return first.replace(/^\s*not checked\s*[:,]?\s*(because\s+)?/i, "").replace(/\.$/, "").trim();
}
