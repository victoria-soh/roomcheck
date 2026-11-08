"""Build the handover report: Jinja2 HTML, then a PDF, then its hash and timestamp token.

What goes in (docs/original-plan.md, Layer 5): scan date and time, the optional room label, which
checks ran and which didn't, findings with confidence, evidence, explanation and next steps, the
landlord message draft, what the scan can't see, and the known limitations. MACs are masked to the
maker plus the last 3 octets. Nothing about neighbours' devices: only flagged items were kept, and
the names of neighbours' open networks are replaced with a count.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup
from pydantic import BaseModel

from app.baseline.models import Comparison
from app.coverage import check_counts, table_rows
from app.discovery.models import Device, DiscoveryResult
from app.explain.models import Explanations
from app.explain.service import message_findings
from app.handover.models import PHYSICAL_ITEMS, HandoverState, PhysicalCheck
from app.questions import (
    partly_line,
    question_statuses,
    status_line,
    text,
    things_to_look_at,
    top_line,
    weak_camera_line,
)
from app.report import tamper
from app.report.masking import mask_mac, mask_text
from app.vocabulary import CLUES_NOT_PROOF

log = logging.getLogger(__name__)

TEMPLATES = Path(__file__).resolve().parent / "templates"
DATA = Path(__file__).resolve().parent / "data"
# The main mark (docs/branding/roomcheck-mark.svg) and the Saira SemiBold wordmark font (SIL
# OFL, data/saira-OFL.txt), embedded in the report so the offline renderer fetches nothing.
MARK_PATH = (
    "M16 6 H48 L54 12 V32 L32 55 L10 32 V12 Z M18 34 V24 L32 14.6 L46 24 V34 H35.5 V27 H28.5 V34 Z"
)


@lru_cache(maxsize=1)
def wordmark_font() -> str:
    return base64.b64encode((DATA / "saira-600.woff2").read_bytes()).decode("ascii")


# The dashboard's fonts, bundled with the report (SIL OFL, data/*-OFL.txt), so the PDF looks the
# same and the offline renderer fetches nothing: (family, weight, file).
# (family, weight, file, unicode-range). Digits 0-9 come from Plus Jakarta Sans under the body
# family's name (Atkinson's zero is slashed), after Atkinson's faces so they win, as on the page
# (web/src/styles/digits.css).
DIGITS = "U+0030-0039"
REPORT_FONTS: list[tuple[str, int, str, str | None]] = [
    ("Atkinson Hyperlegible Next", 400, "atkinson-400.woff2", None),
    ("Atkinson Hyperlegible Next", 600, "atkinson-600.woff2", None),
    ("Atkinson Hyperlegible Next", 700, "atkinson-700.woff2", None),
    ("Atkinson Hyperlegible Next", 400, "jakarta-400.woff2", DIGITS),
    ("Atkinson Hyperlegible Next", 600, "jakarta-600.woff2", DIGITS),
    ("Atkinson Hyperlegible Next", 700, "jakarta-700.woff2", DIGITS),
    ("Plus Jakarta Sans", 600, "jakarta-600.woff2", None),
    ("Plus Jakarta Sans", 700, "jakarta-700.woff2", None),
    ("JetBrains Mono", 400, "jetbrains-mono-400.woff2", None),
]


@lru_cache(maxsize=1)
def report_fonts() -> list[dict[str, object]]:
    return [
        {
            "family": family,
            "weight": weight,
            "range": unicode_range,
            "data": base64.b64encode((DATA / name).read_bytes()).decode("ascii"),
        }
        for family, weight, name, unicode_range in REPORT_FONTS
    ]


MAX_ROOM_LABEL = 80
# The app's priority icons (lucide, as web/src/components/icons.tsx uses them), in the priority
# colours from web/src/styles/tokens.css, always next to the word. Fixed markup, no user text.
_ICON_SHAPES = {
    "High": '<path d="M12 16h.01"/><path d="M12 8v4"/><path d="M15.312 2a2 2 0 0 1 1.414.586'
    "l4.688 4.688A2 2 0 0 1 22 8.688v6.624a2 2 0 0 1-.586 1.414l-4.688 4.688a2 2 0 0 1-1.414"
    ".586H8.688a2 2 0 0 1-1.414-.586l-4.688-4.688A2 2 0 0 1 2 15.312V8.688a2 2 0 0 1 .586"
    '-1.414l4.688-4.688A2 2 0 0 1 8.688 2z"/>',
    "Medium": '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/>'
    '<path d="M12 9v4"/><path d="M12 17h.01"/>',
    "Low": '<circle cx="12" cy="12" r="10"/><path d="M8 12h8"/>',
    "Info": '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
}
_ICON_COLOUR = {"High": "#b42318", "Medium": "#b54708", "Low": "#475467", "Info": "#3c5a72"}


def _icon(level: str) -> Markup:
    # Built only from the fixed constants above, never from scan data or user text.
    return Markup(  # noqa: S704
        f'<svg class="icon" aria-hidden="true" viewBox="0 0 24 24" width="12" height="12" '
        f'fill="none" stroke="{_ICON_COLOUR[level]}" stroke-width="2" stroke-linecap="round" '
        f'stroke-linejoin="round">{_ICON_SHAPES[level]}</svg>'
    )


SEVERITY_ICON = {level: _icon(level) for level in _ICON_SHAPES}
# The banner: the icon of the priority its status stands for.
STATUS_ICON = {
    "Needs attention": SEVERITY_ICON["High"],
    "Check these items": SEVERITY_ICON["Medium"],
}

LIMITATIONS = [
    "It can't see cameras that join a hidden or separate network as ordinary clients, or "
    "cameras that transmit nothing (memory-card only).",
    f"Device types, lookalike networks and tracker formats are {CLUES_NOT_PROOF}. "
    "Names, addresses and signal strength can be changed on purpose.",
    "The locator gives a rough area, not an exact spot.",
    "It can't identify who owns a cloud-linked account, and it can't confirm a device's exact "
    "firmware version without logging in, which it never does.",
    "Its weights and thresholds were tuned on a small set of devices. Results in crowded "
    "buildings will be less accurate.",
    "The timestamp proves when this report existed, not that its findings are correct.",
    "RoomCheck is a prototype, not a certified inspection, and this report is not legal advice.",
]


class ReportPrivacy(BaseModel):
    """What the user chose to include. Left out: replaced everywhere in the report's text."""

    network_name: bool = True  # the Wi-Fi network's name
    device_names: bool = True  # names devices call themselves, and the user's own names
    notes: bool = False  # task notes and "Help identify this" notes: off unless chosen


