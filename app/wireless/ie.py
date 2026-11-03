"""Parse 802.11 information elements (IEs) from an access point's beacon or probe response.

Pure functions over untrusted bytes: every length is checked, and truncated or malformed
elements are skipped or reported as unreadable rather than guessed at.

- RSN (element ID 48): WPA2 / WPA3 and the ciphers, from IEEE 802.11-2020 section 9.4.2.24.
- Microsoft vendor element (ID 221, OUI 00:50:F2): type 1 is the original WPA, type 4 is
  Wi-Fi Protected Setup (WPS), whose attributes are big-endian TLVs from the Wi-Fi Alliance
  WSC 2.0 specification.
- SSID (ID 0): a blank or all-zero name means a hidden network.
"""

from __future__ import annotations

import struct
from collections.abc import Iterator
from dataclasses import dataclass, field

from app.wireless.models import WifiSecurity, WpsInfo

IE_SSID = 0
IE_RSN = 48
IE_VENDOR = 221

IEEE_OUI = b"\x00\x0f\xac"
MS_OUI = b"\x00\x50\xf2"
MS_TYPE_WPA = 1
MS_TYPE_WPS = 4

CAPABILITY_PRIVACY = 0x0010  # in the beacon's capability field: some encryption is on

CIPHERS = {
    1: "WEP-40",
    2: "TKIP",
    4: "CCMP",
    5: "WEP-104",
    6: "BIP-CMAC-128",
    8: "GCMP",
    9: "GCMP-256",
    10: "CCMP-256",
}
AKMS = {
    1: "802.1X",
    2: "PSK",
    3: "FT-802.1X",
    4: "FT-PSK",
    5: "802.1X-SHA256",
    6: "PSK-SHA256",
    8: "SAE",
    9: "FT-SAE",
    11: "802.1X-SuiteB",
    12: "802.1X-SuiteB-192",
    13: "FT-802.1X-SHA384",
    18: "OWE",
    24: "SAE-EXT-KEY",
    25: "FT-SAE-EXT-KEY",
}
MODERN_CIPHERS = {"CCMP", "GCMP", "GCMP-256", "CCMP-256"}

# WPS attribute types
WPS_STATE = 0x1044
WPS_AP_SETUP_LOCKED = 0x1057
WPS_CONFIG_METHODS = 0x1008
WPS_SELECTED_REGISTRAR_CONFIG_METHODS = 0x1053
WPS_DEVICE_NAME = 0x1011
WPS_MANUFACTURER = 0x1021
WPS_MODEL_NAME = 0x1023
WPS_PRIMARY_DEVICE_TYPE = 0x1054
WPS_PIN_METHODS = 0x0004 | 0x0008 | 0x0100  # label, display, keypad
WPS_CATEGORY_CAMERA = 4

MAX_TEXT = 64


class IEError(ValueError):
    """An element is malformed or truncated."""


@dataclass
class CipherSuites:
    """The parsed body of an RSN element or a WPA vendor element."""

    version: int
    group: str
    pairwise: list[str] = field(default_factory=list)
    akms: list[str] = field(default_factory=list)
    capabilities: int = 0


def iter_ies(data: bytes) -> Iterator[tuple[int, bytes]]:
    """(element ID, body) pairs. Stops at a truncated element instead of reading past it."""
    i = 0
    while i + 2 <= len(data):
        eid, length = data[i], data[i + 1]
        body = data[i + 2 : i + 2 + length]
        if len(body) < length:
            return
        yield eid, body
        i += 2 + length


def ies_complete(data: bytes) -> bool:
    """True if the elements fill the buffer exactly, with nothing cut off."""
    i = 0
    while i + 2 <= len(data):
        i += 2 + data[i + 1]
    return i == len(data)


def _suite(raw: bytes, table: dict[int, str], oui: bytes) -> str:
    if raw[:3] == oui:
        return table.get(raw[3], f"unknown-{raw[3]}")
    return f"vendor-{raw.hex()}"


def _suite_list(body: bytes, pos: int, table: dict[int, str], oui: bytes) -> tuple[list[str], int]:
    if len(body) < pos + 2:
        raise IEError("suite count truncated")
    (count,) = struct.unpack_from("<H", body, pos)
    pos += 2
    if len(body) < pos + 4 * count:
        raise IEError("suite list truncated")
    suites = [_suite(body[pos + 4 * k : pos + 4 * k + 4], table, oui) for k in range(count)]
    return suites, pos + 4 * count


