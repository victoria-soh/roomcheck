"""Layer 4 collection: Bluetooth classification, Wi-Fi aggregation (flicker filter), the netsh
fallback, the WLAN API error mapping, and each failure message."""

from pathlib import Path

import pytest
from bleak.exc import BleakBluetoothNotAvailableError, BleakBluetoothNotAvailableReason, BleakError

from app.checks.models import WifiStatus
from app.checks.wifi import first_connected
from app.discovery.messages import message_for
from app.wireless import ble, netsh, survey, wlanapi
from app.wireless.ie import make_security
from app.wireless.models import BleAdvert, BssReading
from app.wireless.survey import aggregate_wifi, collect_nearby, room_network, run_nearby_check
from app.wireless.wlanapi import WirelessError

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
WIRELESS = FIXTURES / "wireless"
SALT = b"test-salt"
WPA2 = make_security("wpa2", pairwise=["CCMP"])
OPEN = make_security("open")
CONNECTED = WifiStatus(
    interface="Wi-Fi",
    ssid="HomeNet",
    bssid="cc:ba:bd:ac:94:d9",
    authentication="WPA2-Personal",
    cipher="CCMP",
)

PLAN_LOCATION = (
    "Windows needs Location turned on to list nearby Wi-Fi. Open Settings, then "
    "Privacy & security, then Location."
)
PLAN_WIFI_OFF = "Turn on Wi-Fi to check nearby networks."
PLAN_BLUETOOTH_OFF = "Turn on Bluetooth to check for nearby trackers."
PLAN_UNSTABLE = "The signal is jumping around. Move more slowly and hold the laptop still."


def read(name):
    return (WIRELESS / name).read_text(encoding="utf-8")


def reading(bssid, ssid="HomeNet", rssi=-50, ts=None, sec=WPA2):
    return BssReading(bssid=bssid, ssid=ssid, rssi_dbm=rssi, security=sec, host_timestamp=ts)


def adv(address="AA:BB:CC:DD:EE:01", rssi=-50, mfg=None, uuids=None, sd=None, name=None):
    return BleAdvert(
        address=address,
        rssi_dbm=rssi,
        manufacturer_data=mfg or {},
        service_uuids=uuids or [],
        service_data=sd or {},
        name=name,
    )


def u16(short):
    return f"0000{short:04x}-0000-1000-8000-00805f9b34fb"


# --- failure messages use PLAN.md's wording ------------------------------------------------


def test_failure_messages_match_plan_wording():
    assert message_for("location_off") == PLAN_LOCATION
    assert message_for("no_wifi") == PLAN_WIFI_OFF
    assert message_for("bluetooth_off") == PLAN_BLUETOOTH_OFF
    assert message_for("signal_unstable") == PLAN_UNSTABLE


# --- Bluetooth classification (AirGuard signatures) ----------------------------------------


@pytest.mark.parametrize(
    ("data", "kind", "category", "separated"),
    [
        (bytes([0x12, 0x19, 0x10]) + bytes(24), "airtag", "tracker", True),
        (bytes([0x12, 0x02, 0x10, 0x00]), "airtag", "tracker", False),
        (bytes([0x12, 0x19, 0x20]) + bytes(24), "findmy_accessory", "tracker", True),
        (bytes([0x12, 0x19, 0x30]) + bytes(24), "airpods", "tracker", True),
        (bytes([0x12, 0x19, 0x00]) + bytes(24), "apple_findmy_device", "phone_computer", True),
        (bytes([0x07, 0x19, 0x01, 0x0E, 0x20]) + bytes(23), "apple_audio", "audio", None),
        (bytes([0x10, 0x05, 0x01]), "apple", "phone_computer", None),
    ],
)
def test_apple_formats(data, kind, category, separated):
    c = ble.classify(adv(mfg={0x004C: data}))
    assert (c.kind, c.category, c.separated) == (kind, category, separated)


@pytest.mark.parametrize(
    ("sd", "kind", "separated"),
    [
        ({u16(0xFEAA): bytes([0x41]) + bytes(20)}, "google_fmdn", True),
        ({u16(0xFEAA): bytes([0x40]) + bytes(20)}, "google_fmdn", False),
        ({u16(0xFD5A): bytes([0x13, 0x00])}, "smarttag", True),
        ({u16(0xFD5A): bytes([0x12, 0x00])}, "smarttag", False),
    ],
)
def test_service_data_trackers(sd, kind, separated):
    c = ble.classify(adv(sd=sd))
    assert (c.kind, c.category, c.separated) == (kind, "tracker", separated)


