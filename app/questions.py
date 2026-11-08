"""Results and the report, organised by the renter's questions.

  Is anything watching?                    camera-like devices, camera hotspots, trackers
  Can someone else control things here?    locks, cloud-linked devices, Telnet, known issues
  Can you trust this Wi-Fi?                encryption, DNS, ARP, DHCP, lookalikes, WPS, UPnP, …
  What's changed since move-in?            from Compare (not rules), added by each page

Each finding's question comes from its rule (rules.yaml). This module groups them into cards and
sets each question's status for the PDF; web/src/results/questions.ts does the same for Results
and the report summary, with the same rule. tests/unit/test_consistency.py and
Consistency.test.tsx hold both to the same numbers on the demo check, and
tests/unit/test_questions.py keeps the page's list of checks per question equal to rules.yaml.

One counting rule: a "thing to look at" is a card with a High, Medium or Low finding. Info
findings never count. They sit inside the card for the same device or signal ("Also found"),
or, when there's no such card, are listed at the end of their question.

The wording is in web/src/strings/en.json (results.questions), read here for the PDF, so the
page and the report say exactly the same.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.coverage import short_phrase
from app.discovery.models import Device, DiscoveryResult
from app.rules.engine import SEVERITY_ORDER, load_rules
from app.rules.models import QUESTIONS, Finding, QuestionCard, QuestionStatus

STRINGS_FILE = Path(__file__).resolve().parents[1] / "web" / "src" / "strings" / "en.json"
BAND_ORDER = {"Likely": 0, "Possible": 1, "Unclear": 2}


def _rank(f: Finding) -> tuple[int, int]:
    return SEVERITY_ORDER[f.severity], BAND_ORDER[f.confidence_band]


def _subject(f: Finding) -> tuple[str, str]:
    """What a card is about: a device, a nearby signal, or (network findings) the finding."""
    if f.scope == "device" and f.device_ref:
        return "device", f.device_ref
    if f.scope == "nearby" and f.nearby_ref:
        return "nearby", f.nearby_ref
    return "network", f.id


def _card_id(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in text)


def camera_threshold() -> float:
    """R-CAM's own flag threshold (rules.yaml): a camera score below it isn't flagged."""
    rule = next(r for r in load_rules().rules if r.id == "R-CAM")
    return float(rule.when["type_score"]["min"])


def camera_score(device: Device) -> float:
    fp = device.fingerprint
    if fp is None:
        return 0.0
    if fp.type == "camera":
        return fp.confidence
    return next((t.score for t in fp.other_types + fp.weak_types if t.type == "camera"), 0.0)


def weak_camera_devices(result: DiscoveryResult) -> list[str]:
    """Devices that gave a camera clue too weak to flag: above zero, below the threshold."""
    flagged = {f.device_ref for f in result.findings if f.rule_id in ("R-CAM", "R-NEW-CAMERA")}
    limit = camera_threshold()
    return [d.id for d in result.devices if d.id not in flagged and 0 < camera_score(d) < limit]


def question_statuses(result: DiscoveryResult) -> list[QuestionStatus]:
    findings = sorted(result.findings, key=_rank)  # stable: the engine's order within a rank
    spec = load_rules().questions
    cards: dict[str, dict[tuple[str, str], QuestionCard]] = {q: {} for q in QUESTIONS}
    for f in findings:
        if f.severity == "Info":
            continue
        kind, ref = _subject(f)
        group = cards[f.question]
        card = group.get((kind, ref))
        if card is None:
            card = QuestionCard(
                key=_card_id(f"q-{f.question}-{kind}-{ref}"),
                kind=kind,  # type: ignore[arg-type]
                device_ref=f.device_ref if kind == "device" else None,
                nearby_ref=f.nearby_ref if kind == "nearby" else None,
                finding_ids=[],
            )
            group[(kind, ref)] = card
        card.finding_ids.append(f.id)

    # Info: inside a card for the same device or signal (its own question's first), else
    # listed at the end of its question.
    orphans: dict[str, list[str]] = {q: [] for q in QUESTIONS}
    for f in findings:
        if f.severity != "Info":
            continue
        subject = _subject(f)
        order = [f.question, *(q for q in QUESTIONS if q != f.question)]
        host = next((cards[q][subject] for q in order if subject in cards[q]), None)
        if host is not None and subject[0] != "network":
            host.also.append(f.id)
        else:
            orphans[f.question].append(f.id)

    by_name = {c.name: c for c in result.checks}
    out: list[QuestionStatus] = []
    for q in QUESTIONS:
        relevant = [by_name[n] for n in spec[q].checks if n in by_name]
        missed = [c for c in relevant if c.status != "ran"]
        reason = None
        if missed:
            first = next((c for c in missed if c.status == "skipped"), missed[0])
            text = first.short_reason or (short_phrase(first.reason) if first.reason else None)
            reason = text or "it wasn't checked this time"
        things = len(cards[q])
        if things:
            state = "look"
        elif orphans[q]:
            state = "info"
        elif relevant and len(missed) < len(relevant):
            state = "not_detected"
        else:
            state = "not_checked"
            reason = reason or "it wasn't checked this time"
        out.append(
            QuestionStatus(
                id=q,
                things=things,
                state=state,  # type: ignore[arg-type]
                not_checked_reason=reason,
                cards=list(cards[q].values()),
                also=orphans[q],
                weak_camera=weak_camera_devices(result) if q == "watching" else [],
            )
        )
    return out


def things_to_look_at(questions: list[QuestionStatus]) -> int:
    """The headline's one number: cards across every question."""
    return sum(q.things for q in questions)


