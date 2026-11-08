"""FastAPI core. Runs as a normal user and is only ever bound to 127.0.0.1."""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import zipfile
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import (
    FastAPI,
    File,
    HTTPException,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import config, demo, version
from app.baseline.compare import assign_subjects
from app.baseline.models import Comparison, MatchDecision
from app.baseline.store import BaselineStore, DpapiProtector, default_store_path
from app.discovery.messages import message_for
from app.discovery.models import DiscoveryResult
from app.explain import ai
from app.explain.models import Explanations
from app.explain.service import explain
from app.handover import recheck as recheck_mod
from app.handover.models import (
    MAX_NOTES,
    Answer,
    HandoverState,
    PhysicalItemId,
    TaskStatus,
    clean_name,
    clean_note,
)
from app.handover.session import BaselineInfo, HandoverSession
from app.jobs import ScanBusy, ScanJob, ScanJobs, ScanSnapshot
from app.logsetup import configure_logging
from app.report import render, tamper
from app.rules.models import Location, StayType
from app.scan import ScanProgress, run_scan
from app.scanner import ScannerError, ScannerProcess
from app.setup_check import Setup, check_setup
from app.wireless.locator import LocatorTarget, locate, source_for
from app.wireless.models import NearbyItem
from app.wireless.survey import NearbyResult, run_nearby_check
from app.wireless.wlanapi import WirelessError

HOST = "127.0.0.1"
PORT = 8765
# The only pages allowed to open RoomCheck's WebSockets: the dashboard FastAPI serves itself,
# and the Vite dev server (web/vite.config.ts), which proxies /api here. Each by its address and
# by "localhost": opening the dashboard as http://localhost:8765 is the same page on this laptop,
# and without it the live connection was refused (403) while polling still worked.
PRODUCTION_ORIGIN = f"http://{HOST}:{PORT}"
DEV_ORIGIN = f"http://{HOST}:5173"
ALLOWED_ORIGINS = frozenset(
    {PRODUCTION_ORIGIN, DEV_ORIGIN, f"http://localhost:{PORT}", "http://localhost:5173"}
)
# The dashboard is bundled (web/dist): no CDNs, web fonts or remote images. Scripts, styles
# and everything else come only from RoomCheck itself.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; "
    f"font-src 'self'; connect-src 'self' ws://{HOST}:{PORT}; "
    "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)
# A report PDF shown inline on the Report screen: nothing in it may load anything, and only
# RoomCheck's own page may frame it. The browser's PDF viewer counts as an embedded object.
REPORT_PDF_POLICY = "default-src 'none'; object-src 'self'; frame-ancestors 'self'"
WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
WS_UNKNOWN_ITEM = 4404
WS_BAD_ORIGIN = 4403
SCAN_HEARTBEAT_SECONDS = 5.0  # a snapshot at least this often while a scan is quiet
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_REPORT_FILE = re.compile(r"^roomcheck-report-\d{8}-\d{6}\.(pdf|sha256|tsr|zip)$")

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.locator_targets = {}
    app.state.scan_jobs = ScanJobs()
    app.state.code_time = version.code_time()
    configure_logging()  # app.* INFO lines ("report: ...") to the terminal; idempotent
    # Printed by uvicorn, so an outdated server is easy to spot: restart after updating.
    logging.getLogger("uvicorn.error").info(version.startup_line(app.state.code_time))
    # Warm the shared AI client in the background so the first explanation doesn't pay for
    # connection setup. Only when a key is configured; a failure is logged as a code only.
    ai.start_warm_up(config.get_settings())
    if getattr(app.state, "demo_requested", False):
        # Demo mode: made-up data, a temporary store, and no scanner worker at all.
        demo.start(app.state)
        logging.getLogger("uvicorn.error").info(demo.BANNER)
        try:
            yield
        finally:
            app.state.locator_targets = {}
            demo.stop(app.state)
        return
    app.state.handover = HandoverSession(baseline_store())
    proc = ScannerProcess()
    app.state.scanner_process = proc  # restarted to cancel the worker's jobs
    try:
        app.state.scanner = proc.start()
    except (ScannerError, OSError):
        log.warning("scanner worker did not start; raw-packet checks will be reported as failed")
        app.state.scanner = None
    try:
        yield
    finally:
        app.state.locator_targets = {}
        proc.stop()
        app.state.scanner_process = None
        app.state.scanner = None


app = FastAPI(title="RoomCheck", lifespan=lifespan)
app.state.locator_targets = {}
app.state.scan_jobs = ScanJobs()
app.state.scanner_process = None
app.state.handover = None  # created at startup, from the encrypted store
app.state.code_time = None  # when the code this server started with was last changed
app.state.last_result = None  # the latest check, kept in memory only, for the report
app.state.report_dir = None  # None: the user's profile folder (render.default_report_dir)
locator_source = source_for  # where readings come from; replaced in tests


def baseline_store() -> BaselineStore:
    """The encrypted move-in store in %LOCALAPPDATA%\\RoomCheck. Replaced in tests."""
    return BaselineStore(default_store_path(), DpapiProtector())


def _handover(state: Any) -> HandoverSession:
    session: HandoverSession | None = getattr(state, "handover", None)
    if session is None:
        session = HandoverSession(baseline_store())
        state.handover = session
    return session


class DiscoveryRequest(BaseModel):
    # True only when the user says this is their network or they have permission to test it.
    consent: bool = False
    duration_seconds: int = Field(default=60, ge=10, le=120)
    # Allow the optional NVD lookup (product names only). False keeps everything offline.
    online: bool = True
    # The nearby Wi-Fi and Bluetooth check (public broadcasts only; never connects).
    nearby: bool = True
    # The room's Wi-Fi name, if you're not connected to it. An SSID is at most 32 bytes.
    room_network: str | None = Field(default=None, max_length=32)
    # Where you're staying (Start): changes some next steps. Optional for older pages.
    stay: StayType = "other"


class ScanStarted(BaseModel):
    id: str


class NearbyRequest(BaseModel):
    room_network: str | None = Field(default=None, max_length=32)


class ReportRequest(BaseModel):
    room_label: str | None = Field(default=None, max_length=render.MAX_ROOM_LABEL)
    # Two independent outside calls, each the user's choice.
    ai: bool = True  # AI explanations: finding types, no addresses or names, to Anthropic
    timestamp: bool = True  # trusted timestamp: only the report's fingerprint, to the service
    # What to include. Notes are off unless chosen; the network and device names are on.
    include_network_name: bool = True
    include_device_names: bool = True
    include_notes: bool = False


ServiceState = Literal["added", "unavailable", "not_requested"]


class ServiceOutcome(BaseModel):
    """What really happened with one optional service, after the report was made."""

    state: ServiceState
    reason: str | None = None  # "unavailable": why, in plain words


class ReportResponse(BaseModel):
    pdf: str
    sha256_file: str
    tsr: str | None
    bundle: str  # a ZIP of the PDF, the .sha256 and (if there is one) the .tsr
    sha256: str
    timestamped_at: datetime | None
    timestamp_message: str | None
    explanations: Explanations
    ai: ServiceOutcome
    timestamp: ServiceOutcome


def _remember_targets(state: Any, items: Iterable[NearbyItem]) -> None:
    """Only the latest check's flagged items can be located. Replaced on every check."""
    state.locator_targets = {
        i.ref: LocatorTarget(ref=i.ref, kind=i.kind, label=i.label) for i in items
    }


@app.middleware("http")
async def security_headers(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    response = await call_next(request)
    inline_pdf = request.url.path.startswith("/api/report/files/") and request.url.path.endswith(
        ".pdf"
    )
    response.headers["Content-Security-Policy"] = (
        REPORT_PDF_POLICY if inline_pdf else CONTENT_SECURITY_POLICY
    )
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


class Health(BaseModel):
    ok: bool
    scanner: bool
    version: str
    code_time: datetime | None  # the code this server started with
    dashboard_built: datetime | None
    # True: the code on disk changed after this server started, so it's running old code
    # (possibly with a newer dashboard). Restart RoomCheck.
    stale: bool
    demo: bool = False  # `python -m app --demo`: made-up data, nothing is scanned


@app.get("/api/setup")
def setup(request: Request) -> Setup:
    """The Start screen's readiness strip: the connected network (shown on this laptop only),
    five quick checks, and which optional outside calls this build makes. Read-only."""
    if demo.is_on(request.app.state):
        return demo.setup()
    return check_setup(config.get_settings())


@app.get("/api/health")
def health(request: Request) -> Health:
    started = getattr(request.app.state, "code_time", None)
    now = version.code_time()
    return Health(
        ok=True,
        scanner=getattr(request.app.state, "scanner", None) is not None,
        version=version.version(),
        code_time=started,
        dashboard_built=version.dashboard_time(),
        stale=bool(started and now and now > started),
        demo=demo.is_on(request.app.state),
    )


_scanner_lock = threading.Lock()


def _scanner_for_check(state: Any, progress: ScanProgress) -> Any:
    """The scanner worker for a new check. If the last check stopped waiting for a worker job
    (it timed out, so the worker may still be running it), or the worker isn't running, it is
    restarted first, so this check never shares the worker with leftover jobs. The page says
    "Finishing the previous check…" meanwhile."""
    proc = getattr(state, "scanner_process", None)
    scanner = getattr(state, "scanner", None)
    if proc is None:
        return scanner
    alive = getattr(proc, "alive", None)
    stale = scanner is None or getattr(scanner, "abandoned", False)
    if not stale and (alive is None or alive()):
        return scanner
    progress.preparing(True)
    try:
        with _scanner_lock:
            try:
                state.scanner = proc.restart()
            except (ScannerError, OSError):
                log.warning("scanner worker did not restart before a check")
                state.scanner = None
    finally:
        progress.preparing(False)
    return state.scanner


def _restart_scanner_after_cancel(state: Any, job: ScanJob) -> None:
    """Stop the cancelled check's worker jobs by restarting the worker, in the background so
    Cancel answers at once. The job reports "stopping" until the new worker is ready."""
    proc = getattr(state, "scanner_process", None)
    if proc is None:
        return
    job.begin_cleanup()

    def restart() -> None:
        try:
            with _scanner_lock:
                try:
                    state.scanner = proc.restart()
                except (ScannerError, OSError):
                    log.warning("scanner worker did not restart after a cancel")
                    state.scanner = None
        finally:
            job.end_cleanup()

    threading.Thread(target=restart, name=f"restart-{job.id}", daemon=True).start()


def _run_check(
    body: DiscoveryRequest, state: Any, progress: ScanProgress | None = None
) -> DiscoveryResult:
    """One full check and its explanations. Used by /api/discovery and by scan jobs."""
    progress = progress or ScanProgress()
    session = _handover(state)
    if demo.is_on(state):
        result = demo.run_check(body.consent, body.stay, progress)
        _remember_targets(state, result.nearby_items)
        state.last_result = result
        return result
    scanner = _scanner_for_check(state, progress)
    progress.raise_if_cancelled()
    result = run_scan(
        body.consent,
        scanner,
        body.duration_seconds,
        online=body.online,
        include_nearby=body.nearby,
        typed_room=body.room_network,
        progress=progress,
        baseline=session.facts(),
        match_salt=session.salt,
        stay_type=body.stay,
    )
    progress.raise_if_cancelled()
    progress.step("explain", "running")
    result.explanations = explain(
        result.findings, result.devices, result.nearby_items, online=body.online
    )
    progress.step("explain", "done")
    # A cancelled check keeps nothing: no report source, no locatable items.
    progress.raise_if_cancelled()
    _remember_targets(state, result.nearby_items)
    state.last_result = result
    return result


@app.post("/api/discovery")
def discovery(body: DiscoveryRequest, request: Request) -> DiscoveryResult:
    """The whole check as one long request. The dashboard uses /api/scans instead."""
    return _run_check(body, request.app.state)


@app.post("/api/scans", status_code=202)
def start_scan(body: DiscoveryRequest, request: Request) -> ScanStarted:
    """Start a check in a background thread; follow it on /api/scans/{id}/events."""
    state = request.app.state
    try:
        job = state.scan_jobs.start(lambda job: _run_check(body, state, job))
    except ScanBusy as e:
        code = "scan_stopping" if e.stopping else "scan_running"
        raise HTTPException(status_code=409, detail=message_for(code)) from e
    return ScanStarted(id=job.id)


def _job(request_or_ws: Request | WebSocket, job_id: str) -> ScanJob | None:
    job: ScanJob | None = request_or_ws.app.state.scan_jobs.get(job_id)
    return job


@app.get("/api/scans/{job_id}")
def scan_status(job_id: str, request: Request) -> ScanSnapshot:
    """The live state: every step's status, the current step, devices so far, elapsed time
    and the last update. The page polls this if the WebSocket drops. Has the result once done."""
    job = _job(request, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=message_for("scan_unknown"))
    return job.snapshot(with_result=True)


@app.post("/api/scans/{job_id}/cancel")
def cancel_scan(job_id: str, request: Request) -> ScanSnapshot:
    """Stop a check. Jobs already running in the scanner worker (listening, sweeps, port
    checks) are stopped by restarting the worker; nothing from the check is kept."""
    state = request.app.state
    job = _job(request, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=message_for("scan_unknown"))
    if job.cancel():
        _restart_scanner_after_cancel(state, job)
    return job.snapshot()


@app.websocket("/api/scans/{job_id}/events")
async def scan_events(websocket: WebSocket, job_id: str) -> None:
    """The live state as JSON snapshots ({"type": "state", ...}): one at once, one on every
    change, and a heartbeat every few seconds while nothing changes, so the page can tell a
    quiet scan from a lost connection. Closes after the final state. If the connection ends
    early, the terminal says how, so a dropped live connection can be traced."""
    origin = websocket.headers.get("origin")
    if not _origin_allowed(origin):
        log.warning(
            "refused a live connection from a page at %s; open RoomCheck at %s",
            origin,
            PRODUCTION_ORIGIN,
        )
        await websocket.close(code=WS_BAD_ORIGIN)
        return
    await websocket.accept()
    job = _job(websocket, job_id)
    if job is None:
        await websocket.send_json({"type": "failed", "text": message_for("scan_unknown")})
        await websocket.close(code=WS_UNKNOWN_ITEM)
        return
    version = -1
    try:
        while True:
            snap = job.snapshot()
            await websocket.send_json({"type": "state", **snap.model_dump(mode="json")})
            if snap.state != "running" and not snap.stopping:
                break
            version = snap.version
            # Wait for a change in a worker thread, so the event loop stays free.
            await asyncio.to_thread(job.wait_for_change, version, SCAN_HEARTBEAT_SECONDS)
        await websocket.close()
    except WebSocketDisconnect as e:
        if job.state == "running":  # the page left, or the connection broke, mid-check
            log.info(
                "check %s: live connection closed by the page (code %s) at %.0f s; "
                "the page carries on by polling",
                job.id,
                e.code,
                job.snapshot().elapsed_seconds,
            )
    except Exception:
        log.exception("check %s: the live connection failed", job.id)
        raise


def _report_dir(request: Request) -> Path:
    return request.app.state.report_dir or render.default_report_dir()


@app.post("/api/report")
def make_report(body: ReportRequest, request: Request) -> ReportResponse:
    """A PDF of the latest check, its .sha256 and (when online) an RFC 3161 .tsr token."""
    result: DiscoveryResult | None = request.app.state.last_result
    if result is None:
        raise HTTPException(status_code=409, detail=message_for("report_no_scan"))
    settings = config.get_settings()
    changes = _compare(request)
    in_demo = demo.is_on(request.app.state)  # built locally, never timestamped
    ai_requested = body.ai and settings.anthropic_api_key is not None
    if ai_requested:
        explanations = result.explanations or explain(
            result.findings, result.devices, result.nearby_items, online=True
        )
    else:
        # Not chosen (or no key): standard words only, and nothing sent to Anthropic.
        explanations = explain(result.findings, result.devices, result.nearby_items, online=False)
    try:
        report = render.make_report(
            result,
            explanations,
            room_label=body.room_label,
            out_dir=_report_dir(request),
            online=body.timestamp and not in_demo,
            tsa_url=settings.tsa_url,
            render=render.render_pdf,
            request=tamper.request_token,
            handover=_handover(request.app.state).state_for(result),
            # "What's changed since move-in?", as Results shows it.
            compare_state=changes.state,
            comparison=changes.comparison,
            privacy=render.ReportPrivacy(
                network_name=body.include_network_name,
                device_names=body.include_device_names,
                notes=body.include_notes,
            ),
        )
    except render.PdfUnavailable as e:
        raise HTTPException(status_code=503, detail=message_for("pdf_unavailable")) from e
    files = report.files
    bundle = _bundle(files.pdf, [files.pdf, files.sha256_file, *([files.tsr] if files.tsr else [])])
    if body.room_label and body.room_label.strip():
        _handover(request.app.state).set_room_label(body.room_label.strip())  # offered next time
    return ReportResponse(
        pdf=files.pdf.name,
        sha256_file=files.sha256_file.name,
        tsr=files.tsr.name if files.tsr else None,
        bundle=bundle.name,
        sha256=files.sha256,
        timestamped_at=files.timestamped_at,
        timestamp_message=files.timestamp_message,
        explanations=explanations,
        ai=_ai_outcome(ai_requested, explanations),
        timestamp=(
            ServiceOutcome(state="not_requested")
            if not body.timestamp
            else ServiceOutcome(state="unavailable", reason=message_for("demo_no_timestamp"))
            if in_demo
            else ServiceOutcome(state="added")
            if files.tsr
            else ServiceOutcome(state="unavailable", reason=files.timestamp_message)
        ),
    )


def _bundle(pdf: Path, members: list[Path]) -> Path:
    """One ZIP with the report's files, beside them, for a single download."""
    path = pdf.with_suffix(".zip")
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for member in members:
            z.write(member, arcname=member.name)
    return path


class ReportDefaults(BaseModel):
    room_label: str | None = None  # the last room label used, if any


@app.get("/api/report/defaults")
def report_defaults(request: Request) -> ReportDefaults:
    """What the report form starts with: the last room label used (saved, encrypted)."""
    return ReportDefaults(room_label=_handover(request.app.state).room_label)


def _ai_outcome(requested: bool, explanations: Explanations) -> ServiceOutcome:
    if not requested:
        return ServiceOutcome(state="not_requested")
    if explanations.ai_status in ("used", "partly_used"):
        return ServiceOutcome(state="added")
    if explanations.ai_status == "none":  # nothing to explain
        return ServiceOutcome(state="not_requested")
    return ServiceOutcome(
        state="unavailable",
        reason=explanations.ai_reason_text or message_for("internal"),
    )


@app.get("/api/report/files/{name}")
def report_file(name: str, request: Request, inline: bool = False) -> FileResponse:
    """A report file. Only RoomCheck's own file names, from the report folder. inline=true
    shows a PDF in the page (the Report screen's preview) instead of downloading it."""
    if not _REPORT_FILE.fullmatch(name):
        raise HTTPException(status_code=404)
    path = _report_dir(request) / name
    if not path.is_file():
        raise HTTPException(status_code=404)
    disposition = "inline" if inline and name.endswith(".pdf") else "attachment"
    return FileResponse(path, filename=name, content_disposition_type=disposition)


# --- Layer 6: recognition answers, handover tasks, the move-in baseline ----------------------


class AnswerRequest(BaseModel):
    subject: str = Field(max_length=200)
    answer: Answer | None  # None: back to no answer
    confirmed: bool | None = None  # "Host's" only: has the host confirmed it?


class NameRequest(BaseModel):
    subject: str = Field(max_length=200)
    name: str = Field(max_length=200)  # cleaned to at most 40 plain characters
    note: str | None = Field(default=None, max_length=1000)  # None: leave the note as it is


class TaskUpdate(BaseModel):
    status: TaskStatus | None = None
    notes: str | None = Field(default=None, max_length=MAX_NOTES)
    host_confirmed: bool | None = None  # evidence: the user records the host's answer


class CompareResponse(BaseModel):
    # none: no move-in scan saved. unreadable: it can't be decrypted. no_check: no check to
    # compare yet. ready: the comparison is below.
    state: str
    baseline: BaselineInfo
    comparison: Comparison | None = None


@app.get("/api/handover")
def handover_state(request: Request) -> HandoverState:
    """The tasks for the latest check, the recognition answers and the bundled message."""
    state = request.app.state
    return _handover(state).state_for(state.last_result)


@app.post("/api/answers")
def set_answer(body: AnswerRequest, request: Request) -> HandoverState:
    """ "Do you recognise this device?": changes guidance and tasks, never the findings."""
    state = request.app.state
    session = _handover(state)
    session.set_answer(body.subject, body.answer, body.confirmed)
    return session.state_for(state.last_result)


@app.post("/api/names")
def set_name(body: NameRequest, request: Request) -> HandoverState:
    """A short name for a device, shown wherever it appears, and an optional short note from
    "Help identify this". Plain text only; "" removes either."""
    try:
        name = clean_name(body.name)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=message_for("name_invalid")) from e
    try:
        note = clean_note(body.note) if body.note is not None else None
    except ValueError as e:
        raise HTTPException(status_code=422, detail=message_for("note_invalid")) from e
    state = request.app.state
    session = _handover(state)
    session.set_name(body.subject, name)
    if note is not None:
        session.set_note(body.subject, note)
    return session.state_for(state.last_result)


class LocationRequest(BaseModel):
    subject: str = Field(max_length=300)
    location: Location | None  # None: back to no answer


@app.post("/api/locations")
def set_location(body: LocationRequest, request: Request) -> HandoverState:
    """A camera's "Where is it?": changes its next step, never the finding."""
    state = request.app.state
    session = _handover(state)
    session.set_location(body.subject, body.location)
    return session.state_for(state.last_result)


class PhysicalItemRequest(BaseModel):
    item: PhysicalItemId
    looked: bool | None = None
    note: str | None = Field(default=None, max_length=400)


class PhysicalDoneRequest(BaseModel):
    done: bool


@app.post("/api/physical")
def set_physical_item(body: PhysicalItemRequest, request: Request) -> HandoverState:
    """One place in the guided physical check: looked at or not, and an optional note."""
    try:
        note = clean_note(body.note) if body.note is not None else None
    except ValueError as e:
        raise HTTPException(status_code=422, detail=message_for("note_invalid")) from e
    state = request.app.state
    session = _handover(state)
    session.set_physical_item(body.item, body.looked, note)
    return session.state_for(state.last_result)


@app.post("/api/physical/done")
def finish_physical(body: PhysicalDoneRequest, request: Request) -> HandoverState:
    """The physical check is done (dated), or back in progress."""
    state = request.app.state
    session = _handover(state)
    session.finish_physical(body.done)
    return session.state_for(state.last_result)


@app.patch("/api/tasks/{task_id}")
def update_task(task_id: str, body: TaskUpdate, request: Request) -> HandoverState:
    state = request.app.state
    session = _handover(state)
    current = session.state_for(state.last_result)
    if task_id not in {t.id for t in current.tasks}:
        raise HTTPException(status_code=404, detail=message_for("task_unknown"))
    session.update_task(
        task_id,
        body.status,
        body.notes,
        host_confirmed=body.host_confirmed,
        check_at=state.last_result.started_at if state.last_result else None,
    )
    return session.state_for(state.last_result)


_recheck_lock = threading.Lock()  # one recheck at a time, and never during a check


@app.post("/api/tasks/{task_id}/recheck")
def recheck_task(task_id: str, request: Request) -> HandoverState:
    """Run only the check that can observe this task's fix, and keep what it found. Offered
    once a task is Done or Host confirmed, and only where RoomCheck can observe the fix."""
    state = request.app.state
    session = _handover(state)
    result = state.last_result
    task = next((t for t in session.state_for(result).tasks if t.id == task_id), None)
    if task is None or result is None:
        raise HTTPException(status_code=404, detail=message_for("task_unknown"))
    if task.recheck_offer != "available":
        raise HTTPException(status_code=409, detail=message_for("recheck_unavailable"))
    if state.scan_jobs.busy() or not _recheck_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail=message_for("scan_running"))
    try:
        found = recheck_mod.recheck(
            task,
            result,
            salt=session.salt,
            collectors=(
                demo.recheck_collectors(result)
                if demo.is_on(state)
                else recheck_mod.real_collectors(getattr(state, "scanner", None))
            ),
        )
    finally:
        _recheck_lock.release()
    session.save_recheck(task_id, found)
    return session.state_for(result)