def test_eddystone_beacon_is_not_a_google_tracker():
    c = ble.classify(adv(sd={u16(0xFEAA): bytes([0x10, 0x00])}))  # Eddystone-URL frame
    assert c.category != "tracker"


@pytest.mark.parametrize(
    ("uuid", "kind"), [(0xFEED, "tile"), (0xFE33, "chipolo"), (0xFA25, "pebblebee")]
)
def test_service_uuid_trackers(uuid, kind):
    c = ble.classify(adv(uuids=[u16(uuid)]))
    assert (c.kind, c.category) == (kind, "tracker")


def test_chipolo_separation_bit_and_firmware_cutoff():
    sd = {u16(0xFE33): bytes([0x00, 0x01])}
    assert ble.classify(adv("C0:00:00:00:00:01", uuids=[u16(0xFE33)], sd=sd)).separated is True
    assert ble.classify(adv("E0:00:00:00:00:01", uuids=[u16(0xFE33)], sd=sd)).separated is None


@pytest.mark.parametrize(
    ("kwargs", "category"),
    [
        ({"uuids": [u16(0xFE2C)]}, "audio"),  # Google Fast Pair earbuds
        ({"uuids": [u16(0x184E)]}, "audio"),  # LE Audio
        ({"name": "WF-1000XM5"}, "audio"),
        ({"name": "Nuki_1A2B3C"}, "lock"),
        ({"uuids": ["a92ee200-5501-11e4-916c-0800200c9a66"]}, "lock"),
        ({"name": "IPCam-01"}, "camera"),
        ({"mfg": {0x0006: bytes([0x01, 0x09, 0x20])}}, "phone_computer"),
        ({}, "other"),
    ],
)
def test_other_categories(kwargs, category):
    assert ble.classify(adv(**kwargs)).category == category


def test_aggregate_keeps_the_strongest_reading_per_round_and_upgrades_to_tracker():
    a = "AA:BB:CC:DD:EE:01"
    away = {0x004C: bytes([0x12, 0x19, 0x10]) + bytes(24)}
    devices = ble.aggregate([[adv(a, -70), adv(a, -60)], [adv(a.lower(), -65, mfg=away)]], SALT)
    [d] = devices
    assert d.round_rssi == {0: -60, 1: -65}
    assert (d.cls.kind, d.cls.separated) == ("airtag", True)


def test_bluetooth_off_or_unsupported_maps_to_plan_message():
    async def off(seconds):
        raise BleakBluetoothNotAvailableError("off", BleakBluetoothNotAvailableReason.POWERED_OFF)

    async def no_radio(seconds):
        raise BleakError("Failed to start scanner. Is Bluetooth turned on?")

    for discover in (off, no_radio):
        with pytest.raises(WirelessError) as e:
            ble.scan_rounds(discover=discover)
        assert e.value.code == "bluetooth_off"


def test_scan_rounds_runs_three_rounds_of_ten_seconds():
    seen = []

    async def discover(seconds):
        seen.append(seconds)
        return [adv()]

    assert len(ble.scan_rounds(discover=discover)) == 3
    assert seen == [10.0, 10.0, 10.0]


# --- Wi-Fi aggregation: seen at least twice ------------------------------------------------


def test_flicker_is_filtered_out():
    rounds = [
        [reading("cc:ba:bd:ac:94:d9", rssi=-40), reading("00:0c:6e:00:00:01", ssid="Flicker")],
        [reading("cc:ba:bd:ac:94:d9", rssi=-44)],
        [reading("cc:ba:bd:ac:94:d9", rssi=-42)],
    ]
    [home] = aggregate_wifi(rounds, SALT)
    assert (home.ssid, home.sightings, home.rssi_dbm) == ("HomeNet", 3, -42)
    assert home.vendor == "TP-Link Systems Inc."


def test_a_cached_entry_that_never_refreshes_counts_once():
    # The WLAN API keeps returning a stale entry; its host timestamp never moves.
    stale = [reading("00:0c:6e:00:00:02", ssid="Gone", ts=111) for _ in range(3)]
    fresh = [reading("cc:ba:bd:ac:94:d9", ts=t) for t in (1, 2, 3)]
    aps = aggregate_wifi([[s, f] for s, f in zip(stale, fresh, strict=True)], SALT)
    assert [a.ssid for a in aps] == ["HomeNet"]


