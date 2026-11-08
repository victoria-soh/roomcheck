// REST and WebSocket calls to the RoomCheck backend. Same origin only: in production FastAPI
// serves this page, and in development Vite proxies /api. No other host is ever contacted.
import type { Answer, BaselineInfo, CompareResponse, HandoverState, CameraLocation, MatchDecision, PhysicalItemId, ReportResponse, ScanMessage, ScanSnapshot, ScanStarted, Setup, StayType, TaskStatus, VerifyResult } from "./types";

export class ApiError extends Error {
  // `detail` is the backend's plain-language message, when it sent one.
  constructor(
    readonly status: number,
    readonly detail: string | null,
  ) {
    super(detail ?? `HTTP ${status}`);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // A FormData body sets its own multipart content type.
  const json = !(init?.body instanceof FormData);
  const response = await fetch(path, {
    ...init,
    headers: json ? { "Content-Type": "application/json", ...init?.headers } : init?.headers,
  });
  if (!response.ok) {
    let detail: string | null = null;
    try {
      const body: unknown = await response.json();
      if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") {
        detail = body.detail;
      }
    } catch {
      // not JSON; keep the status only
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

export interface Health {
  ok: boolean;
  version: string;
  code_time: string | null;
  dashboard_built: string | null;
  stale: boolean; // the server's code changed after it started: restart RoomCheck
  demo?: boolean; // `python -m app --demo`: made-up data, nothing is scanned
}

/** Read-only: the connected network, five readiness checks and the outside calls in use. */
export function getSetup(): Promise<Setup> {
  return request<Setup>("/api/setup");
}

export function getHealth(): Promise<Health> {
  return request<Health>("/api/health");
}

export function startScan(consent: boolean, stay: StayType = "other"): Promise<ScanStarted> {
  return request<ScanStarted>("/api/scans", {
    method: "POST",
    body: JSON.stringify({ consent, stay }),
  });
}

export function getScan(id: string): Promise<ScanSnapshot> {
  return request<ScanSnapshot>(`/api/scans/${encodeURIComponent(id)}`);
}

export function cancelScan(id: string): Promise<ScanSnapshot> {
  return request<ScanSnapshot>(`/api/scans/${encodeURIComponent(id)}/cancel`, { method: "POST" });
}

/** What the report includes and which outside services it uses: each a separate choice. */
export interface ReportChoices {
  ai: boolean;
  timestamp: boolean;
  include_network_name: boolean;
  include_device_names: boolean;
  include_notes: boolean;
}

/** Make the report. */
export function createReport(choices: ReportChoices, roomLabel: string | null): Promise<ReportResponse> {
  return request<ReportResponse>("/api/report", {
    method: "POST",
    body: JSON.stringify({ ...choices, room_label: roomLabel || null }),
  });
}

/** What the report form starts with: the last room label used, if any. */
export function getReportDefaults(): Promise<{ room_label: string | null }> {
  return request<{ room_label: string | null }>("/api/report/defaults");
}

/** A report file from the backend's report folder; inline shows a PDF in the page. */
export function reportFileUrl(name: string, inline = false): string {
  return `/api/report/files/${encodeURIComponent(name)}${inline ? "?inline=true" : ""}`;
}

/** Checked by RoomCheck's own backend on this laptop (127.0.0.1); nothing goes further. */
export function verifyReport(pdf: Blob, tsr: Blob | null, sha256: Blob | null): Promise<VerifyResult> {
  const form = new FormData();
  form.append("pdf", pdf, "report.pdf");
  if (tsr) form.append("tsr", tsr, "report.tsr");
  if (sha256) form.append("sha256", sha256, "report.sha256");
  return request<VerifyResult>("/api/verify", { method: "POST", body: form });
}

// --- Layer 6: everything stays on this laptop ----------------------------------------------

export function getHandover(): Promise<HandoverState> {
  return request<HandoverState>("/api/handover");
}

export function setAnswer(subject: string, answer: Answer | null, confirmed?: boolean | null): Promise<HandoverState> {
  return request<HandoverState>("/api/answers", {
    method: "POST",
    body: JSON.stringify({ subject, answer, confirmed: confirmed ?? null }),
  });
}

/** A short plain-text name for a device, and optionally a short note; "" removes either. */
export function setName(subject: string, name: string, note?: string): Promise<HandoverState> {
  return request<HandoverState>("/api/names", {
    method: "POST",
    body: JSON.stringify(note === undefined ? { subject, name } : { subject, name, note }),
  });
}

/** A camera's "Where is it?"; null goes back to no answer. */
export function setLocation(subject: string, location: CameraLocation | null): Promise<HandoverState> {
  return request<HandoverState>("/api/locations", { method: "POST", body: JSON.stringify({ subject, location }) });
}

/** One place in the guided physical check: looked at or not, and an optional note. */
export function setPhysicalItem(item: PhysicalItemId, change: { looked?: boolean; note?: string }): Promise<HandoverState> {
  return request<HandoverState>("/api/physical", { method: "POST", body: JSON.stringify({ item, ...change }) });
}

/** The physical check is done (dated), or back in progress. */
export function finishPhysical(done: boolean): Promise<HandoverState> {
  return request<HandoverState>("/api/physical/done", { method: "POST", body: JSON.stringify({ done }) });
}

/** Run only the check that can observe this task's fix (Done or Host confirmed tasks only). */
export function recheckTask(id: string): Promise<HandoverState> {
  return request<HandoverState>(`/api/tasks/${encodeURIComponent(id)}/recheck`, { method: "POST" });
}

export function updateTask(
  id: string,
  change: { status?: TaskStatus; notes?: string; host_confirmed?: boolean },
): Promise<HandoverState> {
  return request<HandoverState>(`/api/tasks/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(change),
  });
}

/** Delete all saved RoomCheck data from the local store (not report files). */
export function deleteAllData(): Promise<{ baseline: BaselineInfo; handover: HandoverState }> {
  return request<{ baseline: BaselineInfo; handover: HandoverState }>("/api/data", { method: "DELETE" });
}

export function getBaseline(): Promise<BaselineInfo> {
  return request<BaselineInfo>("/api/baseline");
}

export function saveBaseline(): Promise<BaselineInfo> {
  return request<BaselineInfo>("/api/baseline", { method: "POST" });
}

export function deleteBaseline(): Promise<BaselineInfo> {
  return request<BaselineInfo>("/api/baseline", { method: "DELETE" });
}

export function getCompare(): Promise<CompareResponse> {
  return request<CompareResponse>("/api/compare");
}

/** "Possibly the same device": the user's answer (null goes back to no answer). */
export function setMatch(matchId: string, decision: MatchDecision | null): Promise<CompareResponse> {
  return request<CompareResponse>("/api/compare/matches", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ match_id: matchId, decision }),
  });
}

export function locateUrl(ref: string, location: Location = window.location): string {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${location.host}/api/nearby/locate/${encodeURIComponent(ref)}`;
}

export function scanEventsUrl(id: string, location: Location = window.location): string {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${location.host}/api/scans/${encodeURIComponent(id)}/events`;
}

export interface EventStream {
  close(): void;
}

/** Follow a scan's live state. `onClose(finished)` says whether the final state arrived. */
export function followScan(
  id: string,
  onMessage: (message: ScanMessage) => void,
  onClose: (finished: boolean) => void,
): EventStream {
  const socket = new WebSocket(scanEventsUrl(id));
  let finished = false;
  let closedByUs = false;
  socket.onmessage = (event: MessageEvent) => {
    let message: ScanMessage;
    try {
      message = JSON.parse(String(event.data)) as ScanMessage;
    } catch {
      return;
    }
    if (message.type === "failed" || message.state !== "running") finished = true;
    onMessage(message);
  };
  socket.onclose = () => {
    if (!closedByUs) onClose(finished);
  };
  return {
    close() {
      closedByUs = true;
      socket.close();
    },
  };
}