NETWORK_LEFT_OUT = "[network name left out]"
DEVICE_LEFT_OUT = "[device name left out]"


class _Scrub:
    """Replace the names the user chose to leave out, wherever they appear in the text."""

    def __init__(self, replacements: list[tuple[str, str]]) -> None:
        # Longest first, so a longer name isn't half-replaced by a shorter one inside it.
        pairs = sorted(
            {(a, b) for a, b in replacements if len(a.strip()) >= 2}, key=lambda p: -len(p[0])
        )
        self._pattern = (
            re.compile("|".join(re.escape(a) for a, _ in pairs), re.IGNORECASE) if pairs else None
        )
        self._to = {a.lower(): b for a, b in pairs}

    def __call__(self, text: str) -> str:
        if self._pattern is None or not text:
            return text
        return self._pattern.sub(lambda m: self._to[m.group(0).lower()], text)


def _scrubber(
    result: DiscoveryResult, handover: HandoverState | None, privacy: ReportPrivacy
) -> _Scrub:
    out: list[tuple[str, str]] = []
    if not privacy.network_name:
        names = {result.room_network} | {i.ssid for i in result.nearby_items if i.connected}
        out += [(n, NETWORK_LEFT_OUT) for n in names if n]
    if not privacy.device_names:
        out += [(h, DEVICE_LEFT_OUT) for d in result.devices for h in d.hostnames]
        out += [(n, DEVICE_LEFT_OUT) for n in (handover.names.values() if handover else [])]
    return _Scrub(out)


def _scrub_message(message: Any, scrub: _Scrub) -> Any:
    if message is None:
        return None
    return message.model_copy(update={"text": scrub(message.text)})


