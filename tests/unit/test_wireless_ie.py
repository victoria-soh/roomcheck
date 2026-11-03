"""Layer 4 information-element parsers (on byte fixtures), security mapping, and the WLAN API
structures and buffer decoding (no DLL needed)."""

import ctypes
import re
from pathlib import Path

import pytest

from app.wireless import ie, wlanapi
from app.wireless.ie import IEError, parse_beacon_ies, parse_cipher_suites, security_from_netsh

IES = Path(__file__).resolve().parents[1] / "fixtures" / "wireless" / "ies"
PRIVACY = ie.CAPABILITY_PRIVACY


def hexfile(name: str) -> bytes:
    text = (IES / name).read_text(encoding="utf-8")
    return bytes.fromhex(re.sub(r"#.*", "", text))


def parsed(name: str, capability: int = PRIVACY) -> ie.ParsedIes:
    return parse_beacon_ies(hexfile(name), capability)


# --- RSN, WPA and security -----------------------------------------------------------------


def test_wpa2_psk_ccmp_and_wps():
    p = parsed("wpa2_psk_wps.hex")
    assert p.ssid == "HomeNet"
    assert (p.security.kind, p.security.tier, p.security.label) == ("wpa2", 3, "WPA2")
    assert p.security.pairwise == ["CCMP"]
    assert p.wps is not None and p.wps.state == "configured"
    assert p.unreadable == []


def test_rsn_fields_are_read_in_order():
    body = dict(ie.iter_ies(hexfile("wpa3_transition.hex")))[ie.IE_RSN]
    rsn = parse_cipher_suites(body)
    assert (rsn.version, rsn.group, rsn.pairwise) == (1, "CCMP", ["CCMP"])
    assert rsn.akms == ["PSK", "SAE"]
    assert rsn.capabilities == 0x0080


@pytest.mark.parametrize(
    ("name", "kind", "tier", "label"),
    [
        ("wpa3_transition.hex", "wpa2/wpa3", 3, "WPA2/WPA3"),
        ("wpa3_sae.hex", "wpa3", 3, "WPA3"),
        ("owe.hex", "owe", 1, "Enhanced Open (encrypted, but no password)"),
        ("enterprise.hex", "wpa2", 3, "WPA2 Enterprise"),
        ("wpa2_tkip_only.hex", "wpa2", 2, "WPA2 with outdated TKIP encryption"),
        ("wpa1_tkip.hex", "wpa", 2, "WPA (outdated)"),
    ],
)
def test_security_kinds(name, kind, tier, label):
    s = parsed(name).security
    assert (s.kind, s.tier, s.label) == (kind, tier, label)


def test_open_needs_no_privacy_bit_and_no_rsn():
    p = parsed("open_no_security.hex", capability=0)
    assert p.ssid == "Free Wi-Fi"
    assert (p.security.kind, p.security.tier) == ("open", 0)


def test_privacy_bit_without_rsn_or_wpa_is_wep():
    p = parse_beacon_ies(hexfile("open_no_security.hex"), PRIVACY)
    assert (p.security.kind, p.security.tier) == ("wep", 1)


def test_rsn_absent_defaults_follow_the_standard():
    # A bare version field: group and pairwise default to CCMP, AKM to 802.1X.
    rsn = parse_cipher_suites(b"\x01\x00")
    assert (rsn.group, rsn.pairwise, rsn.akms) == ("CCMP", ["CCMP"], ["802.1X"])


# --- hidden networks -----------------------------------------------------------------------


@pytest.mark.parametrize("name", ["hidden_blank.hex", "hidden_zeros.hex"])
def test_hidden_ssids(name):
    p = parsed(name)
    assert p.ssid_present and p.ssid is None
    assert p.security.kind == "wpa2"