@app.get("/api/baseline")
def baseline_info(request: Request) -> BaselineInfo:
    return _handover(request.app.state).info()


@app.post("/api/baseline")
def save_baseline(request: Request) -> BaselineInfo:
    """Save the latest check as the move-in scan (replacing any earlier one), encrypted on
    this laptop, with the recognition answers and task notes so far."""
    state = request.app.state
    if state.last_result is None:
        raise HTTPException(status_code=409, detail=message_for("baseline_needs_check"))
    return _handover(state).save_baseline(state.last_result)


@app.delete("/api/baseline")
def delete_baseline(request: Request) -> BaselineInfo:
    return _handover(request.app.state).delete_baseline()


class DataDeleted(BaseModel):
    baseline: BaselineInfo
    handover: HandoverState


@app.delete("/api/data")
def delete_all_data(request: Request) -> DataDeleted:
    """Delete all saved RoomCheck data from the local store: the move-in scan, handover tasks,
    statuses, notes, recognition answers, device names and the matching salt. Report files
    saved in the reports folder aren't touched."""
    state = request.app.state
    session = _handover(state)
    session.delete_all()
    if state.last_result is not None:
        # The latest check's subjects come from the old salt: give it the new one, so nothing
        # made from now on can be linked to what was deleted.
        assign_subjects(state.last_result, session.salt)
    return DataDeleted(baseline=session.info(), handover=session.state_for(state.last_result))