def test_randomised_bssid_has_no_maker():
    [a] = aggregate_wifi([[reading("9a:3b:4c:00:11:22")]] * 2, SALT)
    assert (a.bssid_random, a.vendor) == (True, None)


def test_refs_are_salted_hashes():
    [a] = aggregate_wifi([[reading("cc:ba:bd:ac:94:d9")]] * 2, SALT)
    [b] = aggregate_wifi([[reading("cc:ba:bd:ac:94:d9")]] * 2, b"other-salt")
    assert a.ref.startswith("wifi:") and "ccbabd" not in a.ref
    assert a.ref != b.ref


# --- netsh fallback ------------------------------------------------------------------------


def test_netsh_networks_parse():
    readings = netsh.parse_networks(read("netsh_networks.txt"))
    assert [(r.bssid, r.ssid) for r in readings] == [
        ("cc:ba:bd:ac:94:d9", "HomeNet"),
        ("9a:3b:4c:00:11:22", "HomeNet"),
        ("cc:ba:bd:ac:94:da", None),
        ("00:11:22:33:44:55", "Free: Cafe Wi-Fi"),
    ]
    home, home2, hidden, cafe = readings
    assert (home.rssi_dbm, home.channel, home.frequency_mhz) == (-54, 44, 5220)
    assert home2.frequency_mhz == 2437 and hidden.frequency_mhz == 2437
    assert home.security.kind == "wpa2" and cafe.security.kind == "open"
    assert not home.wps_known and home.wps is None


@pytest.mark.parametrize(
    ("fixture", "code"),
    [
        ("netsh_location_off.txt", "location_off"),
        ("netsh_no_interface.txt", "no_wifi"),
        ("netsh_networks_french.txt", "nearby_unreadable"),
    ],
)
def test_netsh_failures(fixture, code):
    with pytest.raises(WirelessError) as e:
        netsh.parse_networks(read(fixture))
    assert e.value.code == code


def test_netsh_survey_reads_three_times_ten_seconds_apart():
    sleeps = []
    out = netsh.survey_rounds(run=lambda: read("netsh_networks.txt"), sleep=sleeps.append)
    assert len(out) == 3 and sleeps == [10.0, 10.0]


# --- WLAN API error mapping ----------------------------------------------------------------


class FakeDll:
    """Stands in for wlanapi.dll; each function returns the given Windows error code."""

    def __init__(self, open_rc=0, enum_rc=0, scan_rc=0, list_rc=0):
        def fn(rc):
            def f(*args):
                return rc

            return f

        self.WlanOpenHandle = fn(open_rc)
        self.WlanEnumInterfaces = fn(enum_rc)
        self.WlanScan = fn(scan_rc)
        self.WlanGetNetworkBssList = fn(list_rc)
        self.WlanFreeMemory = fn(None)
        self.WlanCloseHandle = fn(0)


IFACE = wlanapi.Interface(wlanapi.GUID(), "Intel Wi-Fi", wlanapi.INTERFACE_CONNECTED)


@pytest.mark.parametrize(
    ("dll", "action", "code"),
    [
        (FakeDll(open_rc=1062), "open", "no_wifi"),  # WLAN service not running
        (FakeDll(open_rc=87), "open", "wlanapi_unavailable"),
        (FakeDll(scan_rc=5), "scan", "location_off"),
        (FakeDll(scan_rc=0x80342002), "scan", "no_wifi"),  # radio switched off
        (FakeDll(list_rc=5), "list", "location_off"),
        (FakeDll(list_rc=0x80342002), "list", "no_wifi"),
        (FakeDll(enum_rc=1062), "enum", "no_wifi"),
    ],
)
def test_wlanapi_error_codes(dll, action, code):
    api = wlanapi.WlanApi(dll)
    with pytest.raises(WirelessError) as e:
        if action == "open":
            api.__enter__()
        elif action == "scan":
            api.scan(IFACE)
        elif action == "list":
            api.bss_list(IFACE)
        else:
            api.interfaces()
    assert e.value.code == code


def test_busy_scan_still_reads_the_list():
    wlanapi.WlanApi(FakeDll(scan_rc=170)).scan(IFACE)  # ERROR_BUSY: no exception