def test_ssid_bytes_are_decoded_without_control_characters():
    assert ie.ssid_from_bytes(b"Cafe\x07Net") == "Cafe�Net"
    assert ie.ssid_from_bytes(b"") is None
    assert ie.ssid_from_bytes(b"\x00\x00") is None


# --- WPS -----------------------------------------------------------------------------------


def test_camera_wps_attributes():
    w = parsed("camera_wps_locked.hex").wps
    assert w is not None
    assert (w.state, w.ap_setup_locked, w.manufacturer) == ("configured", True, "Acme")
    assert w.device_category == ie.WPS_CATEGORY_CAMERA
    assert w.config_methods == 0x008C
    assert ie.wps_offers_pin(w)


def test_truncated_wps_attribute_keeps_what_came_before():
    w = parsed("wps_truncated_attr.hex").wps
    assert w is not None
    assert w.state == "configured"
    assert w.manufacturer is None


def test_push_button_only_wps_does_not_offer_pin():
    w = ie.parse_wps(bytes.fromhex("1008 0002 0080"))
    assert not ie.wps_offers_pin(w)


def test_wps_text_is_sanitised_and_capped():
    w = ie.parse_wps(
        bytes.fromhex("1011 0006") + b"Cam\x00\x1b!" + bytes.fromhex("1021 0050") + b"A" * 80
    )
    assert w.device_name == "Cam!"
    assert w.manufacturer == "A" * ie.MAX_TEXT


# --- malformed input -----------------------------------------------------------------------


def test_truncated_suite_list_is_unknown_not_open():
    p = parsed("rsn_truncated_suites.hex")
    assert "rsn" in p.unreadable
    assert (p.security.kind, p.security.tier) == ("unknown", None)


def test_element_cut_off_with_privacy_bit_is_unknown_not_wep():
    data = hexfile("element_cut_off.hex")
    assert not ie.ies_complete(data)
    assert [eid for eid, _ in ie.iter_ies(data)] == [ie.IE_SSID]  # stops before the cut
    p = parse_beacon_ies(data, PRIVACY)
    assert (p.security.kind, p.security.tier) == ("unknown", None)


def test_no_ies_at_all_with_privacy_bit_is_unknown():
    assert parse_beacon_ies(b"", PRIVACY).security.kind == "unknown"
    assert parse_beacon_ies(b"", 0).security.kind == "open"


def test_unknown_rsn_version_is_rejected():
    with pytest.raises(IEError):
        parse_cipher_suites(b"\x02\x00")
    assert parsed("rsn_version_2.hex").security.kind == "unknown"


@pytest.mark.parametrize("junk", [b"\x30", b"\x30\xff", b"\xdd\x03\x00\x50", bytes(range(256))])
def test_junk_never_raises(junk):
    parse_beacon_ies(junk, PRIVACY)


# --- netsh security strings ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("auth", "cipher", "kind", "tier"),
    [
        ("Open", "None", "open", 0),
        ("Open", "WEP", "wep", 1),
        ("Shared", "WEP", "wep", 1),
        ("WPA-Personal", "TKIP", "wpa", 2),
        ("WPA2-Personal", "CCMP", "wpa2", 3),
        ("WPA2-Personal", "TKIP", "wpa2", 2),
        ("WPA2-Enterprise", "CCMP", "wpa2", 3),
        ("WPA3-Personal", "GCMP-256", "wpa3", 3),
        ("WPA2-Personal/WPA3-Personal", "CCMP", "wpa2/wpa3", 3),
        ("OWE", "CCMP", "owe", 1),
        ("Ouvert", "Aucun", "unknown", None),
    ],
)
def test_security_from_netsh(auth, cipher, kind, tier):
    s = security_from_netsh(auth, cipher)
    assert (s.kind, s.tier) == (kind, tier)


# --- WLAN API structures and buffer decoding -----------------------------------------------