@app.get("/api/compare")
def compare_with_baseline(request: Request) -> CompareResponse:
    return _compare(request)


class MatchRequest(BaseModel):
    match_id: str = Field(max_length=300)
    decision: MatchDecision | None  # None: back to no answer


@app.post("/api/compare/matches")
def set_match(body: MatchRequest, request: Request) -> CompareResponse:
    """ "Possibly the same device": the user's answer. It changes how Compare groups the two
    checks, never a finding or its priority."""
    _handover(request.app.state).set_match(body.match_id, body.decision)
    return _compare(request)


def _compare(request: Request) -> CompareResponse:
    state = request.app.state
    session = _handover(state)
    info = session.info()
    if info.state != "saved":
        return CompareResponse(state=info.state, baseline=info)
    if state.last_result is None:
        return CompareResponse(state="no_check", baseline=info)
    comparison = session.comparison(state.last_result)
    return CompareResponse(state="ready", baseline=info, comparison=comparison)


async def _read_capped(upload: UploadFile | None) -> bytes | None:
    if upload is None:
        return None
    data = await upload.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=message_for("file_too_large"))
    return data


@app.post("/api/verify")
async def verify_report(
    pdf: Annotated[UploadFile, File()],
    tsr: Annotated[UploadFile | None, File()] = None,
    sha256: Annotated[UploadFile | None, File()] = None,
) -> tamper.VerifyResult:
    """Recompute the PDF's hash and check it against the .tsr token and the .sha256 file."""
    pdf_bytes = await _read_capped(pdf)
    assert pdf_bytes is not None
    tsr_bytes = await _read_capped(tsr)
    hash_bytes = await _read_capped(sha256)
    expected = tamper.read_hash_file(hash_bytes.decode("ascii", "replace")) if hash_bytes else None
    return tamper.verify(pdf_bytes, tsr_bytes, expected)