def parse_cipher_suites(body: bytes, oui: bytes = IEEE_OUI) -> CipherSuites:
    """RSN element body (or a WPA vendor body after OUI and type, with oui=MS_OUI).

    Trailing fields are optional; when absent the standard's defaults apply (CCMP, 802.1X).
    """
    if len(body) < 2:
        raise IEError("no version")
    (version,) = struct.unpack_from("<H", body, 0)
    if version != 1:
        raise IEError(f"unknown version {version}")
    out = CipherSuites(version=version, group="CCMP", pairwise=["CCMP"], akms=["802.1X"])
    pos = 2
    if len(body) == pos:
        return out
    if len(body) < pos + 4:
        raise IEError("group cipher truncated")
    out.group = _suite(body[pos : pos + 4], CIPHERS, oui)
    pos += 4
    if len(body) == pos:
        return out
    out.pairwise, pos = _suite_list(body, pos, CIPHERS, oui)
    if len(body) == pos:
        return out
    out.akms, pos = _suite_list(body, pos, AKMS, oui)
    if len(body) >= pos + 2:
        (out.capabilities,) = struct.unpack_from("<H", body, pos)
    return out


def _text(raw: bytes) -> str | None:
    s = raw.decode("utf-8", errors="replace").replace("\x00", "")
    s = "".join(c for c in s if c.isprintable()).strip()[:MAX_TEXT]
    return s or None


def parse_wps(body: bytes) -> WpsInfo:
    """WPS vendor body after OUI and type: big-endian (type, length, value) attributes.

    A truncated attribute ends parsing; whatever came before it is kept.
    """
    info = WpsInfo()
    pos = 0
    while pos + 4 <= len(body):
        attr, length = struct.unpack_from(">HH", body, pos)
        value = body[pos + 4 : pos + 4 + length]
        if len(value) < length:
            break
        pos += 4 + length
        if attr == WPS_STATE and length == 1:
            info.state = {1: "not_configured", 2: "configured"}.get(value[0])  # type: ignore[assignment]
        elif attr == WPS_AP_SETUP_LOCKED and length == 1:
            info.ap_setup_locked = value[0] == 1
        elif attr in (WPS_CONFIG_METHODS, WPS_SELECTED_REGISTRAR_CONFIG_METHODS) and length == 2:
            (methods,) = struct.unpack(">H", value)
            info.config_methods = (info.config_methods or 0) | methods
        elif attr == WPS_DEVICE_NAME:
            info.device_name = _text(value)
        elif attr == WPS_MANUFACTURER:
            info.manufacturer = _text(value)
        elif attr == WPS_MODEL_NAME:
            info.model_name = _text(value)
        elif attr == WPS_PRIMARY_DEVICE_TYPE and length == 8:
            (info.device_category,) = struct.unpack_from(">H", value, 0)
    return info


def wps_offers_pin(wps: WpsInfo) -> bool:
    return wps.config_methods is not None and bool(wps.config_methods & WPS_PIN_METHODS)


def ssid_from_bytes(raw: bytes) -> str | None:
    """The network name, or None if hidden (blank or all zero bytes)."""
    if not raw or not raw.strip(b"\x00"):
        return None
    s = raw.decode("utf-8", errors="replace")
    return "".join(c if c.isprintable() else "�" for c in s)


# --- security --------------------------------------------------------------------------------

_LABELS = {
    "open": "Open (no password)",
    "owe": "Enhanced Open (encrypted, but no password)",
    "wep": "WEP (outdated)",
    "wpa": "WPA (outdated)",
    "wpa2": "WPA2",
    "wpa3": "WPA3",
    "wpa2/wpa3": "WPA2/WPA3",
    "unknown": "Unknown security",
}
_TIERS = {"open": 0, "owe": 1, "wep": 1, "wpa": 2, "wpa2": 3, "wpa3": 3, "wpa2/wpa3": 3}