def test_no_adapter_or_radio_off_means_no_wifi():
    with pytest.raises(WirelessError) as e:
        wlanapi.pick_interface([])
    assert e.value.code == "no_wifi"
    off = wlanapi.Interface(wlanapi.GUID(), "Intel Wi-Fi", wlanapi.INTERFACE_NOT_READY)
    with pytest.raises(WirelessError):
        wlanapi.pick_interface([off])


class FakeApi:
    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.scans = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def interfaces(self):
        return [IFACE]

    def scan(self, iface):
        self.scans += 1

    def bss_list(self, iface):
        return self.rounds.pop(0)


def test_wlanapi_survey_scans_three_times_about_ten_seconds_apart(monkeypatch):
    monkeypatch.setattr(wlanapi, "reading_from_raw", lambda raw: raw)
    api = FakeApi([["a"], ["b"], ["c"]])
    sleeps = []
    out = wlanapi.survey_rounds(api_factory=lambda: api, sleep=sleeps.append)
    assert out == [["a"], ["b"], ["c"]] and api.scans == 3
    assert sleeps == [4.0, 6.0, 4.0, 6.0, 4.0]  # settle, gap, settle, gap, settle: 10 s apart


def test_collect_wifi_falls_back_to_netsh(monkeypatch):
    def unavailable():
        raise WirelessError("wlanapi_unavailable")

    monkeypatch.setattr(wlanapi, "survey_rounds", unavailable)
    monkeypatch.setattr(netsh, "survey_rounds", lambda: [[reading("cc:ba:bd:ac:94:d9")]])
    assert survey.collect_wifi()[0] == "netsh"


def test_collect_wifi_does_not_fall_back_when_location_is_off(monkeypatch):
    def denied():
        raise WirelessError("location_off")

    monkeypatch.setattr(wlanapi, "survey_rounds", denied)
    with pytest.raises(WirelessError):
        survey.collect_wifi()


# --- the nearby check, end to end with fakes -----------------------------------------------

HOME_ROUNDS = [
    [
        reading("cc:ba:bd:ac:94:d9", rssi=-40, ts=t),
        reading("9a:3b:4c:00:11:22", rssi=-42, ts=t, sec=OPEN),
    ]
    for t in (1, 2, 3)
]
AWAY_TAG = {0x004C: bytes([0x12, 0x19, 0x10]) + bytes(24)}


def wifi_ok():
    return "wlanapi", HOME_ROUNDS


def ble_ok():
    return [
        [adv("D1:22:33:44:55:66", -50, mfg=AWAY_TAG)],
        [adv("D1:22:33:44:55:66", -52, mfg=AWAY_TAG)],
        [],
    ]


def raises(code):
    def f():
        raise WirelessError(code)

    return f


def statuses(checks):
    return {c.name: (c.status, c.reason) for c in checks}


def test_nearby_check_flags_twin_and_tracker():
    r = run_nearby_check(connected_fn=lambda: CONNECTED, wifi_fn=wifi_ok, ble_fn=ble_ok, salt=SALT)
    assert r.room_network == "HomeNet"
    assert {f.rule_id for f in r.findings} == {"R-TWIN", "R-TRACKER"}
    assert [i.kind for i in r.items] == ["wifi", "bluetooth"]
    assert r.heard.wifi_access_points == 2 and r.heard.bluetooth_devices == 1
    s = statuses(r.checks)
    assert s["nearby_wifi"][0] == s["bluetooth"][0] == s["lookalike"][0] == s["wps"][0] == "ran"
    assert s["on_network"] == ("skipped", message_for("nearby_only"))
    assert r.summary.status == "Needs attention"
    dumped = r.model_dump_json()
    assert "cc:ba:bd" not in dumped and "9a:3b:4c" not in dumped and "D1:22" not in dumped


def test_location_off_keeps_bluetooth_running():
    r = run_nearby_check(
        connected_fn=lambda: CONNECTED, wifi_fn=raises("location_off"), ble_fn=ble_ok, salt=SALT
    )
    s = statuses(r.checks)
    assert s["nearby_wifi"] == ("failed", PLAN_LOCATION)
    assert s["bluetooth"][0] == "ran"
    assert s["lookalike"] == ("skipped", message_for("nearby_wifi_failed"))
    assert PLAN_LOCATION in r.messages
    assert any(PLAN_LOCATION in x for x in r.summary.not_checked)
    assert [f.rule_id for f in r.findings] == ["R-TRACKER"]