class PdfUnavailable(Exception):
    """The PDF renderer can't run on this computer."""


def default_report_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(base) / "RoomCheck" / "reports"


def _when(dt: datetime) -> str:
    local = dt.astimezone()
    offset = local.strftime("%z")
    return f"{local:%d %b %Y, %H:%M} (UTC{offset[:3]}:{offset[3:]})"


def _about_device(d: Device) -> str:
    kind = d.fingerprint.label if d.fingerprint else "Device"
    parts = [kind]
    if d.mac:
        parts.append(f"address {mask_mac(d.mac)}")
    elif d.vendor:
        parts.append(f"made by {d.vendor}")
    if d.ip:
        parts.append(f"at {d.ip}")
    return ", ".join(parts)


def _open_count(evidence: list[str]) -> int:
    """Networks listed by R-OPEN: one line each, plus a final "and N more"."""
    count = 0
    for line in evidence:
        more = re.fullmatch(r"and (\d+) more", line)
        count += int(more.group(1)) if more else 1
    return count


@dataclass
class FindingView:
    severity: str
    urgency: str  # the plain word for the priority, as on the dashboard
    icon: Markup
    title: str
    band: str
    about: str | None
    evidence: list[str]
    explanation: str
    why_it_matters: str
    explanation_label: str
    next_step: str
    guidance: list[str] = field(default_factory=list)
    observed: str = ""  # "What we observed": the rule's fixed sentence
    clues: list[str] = field(default_factory=list)  # the specific clues, shown instead of it
    could_mean: str = ""  # "What it could mean": the rule's fixed risk sentence
    answer: str | None = None  # the user's answer to "Do you recognise this device?"
    name: str | None = None  # the user's own short name for the device (plain text, escaped)
    note: str | None = None  # their short note from "Help identify this" (plain text, escaped)
    location: str | None = None  # a camera's "Where is it?", in plain words


ANSWER_TEXT = {
    "mine": "You said this is yours.",
    "landlord": "You said this is the host's. The host hasn't confirmed it yet.",
    "landlord_confirmed": "You said this is the host's, and the host confirmed it.",
    "unknown": "You said you don't know whose this is.",
}
WHO_TEXT = {
    "landlord_or_host": "Host",
    "booking_platform": "Booking platform",
    "you": "You",
}
STATUS_TEXT = {"todo": "To do", "asked": "Asked", "resolved": "Resolved"}
LOCATION_TEXT = {
    "inside": "You said it's inside the room or unit.",
    "outside": "You said it's outside or in a shared area.",
    "unknown": "You said you can't find it.",
}