@app.post("/api/nearby")
def nearby_check(body: NearbyRequest, request: Request) -> NearbyResult:
    if demo.is_on(request.app.state):  # the demo never listens to the radios
        raise HTTPException(status_code=409, detail=message_for("demo_unavailable"))
    result = run_nearby_check(typed_room=body.room_network)
    _remember_targets(request.app.state, result.items)
    return result


def _origin_allowed(origin: str | None) -> bool:
    """Browsers let any web page open a WebSocket to 127.0.0.1, so only accept our own pages:
    exactly the production and dev origins. No Origin header means a non-browser client on this
    laptop (e.g. a script); no web page can open one without it."""
    if origin is None:
        return True
    return origin in ALLOWED_ORIGINS


@app.websocket("/api/nearby/locate/{ref}")
async def locate_ws(websocket: WebSocket, ref: str) -> None:
    """Stream smoothed signal readings for one flagged item: Bluetooth several times a second,
    Wi-Fi once per scan. Nothing is stored; the stream ends when the page closes it."""
    if not _origin_allowed(websocket.headers.get("origin")):
        await websocket.close(code=WS_BAD_ORIGIN)
        return
    await websocket.accept()
    target = websocket.app.state.locator_targets.get(ref)
    if target is None:
        await websocket.send_json({"error": message_for("locator_unknown_item")})
        await websocket.close(code=WS_UNKNOWN_ITEM)
        return
    in_demo = demo.is_on(websocket.app.state)  # made-up readings, no radio
    source = demo.locator_source(target) if in_demo else locator_source(target)

    async def pump() -> None:
        try:
            async for reading in locate(target, source):
                await websocket.send_json(reading.model_dump())
        except WirelessError as e:
            await websocket.send_json({"error": message_for(e.code)})
        await websocket.close()

    # Stop as soon as the page closes the connection (Stop, or leaving the screen), not at the
    # next reading, which for Wi-Fi can be several seconds away. Any message also means stop.
    readings = asyncio.create_task(pump())
    closed = asyncio.create_task(websocket.receive())
    try:
        await asyncio.wait({readings, closed}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (readings, closed):
            task.cancel()
        await asyncio.gather(readings, closed, return_exceptions=True)
        await source.aclose()  # type: ignore[attr-defined]


# The built dashboard, mounted last so it never shadows /api. One origin: FastAPI serves it.
if WEB_DIST.is_dir():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")
else:

    @app.get("/")
    def dashboard_not_built() -> PlainTextResponse:
        return PlainTextResponse(
            "The dashboard isn't built yet. Run: npm --prefix web install, then "
            "npm --prefix web run build. Then restart RoomCheck."
        )