def test_empty_wifi_list_is_reported_as_location_off():
    r = run_nearby_check(
        connected_fn=lambda: None, wifi_fn=lambda: ("wlanapi", [[], [], []]), ble_fn=ble_ok
    )
    assert statuses(r.checks)["nearby_wifi"] == ("failed", PLAN_LOCATION)


def test_wifi_off_keeps_bluetooth_running():
    r = run_nearby_check(connected_fn=lambda: None, wifi_fn=raises("no_wifi"), ble_fn=ble_ok)
    s = statuses(r.checks)
    assert s["nearby_wifi"] == ("failed", PLAN_WIFI_OFF)
    assert s["bluetooth"][0] == "ran"


def test_bluetooth_off_keeps_wifi_running():
    r = run_nearby_check(
        connected_fn=lambda: CONNECTED, wifi_fn=wifi_ok, ble_fn=raises("bluetooth_off"), salt=SALT
    )
    s = statuses(r.checks)
    assert s["bluetooth"] == ("failed", PLAN_BLUETOOTH_OFF)
    assert s["nearby_wifi"][0] == "ran"
    assert PLAN_BLUETOOTH_OFF in r.messages
    assert [f.rule_id for f in r.findings] == ["R-TWIN"]


def test_unexpected_error_is_contained():
    def boom():
        raise RuntimeError("driver bug")

    survey_, checks, _ = collect_nearby(wifi_fn=boom, ble_fn=ble_ok)
    assert statuses(checks)["nearby_wifi"] == ("failed", message_for("internal"))
    assert survey_.ble_devices is not None


def test_netsh_fallback_cannot_check_wps():
    r = run_nearby_check(
        connected_fn=lambda: CONNECTED, wifi_fn=lambda: ("netsh", HOME_ROUNDS), ble_fn=ble_ok
    )
    assert statuses(r.checks)["wps"] == ("skipped", message_for("wps_unknown"))


def test_not_connected_and_no_name_skips_lookalike_checks():
    r = run_nearby_check(connected_fn=lambda: None, wifi_fn=wifi_ok, ble_fn=ble_ok)
    s = statuses(r.checks)
    assert s["lookalike"] == ("skipped", message_for("no_room_network"))
    assert "R-TWIN" not in {f.rule_id for f in r.findings}


def test_typed_name_is_used_when_not_connected():
    r = run_nearby_check(
        typed_room="HomeNet", connected_fn=lambda: None, wifi_fn=wifi_ok, ble_fn=ble_ok
    )
    assert "R-TWIN" in {f.rule_id for f in r.findings}


def test_room_network_prefers_the_connection():
    room = room_network(CONNECTED, "HomeNet")
    assert (room.source, room.bssid, room.security.kind) == (
        "connected",
        "cc:ba:bd:ac:94:d9",
        "wpa2",
    )
    assert room_network(CONNECTED, "OtherNet").source == "typed"
    assert room_network(None, "  ") is None


def test_first_connected_reads_the_bssid():
    s = first_connected((FIXTURES / "checks" / "netsh_wpa2.txt").read_text("utf-8"))
    assert (s.ssid, s.bssid) == ("HomeNet", "cc:ba:bd:ac:94:d9")


# --- Apple proximity pairing (AirPods) ------------------------------------------------------


def test_apple_records_are_walked():
    assert ble.apple_types(bytes([0x10, 0x02, 0xAA, 0xBB, 0x07, 0x01, 0x01])) == [0x10, 0x07]
    assert ble.apple_types(bytes([0x10, 0x09, 0xAA])) == []  # runs past the end


def test_airpods_proximity_record_after_another_record_is_earbuds():
    data = bytes([0x10, 0x02, 0x0B, 0x1C]) + bytes([0x07, 0x05, 0x01, 0x0E, 0x20, 0x75, 0xAA])
    c = ble.classify(adv(mfg={0x004C: data}))
    assert (c.kind, c.category) == ("apple_audio", "audio")


def test_airpods_in_find_my_mode_are_still_judged_as_a_tracker_first():
    data = bytes([0x12, 0x19, 0x30]) + bytes(24)
    assert ble.classify(adv(mfg={0x004C: data})).kind == "airpods"


def test_iphone_nearby_record_alone_stays_a_phone():
    assert (
        ble.classify(adv(mfg={0x004C: bytes([0x10, 0x05, 0x01, 0x18, 0x00, 0x00, 0x00])})).category
        == "phone_computer"
    )
