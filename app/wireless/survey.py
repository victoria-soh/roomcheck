"""Run the nearby check: Wi-Fi survey and Bluetooth scan side by side, each failing on its own.

Data handling (PLAN.md, "Trust, privacy and legal safeguards"): the full survey, with raw
BSSIDs and Bluetooth addresses, lives only in memory while the rules engine judges it.
`flagged_items` then keeps only items a rule flagged, referenced by salted hashes, plus
counts of everything else. The survey itself is never returned, printed or saved.
"""

from __future__ import annotations

import logging
import statistics
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.checks.models import WifiStatus
from app.discovery.merge import is_random_mac
from app.discovery.messages import message_for
from app.discovery.models import CheckStatus
from app.fingerprint.oui import lookup_vendor
from app.rules.models import Finding, RoomSummary
from app.wireless import ble, netsh, wlanapi
from app.wireless.ie import security_from_netsh
from app.wireless.models import (
    AccessPoint,
    BleAdvert,
    BleDevice,
    BssReading,
    HeardCounts,
    NearbyItem,
    NearbySurvey,
    RoomNetwork,
)
from app.wireless.privacy import SESSION_SALT, wifi_ref
from app.wireless.wlanapi import WirelessError

log = logging.getLogger(__name__)

MIN_SIGHTINGS = 2  # of 3 scans: filters out flicker

WifiMethod = Literal["wlanapi", "netsh"]
WifiFn = Callable[[], tuple[WifiMethod, list[list[BssReading]]]]
BleFn = Callable[[], list[list[BleAdvert]]]

LABELS = {
    "nearby_wifi": "Looking at nearby Wi-Fi",
    "lookalike": "Checking for copies of your Wi-Fi network",
    "wps": "Checking whether your Wi-Fi router offers WPS",
    "bluetooth": "Listening for nearby Bluetooth devices and trackers",
    "on_network": "Checking devices on the network you joined",
}


def _status(name: str, status: str, code: str | None = None, found: int = 0) -> CheckStatus:
    return CheckStatus(
        name=name,
        label=LABELS[name],
        status=status,  # type: ignore[arg-type]
        reason=message_for(code) if code else None,
        found=found,
    )


def collect_wifi() -> tuple[WifiMethod, list[list[BssReading]]]:
    """Three scans through the WLAN API, or through netsh if the API can't be used."""
    try:
        return "wlanapi", wlanapi.survey_rounds()
    except WirelessError as e:
        if e.code != "wlanapi_unavailable":
            raise
        log.info("WLAN API unavailable; falling back to netsh")
    return "netsh", netsh.survey_rounds()


def collect_ble() -> list[list[BleAdvert]]:
    return ble.scan_rounds()


def aggregate_wifi(
    rounds: list[list[BssReading]],
    salt: bytes = SESSION_SALT,
    min_sightings: int = MIN_SIGHTINGS,
) -> list[AccessPoint]:
    """Access points heard in at least `min_sightings` scans.

    With the WLAN API a scan only counts if Windows heard the access point again (its host
    timestamp moved), so an entry cached from an earlier scan doesn't count twice.
    """
    state: dict[str, tuple[BssReading, list[int], int | None]] = {}
    for readings in rounds:
        seen: set[str] = set()
        for b in readings:
            if b.bssid in seen:
                continue
            seen.add(b.bssid)
            latest, rssi, ts = state.get(b.bssid, (b, [], None))
            fresh = b.host_timestamp is None or b.host_timestamp != ts
            if fresh:
                rssi = [*rssi, b.rssi_dbm]
            state[b.bssid] = (b, rssi, b.host_timestamp)
    out = []
    for bssid, (b, rssi, _) in state.items():
        if len(rssi) < min_sightings:
            continue
        random = is_random_mac(bssid)
        out.append(
            AccessPoint(
                ref=wifi_ref(bssid, salt),
                bssid=bssid,
                ssid=b.ssid,
                rssi_dbm=int(statistics.median(rssi)),
                frequency_mhz=b.frequency_mhz,
                channel=b.channel,
                security=b.security,
                wps=b.wps,
                wps_known=b.wps_known,
                vendor=None if random else lookup_vendor(bssid),
                bssid_random=random,
                sightings=len(rssi),
            )
        )
    return sorted(out, key=lambda ap: -ap.rssi_dbm)


def room_network(connected: WifiStatus | None, typed: str | None = None) -> RoomNetwork | None:
    """The network treated as genuine: the one you're connected to, or a name you typed."""
    typed = (typed or "").strip() or None
    if connected is not None and connected.ssid and (typed is None or typed == connected.ssid):
        return RoomNetwork(
            ssid=connected.ssid,
            bssid=connected.bssid,
            security=security_from_netsh(connected.authentication, connected.cipher),
            source="connected",
        )
    if typed:
        return RoomNetwork(ssid=typed, source="typed")
    return None