def test_structure_sizes_match_wlanapi_h():
    assert ctypes.sizeof(wlanapi.GUID) == 16
    assert ctypes.sizeof(wlanapi.DOT11_SSID) == 36
    assert ctypes.sizeof(wlanapi.WLAN_INTERFACE_INFO) == 532
    assert ctypes.sizeof(wlanapi.WLAN_BSS_ENTRY) == 360
    assert wlanapi.WLAN_BSS_ENTRY.lRssi.offset == 56
    assert wlanapi.WLAN_BSS_ENTRY.ulChCenterFrequency.offset == 92
    assert wlanapi.WLAN_BSS_LIST.wlanBssEntries.offset == 8


def build_bss_list(entries: list[tuple[str, bytes, int, int, bytes]]) -> ctypes.Array:
    """A WLAN_BSS_LIST in memory, as wlanapi.dll lays it out: entries, then each one's IEs."""
    esize = ctypes.sizeof(wlanapi.WLAN_BSS_ENTRY)
    first = wlanapi.WLAN_BSS_LIST.wlanBssEntries.offset
    ie_start = first + esize * len(entries)
    total = ie_start + sum(len(e[4]) for e in entries)
    buf = (ctypes.c_uint8 * total)()
    lst = wlanapi.WLAN_BSS_LIST.from_buffer(buf)
    lst.dwTotalSize, lst.dwNumberOfItems = total, len(entries)
    pos = ie_start
    for i, (bssid, ssid, rssi, khz, ies) in enumerate(entries):
        offset = first + i * esize
        e = wlanapi.WLAN_BSS_ENTRY.from_buffer(buf, offset)
        e.dot11Ssid.uSSIDLength = len(ssid)
        e.dot11Ssid.ucSSID[: len(ssid)] = list(ssid)
        e.dot11Bssid[:] = list(bytes.fromhex(bssid.replace(":", "")))
        e.lRssi, e.ulChCenterFrequency = rssi, khz
        e.usCapabilityInformation = PRIVACY
        e.ullHostTimestamp = 1000 + i
        e.ulIeOffset, e.ulIeSize = pos - offset, len(ies)
        ctypes.memmove(ctypes.addressof(buf) + pos, ies, len(ies))
        pos += len(ies)
    return buf


def test_decode_bss_list_reads_entries_and_ies():
    buf = build_bss_list(
        [
            ("cc:ba:bd:ac:94:d9", b"HomeNet", -40, 5220000, hexfile("wpa2_psk_wps.hex")),
            ("9a:3b:4c:00:11:22", b"", -55, 2437000, hexfile("hidden_blank.hex")),
        ]
    )
    raw = wlanapi.decode_bss_list(ctypes.addressof(buf))
    assert [r.bssid for r in raw] == ["cc:ba:bd:ac:94:d9", "9a:3b:4c:00:11:22"]
    readings = [wlanapi.reading_from_raw(r) for r in raw]
    home, hidden = readings
    assert (home.ssid, home.rssi_dbm, home.frequency_mhz, home.channel) == (
        "HomeNet",
        -40,
        5220,
        44,
    )
    assert home.security.kind == "wpa2" and home.wps is not None
    assert (hidden.ssid, hidden.channel) == (None, 6)


def test_decode_bss_list_never_reads_past_total_size():
    buf = build_bss_list(
        [("cc:ba:bd:ac:94:d9", b"HomeNet", -40, 5220000, hexfile("wpa2_psk_wps.hex"))]
    )
    lst = wlanapi.WLAN_BSS_LIST.from_buffer(buf)
    lst.dwNumberOfItems = 50  # lies about the count
    e = wlanapi.WLAN_BSS_ENTRY.from_buffer(buf, wlanapi.WLAN_BSS_LIST.wlanBssEntries.offset)
    e.ulIeSize = 10_000  # and about the IE size
    raw = wlanapi.decode_bss_list(ctypes.addressof(buf))
    assert len(raw) == 1
    assert raw[0].ies == b""  # out-of-bounds IEs are dropped, not read