def build_view(
    result: DiscoveryResult,
    explanations: Explanations,
    *,
    room_label: str | None,
    generated_at: datetime,
    handover: HandoverState | None = None,
    privacy: ReportPrivacy | None = None,
    compare_state: str | None = None,
    comparison: Comparison | None = None,
) -> dict[str, Any]:
    """compare_state and comparison: the move-in scan, for "What's changed since move-in?"
    (as GET /api/compare gives them). None: not known, e.g. from the command line."""
    privacy = privacy or ReportPrivacy()
    scrub = _scrubber(result, handover, privacy)
    devices = {d.id: d for d in result.devices}
    items = {i.ref: i for i in result.nearby_items}
    findings: dict[str, FindingView] = {}
    for f in result.findings:
        about = None
        if f.device_ref in devices:
            about = _about_device(devices[f.device_ref])
        elif f.nearby_ref in items:
            item = items[f.nearby_ref]
            bits = [item.label, item.maker and f"made by {item.maker}", item.band]
            about = ", ".join(b for b in bits if b) + f", signal {item.signal_dbm} dBm"
        if f.rule_id == "R-OPEN":
            # Neighbours' network names stay out of the report.
            evidence = [f"{_open_count(f.evidence)} open network(s) nearby; names left out"]
        else:
            evidence = [mask_text(e) for e in f.evidence]
        e = explanations.for_finding(f.id)
        subject = f.subject or ""
        answer: str | None = handover.answers.get(subject) if handover else None
        if answer == "landlord" and handover and handover.confirmed.get(subject):
            answer = "landlord_confirmed"
        steps = handover.adjusted.get(f.id) if handover else None
        findings[f.id] = FindingView(
            severity=f.severity,
            urgency=text(f"results.severity.{f.severity}"),
            icon=SEVERITY_ICON[f.severity],
            title=scrub(mask_text(f.title)),
            band=f.confidence_band,
            about=scrub(about) if about else None,
            evidence=[scrub(e) for e in evidence],
            observed=scrub(mask_text(f.observed)),
            clues=[scrub(mask_text(c)) for c in f.clues],
            could_mean=scrub(f.could_mean),
            explanation=scrub(e.explanation if e else f.standard_explanation),
            why_it_matters=scrub(e.why_it_matters if e else f.standard_why),
            explanation_label=e.label if e else "Standard explanation",
            next_step=steps.next_step if steps else f.next_step,
            guidance=steps.guidance if steps else f.guidance,
            answer=ANSWER_TEXT.get(answer or ""),
            name=(handover.names.get(subject) if handover and privacy.device_names else None),
            note=(handover.notes.get(subject) if handover and privacy.notes else None),
            location=LOCATION_TEXT.get(handover.locations.get(subject, "")) if handover else None,
        )
    summary = result.summary
    questions = question_statuses(result)
    physical = handover.physical if handover else PhysicalCheck()
    things = things_to_look_at(questions)
    checked, not_checked_count = check_counts(result)
    coverage_line = (
        text("results.coverageLine.partial", checked=checked, total=checked + not_checked_count)
        if not_checked_count
        else text("results.coverageLine.full", count=checked)
    )
    label = (room_label or "").strip()[:MAX_ROOM_LABEL] or None
    return {
        "room_label": label,
        "generated": _when(generated_at),
        "scan_started": _when(result.started_at),
        "scan_finished": _when(result.finished_at),
        # The permission choice from the Start screen, in the dashboard's words.
        "mode": text(f"compare.mode.{result.mode}"),
        "network": result.network.cidr if result.network else None,
        "room_network": result.room_network if privacy.network_name else None,
        "summary": summary,
        "status_icon": STATUS_ICON.get(summary.status if summary else "", SEVERITY_ICON["Info"]),
        # Counted as on Results (app/questions.py): things to look at, per question and in all.
        "things": things,
        "things_line": text("results.headline.things", count=things)
        if things
        else text("results.headline.none"),
        "per_question": " · ".join(
            text(f"results.questions.short.{q.id}", count=q.things) for q in questions
        ),
        "page_note": text("results.questions.pageNote"),
        "top_line": scrub(mask_text(top_line(result, questions) or "")),
        # Page 1: one paragraph for the host or platform, then the tasks.
        "for_host_title": text("reportPdf.forHostTitle"),
        "for_host": scrub(_for_host(result, handover, label, physical)),
        "tasks_title": text("reportPdf.tasksTitle"),
        "details_title": text("reportPdf.detailsTitle"),
        "stay_label": text("reportPdf.stay"),
        "stay": text(f"start.stay.{result.stay_type}") if result.stay_type else None,
        # A listening-only check: what it covered, and what permission would add.
        "listening": [text("results.listening.covered"), text("results.listening.adds")]
        if result.mode == "passive"
        else [],
        "listening_title": text("results.listening.title"),
        "physical_title": text("reportPdf.physicalTitle"),
        "physical": _physical(physical, privacy.notes, scrub),
        "questions": [
            {
                "title": text(f"results.questions.{q.id}"),
                "status": status_line(q),
                "partly": partly_line(q),
                "weak_camera": weak_camera_line(q),
                "cards": [
                    {
                        "findings": [findings[i] for i in c.finding_ids],
                        "also": [findings[i] for i in c.also],
                    }
                    for c in q.cards
                ],
                "also": [findings[i] for i in q.also],
            }
            for q in questions
        ],
        "changes": _changes(compare_state, comparison),
        "also_title": text("results.questions.alsoTitle"),
        "also_intro": text("results.questions.alsoIntro"),
        "findings": list(findings.values()),
        # Coverage and limits, as on Results: one row per check, and the same totals.
        "check_rows": table_rows(result),
        "checked": checked,
        "not_checked_count": not_checked_count,
        "coverage_line": coverage_line,
        "not_checked": summary.not_checked if summary else [],
        "cant_see": summary.cant_see if summary else [],
        # Layer 6: the message bundles the open handover tasks; without them, the draft.
        "landlord": _scrub_message(
            handover.message if handover else explanations.landlord_message, scrub
        ),
        "tasks": [
            {
                "title": t.title,
                "severity": t.severity,
                "urgency": text(f"results.severity.{t.severity}"),
                "who": WHO_TEXT[t.who],
                "status": STATUS_TEXT[t.status],
                "changed": _when(t.changed_at) if t.changed_at else "Not changed yet",
                "notes": scrub(t.notes) if privacy.notes else "",
                # Evidence, apart from the status: what the host said, and what RoomCheck saw.
                "labels": [
                    label
                    for label, on in (
                        (
                            "Host confirmed"
                            + (f" ({_when(t.host_confirmed_at)})" if t.host_confirmed_at else ""),
                            t.host_confirmed,
                        ),
                        (
                            "Observed by RoomCheck"
                            + (f" ({_when(t.observed_at)})" if t.observed_at else ""),
                            t.observed,
                        ),
                    )
                    if on
                ],
                # Every recheck, oldest first; the original finding above stays as it was.
                "rechecks": [f"Rechecked {_when(r.checked_at)}: {r.text}" for r in t.rechecks],
                "unobservable": t.recheck_offer == "unobservable",
            }
            for t in (handover.tasks if handover else [])
        ],
        "logo_path": MARK_PATH,
        "wordmark_font": wordmark_font(),
        "fonts": report_fonts(),
        "limitations": LIMITATIONS,
    }