# --- the wording, from the page's strings -----------------------------------------------------


@lru_cache(maxsize=1)
def strings() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(STRINGS_FILE.read_text(encoding="utf-8"))
    return data


def _node(key: str) -> tuple[Any, str]:
    node: Any = strings()
    *path, last = key.split(".")
    for part in path:
        node = node[part]
    return node, last


def has_text(key: str, count: int | None = None) -> bool:
    node, last = _node(key)
    if count is not None:
        return f"{last}_one" in node or last in node
    return last in node


def text(key: str, count: int | None = None, **values: object) -> str:
    """An en.json string by its dotted key, with i18next's _zero/_one/_other plurals and {{x}}."""
    node, last = _node(key)
    if count is not None and count == 0 and f"{last}_zero" in node:
        last = f"{last}_zero"
    elif count is not None and f"{last}_one" in node:
        last = f"{last}_one" if count == 1 else f"{last}_other"
    template: str = node[last]
    for name, value in {"count": count, **values}.items():
        template = template.replace("{{" + name + "}}", str(value))
    return template


def status_line(q: QuestionStatus) -> str:
    """'1 thing to look at', 'Not detected by the checks that ran', 'Not checked: <reason>'."""
    base = "results.questions.status"
    if q.state == "look":
        return text(f"{base}.look", count=q.things)
    if q.state == "info":
        return text(f"{base}.info", count=len(q.also))
    if q.state == "not_detected":
        return text(f"{base}.notDetected")
    return text(f"{base}.notChecked", reason=q.not_checked_reason)


def weak_camera_line(q: QuestionStatus) -> str | None:
    """'1 device gave a weak camera clue. Not enough to flag it, but worth a look during the
    physical check.'"""
    if not q.weak_camera:
        return None
    return text("results.questions.weakCamera", count=len(q.weak_camera))


def partly_line(q: QuestionStatus) -> str | None:
    """The second line when some of the question's checks didn't run: 'Not checked: <reason>'."""
    if q.state == "not_checked" or not q.not_checked_reason:
        return None
    return text("results.questions.status.notChecked", reason=q.not_checked_reason)


def lower_first(sentence: str) -> str:
    """'It offers…' -> 'it offers…' after a colon; 'ONVIF…' and other acronyms stay."""
    if len(sentence) > 1 and sentence[0].isupper() and sentence[1].islower():
        return sentence[0].lower() + sentence[1:]
    return sentence


def top_line(result: DiscoveryResult, questions: list[QuestionStatus]) -> str | None:
    """The summary sentence: the top thing to look at and its plainest clue, e.g. "Likely
    camera: it offers a live video stream, the kind security cameras use." The rule's observed
    sentence when there are no device clues. None when there's nothing to look at."""
    by_id = {f.id: f for f in result.findings}
    cards = [c for q in questions for c in q.cards]
    if not cards:
        return None
    top = by_id[min(cards, key=lambda c: _rank(by_id[c.finding_ids[0]])).finding_ids[0]]
    clue = top.lead_clue or (top.clues[0] if top.clues else "") or top.observed
    clue = clue or top.standard_explanation
    return text("results.headline.topLine", title=top.title, clue=lower_first(clue))