def collect_nearby(
    *,
    wifi_fn: WifiFn = collect_wifi,
    ble_fn: BleFn = collect_ble,
    salt: bytes = SESSION_SALT,
) -> tuple[NearbySurvey, list[CheckStatus], list[str]]:
    """Run the Wi-Fi survey and the Bluetooth scan at the same time (about 30 s)."""
    survey = NearbySurvey()
    checks: list[CheckStatus] = []
    messages: list[str] = []
    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="nearby") as pool:
        wifi_future = pool.submit(wifi_fn)
        ble_future = pool.submit(ble_fn)

        try:
            method, rounds = wifi_future.result()
            aps = aggregate_wifi(rounds, salt)
            if not any(rounds):
                raise WirelessError("location_off")  # the list came back empty: PLAN.md
            survey.access_points = aps
            survey.wifi_method = method
            checks.append(_status("nearby_wifi", "ran", found=len(aps)))
        except WirelessError as e:
            checks.append(_status("nearby_wifi", "failed", e.code))
            messages.append(message_for(e.code))
        except Exception:
            log.exception("nearby Wi-Fi survey failed")
            checks.append(_status("nearby_wifi", "failed", "internal"))

        try:
            ble_rounds = ble_future.result()
            survey.ble_devices = ble.aggregate(ble_rounds, salt)
            survey.ble_rounds = len(ble_rounds)
            checks.append(_status("bluetooth", "ran", found=len(survey.ble_devices)))
        except WirelessError as e:
            checks.append(_status("bluetooth", "failed", e.code))
            messages.append(message_for(e.code))
        except Exception:
            log.exception("Bluetooth scan failed")
            checks.append(_status("bluetooth", "failed", "internal"))
    return survey, checks, messages


def room_checks(survey: NearbySurvey) -> list[CheckStatus]:
    """Status of the checks that compare nearby networks with the room network."""
    if survey.access_points is None:
        return [_status(n, "skipped", "nearby_wifi_failed") for n in ("lookalike", "wps")]
    if survey.room is None:
        return [_status(n, "skipped", "no_room_network") for n in ("lookalike", "wps")]
    ssid = survey.room.ssid
    mine = [ap for ap in survey.access_points if ap.ssid == ssid]
    out = [_status("lookalike", "ran", found=len(mine))]
    if survey.wifi_method != "wlanapi" or not any(ap.wps_known for ap in mine):
        out.append(_status("wps", "skipped", "wps_unknown"))
    else:
        out.append(_status("wps", "ran", found=len(mine)))
    return out


# --- what is kept ---------------------------------------------------------------------------


def _wifi_item(ap: AccessPoint, rule_ids: list[str]) -> NearbyItem:
    if ap.ssid:
        label = f'Wi-Fi network "{ap.ssid}"'
    else:
        label = "Hidden Wi-Fi network"
    return NearbyItem(
        ref=ap.ref,
        kind="wifi",
        label=label,
        ssid=ap.ssid,
        maker=None if ap.bssid_random else ap.vendor,
        security=ap.security.label,
        band=ap.band,
        signal_dbm=ap.rssi_dbm,
        rule_ids=rule_ids,
    )


def _ble_item(d: BleDevice, rule_ids: list[str]) -> NearbyItem:
    return NearbyItem(
        ref=d.ref,
        kind="bluetooth",
        label=d.cls.label,
        signal_dbm=d.max_rssi,
        rule_ids=rule_ids,
    )


def flagged_items(survey: NearbySurvey, findings: list[Finding]) -> list[NearbyItem]:
    """Only items a rule flagged. Everything else is dropped here."""
    rules_by_ref: dict[str, list[str]] = {}
    for f in findings:
        if f.nearby_ref:
            rules_by_ref.setdefault(f.nearby_ref, [])
            if f.rule_id not in rules_by_ref[f.nearby_ref]:
                rules_by_ref[f.nearby_ref].append(f.rule_id)
    items: list[NearbyItem] = []
    for ap in survey.access_points or []:
        if ap.ref in rules_by_ref:
            items.append(_wifi_item(ap, rules_by_ref[ap.ref]))
    for d in survey.ble_devices or []:
        if d.ref in rules_by_ref:
            items.append(_ble_item(d, rules_by_ref[d.ref]))
    return items


def heard_counts(survey: NearbySurvey) -> HeardCounts:
    by_cat = Counter(ble.CATEGORY_LABELS[d.cls.category] for d in survey.ble_devices or [])
    return HeardCounts(
        wifi_access_points=len(survey.access_points or []),
        bluetooth_devices=len(survey.ble_devices or []),
        bluetooth_by_category=dict(by_cat.most_common()),
    )


class NearbyResult(BaseModel):
    """A nearby-only check, as the API and CLI return it: flagged items only."""

    started_at: datetime
    finished_at: datetime
    room_network: str | None
    wifi_method: WifiMethod | None
    checks: list[CheckStatus]
    messages: list[str] = Field(default_factory=list)
    items: list[NearbyItem] = Field(default_factory=list)
    heard: HeardCounts = Field(default_factory=HeardCounts)
    findings: list[Finding] = Field(default_factory=list)
    summary: RoomSummary | None = None


def run_nearby_check(
    *,
    typed_room: str | None = None,
    connected_fn: Callable[[], WifiStatus | None] | None = None,
    wifi_fn: WifiFn = collect_wifi,
    ble_fn: BleFn = collect_ble,
    salt: bytes = SESSION_SALT,
) -> NearbyResult:
    """Layer 4 on its own ("run only the nearby check"), judged by the same rules engine."""
    from app.checks.wifi import connected_wifi
    from app.rules.engine import RoomFacts, evaluate, summarise

    started = datetime.now(UTC)
    survey, checks, messages = collect_nearby(wifi_fn=wifi_fn, ble_fn=ble_fn, salt=salt)
    survey.room = room_network((connected_fn or connected_wifi)(), typed_room)
    checks += room_checks(survey)
    checks.append(_status("on_network", "skipped", "nearby_only"))
    findings = evaluate(RoomFacts(devices=[], network=None, checks=checks, nearby=survey))
    result = NearbyResult(
        started_at=started,
        finished_at=datetime.now(UTC),
        room_network=survey.room.ssid if survey.room else None,
        wifi_method=survey.wifi_method,
        checks=checks,
        messages=messages,
        items=flagged_items(survey, findings),
        heard=heard_counts(survey),
        findings=findings,
        summary=summarise(findings, checks),
    )
    del survey  # raw addresses go no further than this function
    return result