def _changes(state: str | None, comparison: Comparison | None) -> dict[str, Any]:
    """'What's changed since move-in?', worded as on Results."""
    title = text("results.questions.changes")
    if comparison is not None:
        n = len(comparison.new) + len(comparison.gone) + len(comparison.changed)
        status = (
            text("results.questions.differences", count=n)
            if n
            else text("results.questions.noDifferences")
        )
        notes = [text("results.questions.savedOn", when=_when(comparison.baseline_saved_at))]
        if comparison.ran_differently:
            notes.append(text("compare.ranDifferently"))
        return {"title": title, "status": status, "notes": notes}
    unknown: str | None = {
        "unreadable": text("results.questions.changesUnreadable"),
        "no_check": text("results.questions.changesWaiting"),
        "none": text("results.questions.changesNone"),
    }.get(state or "", text("results.questions.changesUnknown"))
    return {"title": title, "status": unknown, "notes": []}


def _open_asks(result: DiscoveryResult, handover: HandoverState | None) -> int:
    """What the user is asking the host: open tasks for the host or platform, or (without the
    handover data, e.g. from the command line) the findings the host message asks about."""
    if handover is not None:
        return sum(
            1
            for t in handover.tasks
            if t.status != "resolved" and not t.host_confirmed and t.who != "you"
        )
    return len(message_findings(result.findings))


def _for_host(
    result: DiscoveryResult,
    handover: HandoverState | None,
    room: str | None,
    physical: PhysicalCheck,
) -> str:
    """One paragraph for the host or platform: what was checked, how, and what is asked."""
    date = f"{result.started_at.astimezone():%d %b %Y}"
    parts = [
        text("reportPdf.checkedRoom", date=date, room=room)
        if room
        else text("reportPdf.checked", date=date),
        text("reportPdf.howFull") if result.mode == "full" else text("reportPdf.howPassive"),
        text("reportPdf.physicalDone", date=f"{physical.done_at.astimezone():%d %b %Y}")
        if physical.done_at
        else text("reportPdf.physicalNot"),
    ]
    asks = _open_asks(result, handover)
    parts.append(text("reportPdf.ask", count=asks) if asks else text("reportPdf.askNone"))
    return " ".join(parts)


