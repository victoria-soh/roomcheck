"""Recheck a handover task after the host says it's fixed: run only the check that can see it,
judge the fresh data with the same rules, and say plainly what changed.

Only some fixes can be observed. WPS off, a lookalike or camera-setup network gone (the Wi-Fi
survey); Telnet closed, the router's UPnP controls off, a camera-like device gone (device
discovery and identification). Telnet and UPnP need active checks, so they're only rechecked
after a check the user gave permission for. Some fixes can never be observed (who uses a smart
lock, who holds a cloud account, a firmware version): those rely on the host's confirmation.
No new detection: the same collectors and the same rules engine as a full check.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from app.baseline.compare import assign_subjects
from app.baseline.keys import device_subject, nearby_key
from app.checks.models import NetworkFacts
from app.checks.wifi import connected_wifi
from app.discovery.models import CheckStatus, DiscoveryResult
from app.discovery.runner import default_collectors, run_discovery
from app.fingerprint.pipeline import fingerprint_devices
from app.handover.models import Recheck, RecheckKind, RecheckOutcome, Task
from app.rules.engine import RoomFacts, evaluate
from app.scanner import Scanner
from app.wireless import survey as nearby
from app.wireless.models import NearbySurvey

# Rule -> the check that can observe its fix.
OBSERVABLE: dict[str, RecheckKind] = {
    "R-WPS": "nearby_wifi",
    "R-TWIN": "nearby_wifi",
    "R-TWIN-VENDOR": "nearby_wifi",
    "R-TWIN-DOWNGRADE": "nearby_wifi",
    "R-CAMHOT": "nearby_wifi",
    "R-TELNET": "devices",
    "R-UPNP": "devices",
    "R-CAM": "devices",
    "R-NEW-CAMERA": "devices",
}
ACTIVE = {"R-TELNET", "R-UPNP"}  # need the active checks, so a consented check
# Fixes RoomCheck can never see: smart-lock users and codes, cloud accounts, firmware.
UNOBSERVABLE = {"R-LOCK", "R-CLOUD", "R-CVE"}
RECHECK_LISTEN_SECONDS = 30

# The words for each outcome, by rule. Fixed text, never AI.
TEXT: dict[str, dict[str, str]] = {
    "R-WPS": {
        "fixed": "WPS is now off on that router.",
        "still_there": "WPS is still on.",
        "not_heard": "That router wasn't heard this time, so WPS wasn't checked.",
    },
    "nearby_network": {
        "gone": "That network wasn't heard this time.",
        "still_there": "That network is still there.",
    },
    "R-TELNET": {
        "fixed": "Telnet is now closed on that device.",
        "still_there": "Telnet is still open on that device.",
        "not_seen": "The device wasn't seen this time, so Telnet wasn't checked.",
        "no_ports": "The service check couldn't run this time, so Telnet wasn't checked.",
    },
    "R-UPNP": {
        "fixed": "The router no longer offers internet port controls (UPnP).",
        "still_there": "The router still offers internet port controls (UPnP).",
        "no_ssdp": "The smart-device search couldn't run this time, so UPnP wasn't checked.",
    },
    "camera": {
        "gone": "The device wasn't seen this time. A quiet device can be missed, so look in the "
        "room too.",
        "still_there": "The device is still on this network.",
    },
}
NO_ROOM = "RoomCheck doesn't know your Wi-Fi network's name this time, so this wasn't checked."
NEEDS_PERMISSION = (
    "This recheck asks devices to answer, so it needs a check you have permission for. "
    "Start a full check, then recheck."
)


@dataclass
class Collectors:
    """The checks a recheck can run; tests pass fakes."""

    # The Wi-Fi survey, with the room's network set (from the connection or the typed name).
    wifi: Callable[[str | None], tuple[NearbySurvey, list[CheckStatus], list[str]]]
    devices: Callable[[bool], DiscoveryResult]


def real_collectors(scanner: Scanner | None) -> Collectors:
    def wifi(typed: str | None) -> tuple[NearbySurvey, list[CheckStatus], list[str]]:
        # The Wi-Fi survey only: no Bluetooth, which none of these fixes needs.
        survey, checks, messages = nearby.collect_nearby(ble_fn=lambda: [])
        survey.room = nearby.room_network(connected_wifi(), typed)
        return survey, checks, messages

    def devices(consent: bool) -> DiscoveryResult:
        fresh = run_discovery(
            "full" if consent else "passive",
            default_collectors(scanner, RECHECK_LISTEN_SECONDS),
        )
        if fresh.network is not None:
            checks, _ = fingerprint_devices(fresh.devices, consent=consent, scanner=scanner)
            fresh.checks += checks
        return fresh

    return Collectors(wifi=wifi, devices=devices)


def kind_for(rule_id: str) -> RecheckKind | None:
    return OBSERVABLE.get(rule_id)


def _done(outcome: RecheckOutcome, text: str, now: datetime | None) -> Recheck:
    return Recheck(outcome=outcome, text=text, checked_at=now or datetime.now(UTC))


def _ran(checks: list[CheckStatus], name: str) -> bool:
    return any(c.name == name and c.status == "ran" for c in checks)


def recheck(
    task: Task,
    result: DiscoveryResult,
    *,
    salt: bytes,
    collectors: Collectors,
    now: datetime | None = None,
) -> Recheck:
    """Run the one relevant check for this task and compare with the same rule."""
    kind = kind_for(task.rule_id)
    if kind is None:
        raise ValueError(f"{task.rule_id} can't be rechecked")
    consent = result.mode == "full"
    if task.rule_id in ACTIVE and not consent:
        return _done("needs_permission", NEEDS_PERMISSION, now)
    if kind == "nearby_wifi":
        return _recheck_wifi(task, result, salt, collectors, now)
    return _recheck_devices(task, result, salt, collectors, consent, now)


def _recheck_wifi(
    task: Task, result: DiscoveryResult, salt: bytes, c: Collectors, now: datetime | None
) -> Recheck:
    survey, checks, messages = c.wifi(result.room_network)
    if survey.access_points is None:  # the survey itself failed, e.g. Location off
        reason = messages[0] if messages else "The Wi-Fi survey couldn't run this time."
        return _done("couldnt_check", reason, now)
    if survey.room is None:  # without it, the WPS and lookalike rules can't be judged
        return _done("couldnt_check", NO_ROOM, now)
    findings = evaluate(RoomFacts(devices=[], network=None, net=NetworkFacts(), nearby=survey))
    fresh = DiscoveryResult(
        started_at=result.started_at,
        finished_at=result.finished_at,
        mode=result.mode,
        network=None,
        devices=[],
        checks=checks,
        findings=findings,
        nearby_items=nearby.flagged_items(survey, findings, salt),
    )
    assign_subjects(fresh, salt)
    heard = {nearby_key("wifi", ap.bssid, salt) for ap in survey.access_points}
    still = any(f.rule_id == task.rule_id and f.subject == task.subject for f in fresh.findings)
    if task.rule_id == "R-WPS":
        words = TEXT["R-WPS"]
        if task.subject not in heard:
            return _done("couldnt_check", words["not_heard"], now)
        if still:
            return _done("still_there", words["still_there"], now)
        return _done("fixed", words["fixed"], now)
    words = TEXT["nearby_network"]
    if still or task.subject in heard:
        return _done("still_there", words["still_there"], now)
    return _done("gone", words["gone"], now)


def _recheck_devices(
    task: Task,
    result: DiscoveryResult,
    salt: bytes,
    c: Collectors,
    consent: bool,
    now: datetime | None,
) -> Recheck:
    fresh = c.devices(consent)
    if fresh.network is None:
        return _done("couldnt_check", "Not connected to a network, so this wasn't checked.", now)
    fresh.findings = evaluate(
        RoomFacts(
            devices=fresh.devices, network=fresh.network, net=NetworkFacts(), checks=fresh.checks
        )
    )
    assign_subjects(fresh, salt)
    still = any(f.rule_id == task.rule_id and f.subject == task.subject for f in fresh.findings)
    seen = {device_subject(d, salt) for d in fresh.devices}
    if task.rule_id == "R-UPNP":
        words = TEXT["R-UPNP"]
        if still:
            return _done("still_there", words["still_there"], now)
        if not _ran(fresh.checks, "ssdp"):
            return _done("couldnt_check", words["no_ssdp"], now)
        return _done("fixed", words["fixed"], now)
    if task.rule_id == "R-TELNET":
        words = TEXT["R-TELNET"]
        if still:
            return _done("still_there", words["still_there"], now)
        if task.subject not in seen:
            return _done("couldnt_check", words["not_seen"], now)
        if not _ran(fresh.checks, "port_check"):
            return _done("couldnt_check", words["no_ports"], now)
        return _done("fixed", words["fixed"], now)
    words = TEXT["camera"]  # R-CAM, R-NEW-CAMERA: is the device still here?
    if task.subject in seen:
        return _done("still_there", words["still_there"], now)
    return _done("gone", words["gone"], now)
