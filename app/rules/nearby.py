"""Layer 4 rule predicates over one nearby survey. Pure functions, no I/O.

Each returns a list of Matches; a Match with `nearby_ref` points at one access point or
Bluetooth device, so the locator can find it. Evidence never contains a BSSID or Bluetooth
address.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from typing import Any

from app.rules.hotspots import load_hotspots
from app.rules.models import Match
from app.wireless.ie import wps_offers_pin
from app.wireless.models import AccessPoint, BleDevice, NearbySurvey
from app.wireless.radio import strength

NearbyPredicate = Callable[[NearbySurvey, dict[str, Any]], list[Match]]

# Words that don't tell two makers apart: places and legal suffixes in IEEE registrations.
_SKIP_WORDS = {
    "the",
    "shenzhen",
    "hangzhou",
    "zhejiang",
    "guangdong",
    "guangzhou",
    "beijing",
    "shanghai",
    "dongguan",
    "xiamen",
    "suzhou",
    "fujian",
    "jiangsu",
    "tianjin",
    "chengdu",
    "wuhan",
    "nanjing",
    "qingdao",
    "ningbo",
    "zhuhai",
    "taiwan",
}


def company_key(vendor: str) -> str | None:
    """One key per company, so a maker's several IEEE registrations count as the same maker:
    "TP-LINK TECHNOLOGIES CO.,LTD." and "TP-Link Systems Inc" both become "tplink"."""
    words = re.findall(r"[a-z0-9]+", vendor.lower().replace("-", ""))
    words = [w for w in words if w not in _SKIP_WORDS]
    return words[0] if words else None


def _maker_key(ap: AccessPoint) -> str | None:
    if ap.bssid_random or not ap.vendor:
        return None  # randomised or unregistered BSSID: maker unknown, never a match
    return company_key(ap.vendor)


def _maker(ap: AccessPoint) -> str:
    if ap.bssid_random:
        return "Maker: unknown (private address, common for extra networks and phone hotspots)"
    return f"Maker: {ap.vendor}" if ap.vendor else "Maker: unknown"


def _signal(ap: AccessPoint) -> str:
    where = ", ".join(x for x in (ap.band, f"channel {ap.channel}" if ap.channel else None) if x)
    text = f"Signal {ap.rssi_dbm} dBm ({strength(ap.rssi_dbm)})"
    return f"{text}, {where}" if where else text


def _name(ap: AccessPoint) -> str:
    return f'"{ap.ssid}"' if ap.ssid else "a hidden network"


def _room_aps(s: NearbySurvey) -> list[AccessPoint]:
    if s.room is None or s.access_points is None:
        return []
    return [ap for ap in s.access_points if ap.ssid == s.room.ssid]


def _connected(s: NearbySurvey) -> AccessPoint | None:
    if s.room is None or s.room.bssid is None:
        return None
    return next((ap for ap in _room_aps(s) if ap.bssid == s.room.bssid), None)


def reference_security(s: NearbySurvey) -> tuple[int, str] | None:
    """The room network's security tier, and how we know it.

    The access point you're connected to wins; then the connection details Windows reports;
    for a typed-in name with no connection, the strongest access point with that name.
    """
    if s.room is None:
        return None
    name = s.room.ssid
    c = _connected(s)
    if c is not None and c.security.tier is not None:
        return c.security.tier, f'Your connection to "{name}" uses {c.security.label}'
    if s.room.security is not None and s.room.security.tier is not None:
        return s.room.security.tier, f'Your connection to "{name}" uses {s.room.security.label}'
    known = [ap.security for ap in _room_aps(s) if ap.security.tier is not None]
    if not known:
        return None
    best = max(known, key=lambda sec: sec.tier or 0)
    return best.tier or 0, f'The strongest access point named "{name}" uses {best.label}'


def weaker_twin(s: NearbySurvey, args: dict[str, Any]) -> list[Match]:
    ref = reference_security(s)
    if ref is None:
        return []
    tier, how = ref
    room_bssid = s.room.bssid if s.room else None
    out = []
    for ap in _room_aps(s):
        if ap.bssid == room_bssid or ap.security.tier is None or ap.security.tier >= tier:
            continue
        out.append(
            Match(
                band="Likely",
                evidence=[
                    f"Another access point is also called {_name(ap)}, "
                    f"but uses {ap.security.label}",
                    how,
                    _signal(ap),
                    _maker(ap),
                ],
                nearby_ref=ap.ref,
            )
        )
    return out


def twin_other_maker(s: NearbySurvey, args: dict[str, Any]) -> list[Match]:
    """Same name and security, but a different maker with a strong signal. Mesh-aware:

    - A maker's several registrations count as one company (company_key).
    - Randomised BSSIDs (common for mesh nodes' extra networks) are "maker unknown": they
      never set the reference and are never flagged.
    - The reference maker is the access point you're connected to; failing that, a strict
      majority of at least two access points with known makers. With no clear reference,
      nothing fires.
    """
    ref = reference_security(s)
    if ref is None or s.room is None:
        return []
    tier, _ = ref
    same = [ap for ap in _room_aps(s) if ap.security.tier == tier]
    connected = _connected(s)
    if connected is not None and _maker_key(connected):
        reference = {_maker_key(connected)}
        reference_text = f"The access point you're connected to is made by {connected.vendor}"
    else:
        counts = Counter(k for k in map(_maker_key, same) if k)
        if not counts:
            return []
        ((top, n),) = counts.most_common(1)
        if n < 2 or n * 2 <= sum(counts.values()):
            return []
        reference = {top}
        makers = sorted({ap.vendor or "" for ap in same if _maker_key(ap) == top})
        reference_text = f"{n} other access points with this name are made by {makers[0]}"
    min_rssi = int(args.get("min_rssi", -60))
    out = []
    for ap in same:
        key = _maker_key(ap)
        if ap is connected or key is None or key in reference or ap.rssi_dbm < min_rssi:
            continue
        out.append(
            Match(
                band="Possible",
                evidence=[
                    f"Another access point called {_name(ap)} uses the same security "
                    f"({ap.security.label}) but is made by {ap.vendor}",
                    reference_text,
                    _signal(ap),
                ],
                nearby_ref=ap.ref,
            )
        )
    return out


_WPA3_KINDS = {"wpa3", "wpa2/wpa3"}


def _wpa3_reference(s: NearbySurvey) -> str | None:
    """How we know the room network offers WPA3, or None if it doesn't (or we can't tell).

    The access point you're connected to wins (its beacon shows mixed mode even when Windows
    joined it over WPA2). Otherwise, access points with this name and a registered maker that
    offer WPA3; then the connection details Windows reports.
    """
    if s.room is None:
        return None
    name = s.room.ssid
    c = _connected(s)
    if c is not None and c.security.kind != "unknown":
        if c.security.kind not in _WPA3_KINDS:
            return None
        return f"The access point you're connected to offers {c.security.label}"
    registered = [ap for ap in _room_aps(s) if _maker_key(ap) and ap.security.kind in _WPA3_KINDS]
    if registered:
        vendors = sorted({ap.vendor or "" for ap in registered})
        return (
            f'{len(registered)} access point(s) named "{name}" made by {vendors[0]} offer '
            f"{registered[0].security.label}"
        )
    if s.room.security is not None and s.room.security.kind in _WPA3_KINDS:
        return f'Your connection to "{name}" uses {s.room.security.label}'
    return None


def downgrade_twin(s: NearbySurvey, args: dict[str, Any]) -> list[Match]:
    """A WPA2-only copy of a network that offers WPA3, with no known maker and a strong signal.

    This is the shape of the WPA3 downgrade attack in Dragonblood (Vanhoef and Ronen, "Dragonblood:
    Analyzing the Dragonfly Handshake of WPA3 and EAP-pwd", IEEE S&P 2020): a rogue WPA2-only
    access point with the same name lures devices that would otherwise use WPA3.

    Mesh-aware: WPA2-only nodes from the room network's own maker stay silent, and copies from
    a different known maker are left to R-TWIN-VENDOR, so nothing is reported twice. Phone
    hotspots and many extenders also look like this, hence "possible".
    """
    how = _wpa3_reference(s)
    if how is None or s.room is None:
        return []
    min_rssi = int(args.get("min_rssi", -60))
    out = []
    for ap in _room_aps(s):
        sec = ap.security
        if ap.bssid == s.room.bssid or sec.kind != "wpa2" or sec.enterprise or sec.tier != 3:
            continue
        if _maker_key(ap) is not None or ap.rssi_dbm < min_rssi:
            continue  # known maker: the room's own node, or R-TWIN-VENDOR's case
        out.append(
            Match(
                band="Possible",
                evidence=[
                    f"Another access point called {_name(ap)} offers only {sec.label}, "
                    "without WPA3",
                    how,
                    _signal(ap),
                    _maker(ap),
                ],
                nearby_ref=ap.ref,
            )
        )
    return out


def camera_hotspot(s: NearbySurvey, args: dict[str, Any]) -> list[Match]:
    hotspots = load_hotspots()
    room_ssid = s.room.ssid if s.room else None
    out = []
    for ap in s.access_points or []:
        if ap.ssid is not None and ap.ssid == room_ssid:
            continue
        evidence = []
        if ap.ssid:
            pattern = hotspots.match_name(ap.ssid)
            if pattern is not None:
                evidence.append(f'The network name "{ap.ssid}" matches {pattern.label}')
        if _maker_key(ap) and ap.vendor and hotspots.camera_vendor_match(ap.vendor):
            evidence.append(
                f"Its maker, from its address, is {ap.vendor}, a company known for cameras"
            )
        if ap.wps is not None and ap.wps.device_category == 4:
            evidence.append("Its setup information (WPS) describes it as a camera")
        if not evidence:
            continue
        if ap.ssid is None:
            evidence.append("It hides its network name")
        evidence += [_signal(ap)]
        out.append(Match(band="Possible", evidence=evidence, nearby_ref=ap.ref))
    return out


def hidden_strong(s: NearbySurvey, args: dict[str, Any]) -> list[Match]:
    min_rssi = int(args.get("min_rssi", -60))
    return [
        Match(
            band="Likely",
            evidence=[
                "A network that hides its name",
                _signal(ap),
                f"Security: {ap.security.label}",
                _maker(ap),
            ],
            nearby_ref=ap.ref,
        )
        for ap in s.access_points or []
        if ap.hidden and ap.rssi_dbm > min_rssi
    ]


def open_nearby(s: NearbySurvey, args: dict[str, Any]) -> list[Match]:
    room_ssid = s.room.ssid if s.room else None
    best: dict[str, AccessPoint] = {}
    for ap in s.access_points or []:
        if ap.ssid is None or ap.ssid == room_ssid or ap.security.kind != "open":
            continue
        if ap.ssid not in best or ap.rssi_dbm > best[ap.ssid].rssi_dbm:
            best[ap.ssid] = ap
    if not best:
        return []
    shown = sorted(best.values(), key=lambda ap: -ap.rssi_dbm)
    limit = int(args.get("max_listed", 10))
    evidence = [f'"{ap.ssid}" has no password (signal {ap.rssi_dbm} dBm)' for ap in shown[:limit]]
    if len(shown) > limit:
        evidence.append(f"and {len(shown) - limit} more")
    return [Match(band="Likely", evidence=evidence)]


def wps_enabled(s: NearbySurvey, args: dict[str, Any]) -> list[Match]:
    ref = reference_security(s)
    tier = ref[0] if ref else None
    aps = [
        ap
        for ap in _room_aps(s)
        if ap.wps is not None
        and (tier is None or ap.security.tier is None or ap.security.tier >= tier)
    ]
    if not aps:
        return []
    evidence = []
    for ap in sorted(aps, key=lambda a: -a.rssi_dbm):
        wps = ap.wps
        assert wps is not None
        where = ", ".join(x for x in (ap.vendor or "maker unknown", ap.band) if x)
        text = f"An access point called {_name(ap)} ({where}) advertises WPS"
        if wps.state == "not_configured":
            text += ", still in its factory setup state"
        evidence.append(text)
        if wps_offers_pin(wps):
            evidence.append("It lists PIN entry among its setup methods")
        if wps.ap_setup_locked:
            evidence.append("It says PIN entry is locked for now, which can reset after a restart")
    # Point at the access point you're connected to when it's one of them, else the strongest.
    room_bssid = s.room.bssid if s.room else None
    chosen = next((a for a in aps if a.bssid == room_bssid), max(aps, key=lambda a: a.rssi_dbm))
    return [Match(band="Likely", evidence=evidence, nearby_ref=chosen.ref)]


def _strong_rounds(d: BleDevice, min_rssi: int) -> set[int]:
    return {r for r, rssi in d.round_rssi.items() if rssi >= min_rssi}


def _tracker_match(devices: list[BleDevice], rounds: set[int], total: int, rotated: bool) -> Match:
    d = max(devices, key=lambda x: x.max_rssi)
    separated = all(x.cls.separated for x in devices)
    evidence = [
        f"Its Bluetooth signal matches the format of a {d.cls.label} (signature from AirGuard)"
    ]
    if separated:
        evidence.append(
            "It is in 'away from its owner' mode: its owner's phone hasn't been near it"
        )
    else:
        evidence.append("This tracker type doesn't show whether its owner is nearby")
    strongest = max(x.max_rssi for x in devices)
    evidence.append(
        f"Heard with a strong signal in {len(rounds)} of {total} scans (strongest {strongest} dBm)"
    )
    if rotated:
        evidence.append("Its Bluetooth address changed during the scan, as trackers' addresses do")
    evidence.append("If it belongs to you or someone you're with, this is expected")
    return Match(
        band="Likely" if separated else "Possible",
        evidence=evidence,
        variant="separated" if separated else "unknown",
        nearby_ref=d.ref,
    )


def tracker_repeated(s: NearbySurvey, args: dict[str, Any]) -> list[Match]:
    """A tracker that isn't near its owner, heard strongly in repeated scans, never once.

    Trackers whose format says the owner is near (separated is False) are left alone. Since
    tracker addresses rotate, a kind of tracker whose address changed between scans also
    counts, as long as each scan heard exactly one strong tracker of that kind.
    """
    if not s.ble_devices:
        return []
    min_rounds = int(args.get("min_rounds", 2))
    min_rssi = int(args.get("min_rssi", -70))
    candidates = [
        d for d in s.ble_devices if d.cls.category == "tracker" and d.cls.separated is not False
    ]
    out = []
    leftovers: dict[str, list[BleDevice]] = {}
    for d in candidates:
        rounds = _strong_rounds(d, min_rssi)
        if len(rounds) >= min_rounds:
            out.append(_tracker_match([d], rounds, s.ble_rounds, rotated=False))
        elif rounds:
            leftovers.setdefault(d.cls.kind, []).append(d)
    for devices in leftovers.values():
        per_round = Counter(r for d in devices for r in _strong_rounds(d, min_rssi))
        if len(per_round) >= min_rounds and all(n == 1 for n in per_round.values()):
            out.append(_tracker_match(devices, set(per_round), s.ble_rounds, rotated=True))
    return out


NEARBY_PREDICATES: dict[str, NearbyPredicate] = {
    "weaker_twin": weaker_twin,
    "twin_other_maker": twin_other_maker,
    "downgrade_twin": downgrade_twin,
    "camera_hotspot": camera_hotspot,
    "hidden_strong": hidden_strong,
    "open_nearby": open_nearby,
    "wps_enabled": wps_enabled,
    "tracker_repeated": tracker_repeated,
}