def _physical(physical: PhysicalCheck, notes: bool, scrub: _Scrub) -> dict[str, Any]:
    """'Physical check: done on <date>, items looked at, anything noted'. Notes are the user's
    own words, so they follow the report's notes choice."""
    total = len(PHYSICAL_ITEMS)
    looked = physical.looked
    if physical.done_at is not None:
        line = text(
            "reportPdf.physicalLine",
            date=f"{physical.done_at.astimezone():%d %b %Y}",
            looked=looked,
            total=total,
        )
    elif physical.items:
        line = text("reportPdf.physicalProgress", looked=looked, total=total)
    else:
        line = text("reportPdf.physicalNone")
    looked_at = [
        text(f"physical.items.{i}")
        for i in PHYSICAL_ITEMS
        if (item := physical.items.get(i)) is not None and item.looked  # type: ignore[call-overload]
    ]
    noted = [
        (i, item.note)
        for i in PHYSICAL_ITEMS
        if (item := physical.items.get(i)) is not None and item.note  # type: ignore[call-overload]
    ]
    return {
        "line": line,
        "looked_at": looked_at,
        "noted_title": text("reportPdf.physicalNoted"),
        "noted": [f"{text(f'physical.items.{i}')}: {scrub(n)}" for i, n in noted] if notes else [],
        "notes_left_out": text("reportPdf.physicalNotesLeftOut", count=len(noted))
        if noted and not notes
        else None,
    }


def render_html(view: dict[str, Any]) -> str:
    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(default=True, default_for_string=True),
    )
    return env.get_template("report.html.j2").render(**view)


PDF_STEP_TIMEOUT_MS = 20_000  # each browser step: starting, loading the page, printing


def render_pdf(html: str) -> bytes:
    """HTML to PDF with headless Chromium (Playwright). Raises PdfUnavailable if it can't run.

    The page is printed with JavaScript off, the browser offline and every request aborted,
    so only the local HTML is rendered and nothing is fetched or sent.
    (WeasyPrint was the first choice, but its GTK/Pango libraries don't load on Windows.)
    """
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as e:
        raise PdfUnavailable("playwright_missing") from e
    try:
        with sync_playwright() as p:
            # Bounded, so a stuck browser can't hold the report up: the page says it failed
            # and offers Try again.
            browser = p.chromium.launch(timeout=PDF_STEP_TIMEOUT_MS)
            try:
                context = browser.new_context(java_script_enabled=False, offline=True)
                context.set_default_timeout(PDF_STEP_TIMEOUT_MS)
                page = context.new_page()
                page.route("**/*", lambda route: route.abort())
                page.set_content(html, wait_until="load")
                return page.pdf(format="A4", print_background=True, prefer_css_page_size=True)
            finally:
                browser.close()
    except PlaywrightError as e:  # e.g. Chromium not downloaded yet
        raise PdfUnavailable("playwright_failed") from e


class ReportResult(BaseModel):
    files: tamper.ReportFiles
    generated_at: datetime
    explanations: Explanations


def make_report(
    result: DiscoveryResult,
    explanations: Explanations,
    *,
    room_label: str | None = None,
    out_dir: Path | None = None,
    online: bool = True,
    tsa_url: str = tamper.FREETSA_URL,
    render: Callable[[str], bytes] = render_pdf,
    request: Callable[[bytes, str], bytes] = tamper.request_token,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    handover: HandoverState | None = None,
    privacy: ReportPrivacy | None = None,
    compare_state: str | None = None,
    comparison: Comparison | None = None,
) -> ReportResult:
    generated = now()
    started = time.monotonic()
    html = render_html(
        build_view(
            result,
            explanations,
            room_label=room_label,
            generated_at=generated,
            handover=handover,
            privacy=privacy,
            compare_state=compare_state,
            comparison=comparison,
        )
    )
    pdf = render(html)
    rendered = time.monotonic()
    stem = f"roomcheck-report-{generated.astimezone():%Y%m%d-%H%M%S}"
    files = tamper.save(
        pdf, out_dir or default_report_dir(), stem, tsa_url=tsa_url, online=online, request=request
    )
    # One line per report, so a slow one shows which stage it was.
    log.info(
        "report: PDF in %.1f s, timestamp in %.1f s (%s)",
        rendered - started,
        time.monotonic() - rendered,
        "added" if files.tsr else "not requested" if not online else "unavailable",
    )
    return ReportResult(files=files, generated_at=generated, explanations=explanations)