def make_security(
    kind: str, *, enterprise: bool = False, pairwise: list[str] | None = None
) -> WifiSecurity:
    pairwise = pairwise or []
    tier = _TIERS.get(kind)
    label = _LABELS[kind]
    if enterprise and kind in ("wpa", "wpa2", "wpa3", "wpa2/wpa3"):
        label += " Enterprise"
    if tier == 3 and pairwise and not (set(pairwise) & MODERN_CIPHERS):
        tier = 2
        label += " with outdated TKIP encryption"
    return WifiSecurity(
        kind=kind,  # type: ignore[arg-type]
        enterprise=enterprise,
        pairwise=pairwise,
        tier=tier,
        label=label,
    )


def security_from_suites(
    rsn: CipherSuites | None, wpa: CipherSuites | None, privacy: bool
) -> WifiSecurity:
    if rsn is not None:
        akms = set(rsn.akms)
        sae = any("SAE" in a for a in akms)
        psk = any("PSK" in a for a in akms)
        dot1x = any("802.1X" in a for a in akms)
        if akms == {"OWE"}:
            return make_security("owe", pairwise=rsn.pairwise)
        if sae and psk:
            kind = "wpa2/wpa3"
        elif sae or any("SuiteB" in a for a in akms):
            kind = "wpa3"
        elif psk or dot1x:
            kind = "wpa2"
        else:
            return make_security("unknown")
        return make_security(kind, enterprise=dot1x and not (sae or psk), pairwise=rsn.pairwise)
    if wpa is not None:
        return make_security("wpa", enterprise="802.1X" in wpa.akms, pairwise=wpa.pairwise)
    return make_security("wep" if privacy else "open")


def security_from_netsh(authentication: str, cipher: str) -> WifiSecurity:
    """From netsh's English labels, e.g. ("WPA2-Personal", "CCMP"). Unknown values stay unknown."""
    a = authentication.lower()
    c = cipher.lower()
    pairwise = ["TKIP"] if c == "tkip" else ["CCMP"] if c in ("ccmp", "gcmp", "gcmp-256") else []
    enterprise = "enterprise" in a or "802.1x" in a
    if "owe" in a:
        return make_security("owe")
    if a == "open":
        return make_security("wep" if c == "wep" else "open" if c in ("none", "") else "unknown")
    if a == "shared":
        return make_security("wep")
    if "wpa3" in a and "wpa2" in a:
        kind = "wpa2/wpa3"
    elif "wpa3" in a:
        kind = "wpa3"
    elif "wpa2" in a:
        kind = "wpa2"
    elif "wpa" in a:
        kind = "wpa"
    else:
        return make_security("unknown")
    return make_security(kind, enterprise=enterprise, pairwise=pairwise)


@dataclass
class ParsedIes:
    ssid: str | None
    ssid_present: bool
    security: WifiSecurity
    wps: WpsInfo | None
    unreadable: list[str] = field(default_factory=list)


def parse_beacon_ies(data: bytes, capability: int) -> ParsedIes:
    """Everything RoomCheck reads from one access point's information elements."""
    ssid: str | None = None
    ssid_present = False
    rsn: CipherSuites | None = None
    wpa: CipherSuites | None = None
    wps: WpsInfo | None = None
    unreadable: list[str] = []
    for eid, body in iter_ies(data):
        if eid == IE_SSID and not ssid_present:
            ssid_present = True
            ssid = ssid_from_bytes(body)
        elif eid == IE_RSN and rsn is None:
            try:
                rsn = parse_cipher_suites(body)
            except IEError:
                unreadable.append("rsn")
        elif eid == IE_VENDOR and len(body) >= 4 and body[:3] == MS_OUI:
            if body[3] == MS_TYPE_WPA and wpa is None:
                try:
                    wpa = parse_cipher_suites(body[4:], MS_OUI)
                except IEError:
                    unreadable.append("wpa")
            elif body[3] == MS_TYPE_WPS and wps is None:
                wps = parse_wps(body[4:])
    privacy = bool(capability & CAPABILITY_PRIVACY)
    if "rsn" in unreadable and rsn is None:
        security = make_security("unknown")  # never guess "open" from a broken RSN element
    elif privacy and rsn is None and wpa is None and (not data or not ies_complete(data)):
        # Encrypted, but the elements are missing or cut off: it could be WPA2 just as well
        # as WEP, so don't guess (a wrong "WEP" would look like a weaker copy).
        security = make_security("unknown")
        unreadable.append("truncated")
    else:
        security = security_from_suites(rsn, wpa, privacy)
    return ParsedIes(ssid, ssid_present, security, wps, unreadable)
