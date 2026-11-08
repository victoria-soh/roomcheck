"""Layer 4 rules: lookalike networks (real twins, mesh systems, randomised BSSIDs), camera
setup hotspots, hidden and open networks, WPS, and the tracker repeat logic."""

import re

import pytest

from app.discovery.merge import is_random_mac
from app.fingerprint.oui import load_oui, lookup_vendor
from app.rules.engine import RoomFacts, evaluate, summarise
from app.rules.hotspots import HOTSPOT_FILE, load_hotspots
from app.rules.nearby import company_key
from app.wireless import ble
from app.wireless.ie import make_security
from app.wireless.models import AccessPoint, BleAdvert, NearbySurvey, RoomNetwork, WpsInfo
from app.wireless.privacy import wifi_ref
from app.wireless.survey import flagged_items

SALT = b"test-salt"
WPA2 = make_security("wpa2", pairwise=["CCMP"])
WPA3 = make_security("wpa3", pairwise=["CCMP"])
MIXED = make_security("wpa2/wpa3", pairwise=["CCMP"])
OPEN = make_security("open")
OWE = make_security("owe")
WEP = make_security("wep")
WPA1 = make_security("wpa", pairwise=["TKIP"])
UNKNOWN = make_security("unknown")

ROUTER = "cc:ba:bd:00:10:d9"  # TP-Link Systems Inc.
ROUTER_5G = "cc:ba:bd:00:10:da"
MESH_NODE = "00:14:78:10:20:30"  # TP-LINK TECHNOLOGIES CO.,LTD.: same company, other registration
ASUS = "00:0c:6e:aa:bb:cc"
EERO_1 = "00:ab:48:01:02:03"
EERO_2 = "08:9b:f1:01:02:03"
HIKVISION = "00:bc:99:aa:bb:cc"
PHONE_HOTSPOT = "9a:3b:4c:00:11:22"  # locally administered: randomised
MESH_EXTRA = "da:ba:bd:00:53:db"  # randomised extra network from a mesh node

CONNECTED = RoomNetwork(ssid="HomeNet", bssid=ROUTER, security=WPA2, source="connected")
TYPED = RoomNetwork(ssid="HomeNet", source="typed")


def ap(bssid, ssid="HomeNet", rssi=-50, sec=WPA2, wps=None, mhz=2437):
    random = is_random_mac(bssid)
    return AccessPoint(
        ref=wifi_ref(bssid, SALT),
        bssid=bssid,
        ssid=ssid,
        rssi_dbm=rssi,
        frequency_mhz=mhz,
        channel=6,
        security=sec,
        wps=wps,
        vendor=None if random else lookup_vendor(bssid),
        bssid_random=random,
        sightings=3,
    )


def judge(aps=(), room=CONNECTED, ble_devices=None, rounds=3):
    survey = NearbySurvey(
        room=room,
        access_points=list(aps),
        wifi_method="wlanapi",
        ble_devices=ble_devices,
        ble_rounds=rounds,
    )
    return evaluate(RoomFacts(devices=[], network=None, nearby=survey)), survey


def ids(findings):
    return [f.rule_id for f in findings]


def one(findings, rule_id):
    [f] = [f for f in findings if f.rule_id == rule_id]
    return f


# --- R-TWIN: same name, weaker security ----------------------------------------------------


def test_real_twin_open_phone_hotspot_is_high():
    hotspot = ap(PHONE_HOTSPOT, rssi=-42, sec=OPEN)
    findings, survey = judge([ap(ROUTER), hotspot])
    f = one(findings, "R-TWIN")
    assert (f.severity, f.confidence_band) == ("High", "Likely")
    assert f.nearby_ref == hotspot.ref
    assert f.id == f"R-TWIN:{hotspot.ref}"
    assert (
        'Another access point is also called "HomeNet", but uses Open (no password)' in f.evidence
    )
    assert 'Your connection to "HomeNet" uses WPA2' in f.evidence
    assert any(e.startswith("Maker: unknown (private address") for e in f.evidence)
    assert f.next_step.startswith("Don't connect to it.")
    # Only R-TWIN: the open copy isn't also listed as a neighbour's open network.
    assert "R-OPEN" not in ids(findings)
    assert summarise(findings, []).status == "Needs attention"


@pytest.mark.parametrize("weaker", [OPEN, OWE, WEP, WPA1])
def test_any_weaker_security_is_a_twin(weaker):
    findings, _ = judge([ap(ROUTER), ap(PHONE_HOTSPOT, sec=weaker)])
    assert "R-TWIN" in ids(findings)


def test_mesh_nodes_with_the_same_security_stay_silent():
    aps = [ap(ROUTER), ap(ROUTER_5G, mhz=5220), ap(MESH_NODE, rssi=-48), ap(MESH_EXTRA)]
    findings, _ = judge(aps)
    assert not {"R-TWIN", "R-TWIN-VENDOR"} & set(ids(findings))


def test_wpa3_band_next_to_transition_mode_is_not_a_twin():
    # Tri-band routers run WPA3-only on 6 GHz and WPA2/WPA3 on the other bands.
    room = RoomNetwork(ssid="HomeNet", bssid=ROUTER, security=WPA3, source="connected")
    findings, _ = judge([ap(ROUTER, sec=WPA3, mhz=6115), ap(ROUTER_5G, sec=MIXED)], room=room)
    assert "R-TWIN" not in ids(findings)


def test_unknown_security_is_never_compared():
    findings, _ = judge([ap(ROUTER), ap(PHONE_HOTSPOT, sec=UNKNOWN)])
    assert "R-TWIN" not in ids(findings)


def test_connection_details_used_when_connected_ap_not_in_the_list():
    room = RoomNetwork(ssid="HomeNet", bssid="cc:ba:bd:00:00:01", security=WPA2, source="connected")
    findings, _ = judge([ap(PHONE_HOTSPOT, sec=OPEN)], room=room)
    assert 'Your connection to "HomeNet" uses WPA2' in one(findings, "R-TWIN").evidence


def test_typed_room_network_compares_with_its_strongest_access_point():
    findings, _ = judge([ap(ROUTER), ap(PHONE_HOTSPOT, sec=OPEN)], room=TYPED)
    f = one(findings, "R-TWIN")
    assert 'The strongest access point named "HomeNet" uses WPA2' in f.evidence


def test_no_room_network_means_no_lookalike_or_wps_findings():
    wps = WpsInfo(state="configured")
    findings, _ = judge([ap(ROUTER, wps=wps), ap(PHONE_HOTSPOT, sec=OPEN)], room=None)
    assert not {"R-TWIN", "R-TWIN-VENDOR", "R-WPS"} & set(ids(findings))


def test_a_differently_named_open_network_is_not_a_twin():
    findings, _ = judge([ap(ROUTER), ap(PHONE_HOTSPOT, ssid="HomeNet_EXT", sec=OPEN)])
    assert "R-TWIN" not in ids(findings)
    assert "R-OPEN" in ids(findings)


# --- R-TWIN-VENDOR: same name and security, different maker --------------------------------


def test_other_maker_with_strong_signal_is_a_possible_lookalike():
    asus = ap(ASUS, rssi=-45)
    findings, _ = judge([ap(ROUTER), ap(MESH_NODE), asus])
    f = one(findings, "R-TWIN-VENDOR")
    assert (f.severity, f.confidence_band, f.nearby_ref) == ("Medium", "Possible", asus.ref)
    assert f.title == "Possible lookalike of your Wi-Fi"
    assert any("made by ASUSTek COMPUTER INC." in e for e in f.evidence)
    assert "The access point you're connected to is made by TP-Link Systems Inc." in f.evidence
    assert "Mesh systems and extenders can explain this" in f.next_step


def test_other_maker_with_weak_signal_is_silent():
    findings, _ = judge([ap(ROUTER), ap(ASUS, rssi=-75)])
    assert "R-TWIN-VENDOR" not in ids(findings)


def test_one_maker_with_two_registrations_is_the_same_maker():
    assert company_key("TP-LINK TECHNOLOGIES CO.,LTD.") == company_key("TP-Link Systems Inc")
    assert company_key("Hangzhou Hikvision Digital Technology Co.,Ltd.") == "hikvision"
    assert company_key("ASUSTek COMPUTER INC.") != company_key("TP-Link Systems Inc.")


def test_randomised_bssids_are_maker_unknown_never_a_match():
    # Extra mesh networks and phone hotspots: same name and security, randomised addresses.
    aps = [ap(ROUTER), ap(MESH_EXTRA, rssi=-40), ap(PHONE_HOTSPOT, rssi=-35)]
    findings, survey = judge(aps)
    assert "R-TWIN-VENDOR" not in ids(findings)
    assert all(a.vendor is None for a in survey.access_points if a.bssid_random)


def test_typed_name_uses_a_strict_majority_maker():
    asus = ap(ASUS, rssi=-50)
    findings, _ = judge([ap(ROUTER), ap(MESH_NODE), asus], room=TYPED)
    f = one(findings, "R-TWIN-VENDOR")
    assert f.nearby_ref == asus.ref
    assert "2 other access points with this name are made by" in f.evidence[1]


def test_no_clear_reference_maker_means_no_finding():
    # Not connected, one TP-Link and one ASUS: nobody can say which one is the odd one out.
    findings, _ = judge([ap(ROUTER), ap(ASUS)], room=TYPED)
    assert "R-TWIN-VENDOR" not in ids(findings)


def test_randomised_connected_ap_falls_back_to_the_majority():
    room = RoomNetwork(ssid="HomeNet", bssid=MESH_EXTRA, security=WPA2, source="connected")
    tp = ap(ROUTER)
    findings, _ = judge([ap(MESH_EXTRA), ap(EERO_1), ap(EERO_2), tp], room=room)
    assert one(findings, "R-TWIN-VENDOR").nearby_ref == tp.ref


# --- R-CAMHOT ------------------------------------------------------------------------------


def test_camera_named_hotspot_is_medium_possible():
    cam = ap(PHONE_HOTSPOT, ssid="IPCAM-7F3A21", sec=WPA2)
    findings, _ = judge([ap(ROUTER), cam])
    f = one(findings, "R-CAMHOT")
    assert (f.severity, f.confidence_band, f.nearby_ref) == ("Medium", "Possible", cam.ref)
    assert 'The network name "IPCAM-7F3A21" matches the name mentions a camera' in f.evidence
    # "Unconfirmed" is said once on the page, not on each card.
    assert not [e for e in f.evidence if "not proof" in e]
    assert "Use the locator" in f.next_step


def test_camera_maker_from_bssid_fires_even_with_a_plain_name():
    f = one(judge([ap(HIKVISION, ssid="Guest-24")])[0], "R-CAMHOT")
    assert any("a company known for cameras" in e for e in f.evidence)


def test_wps_camera_device_type_fires():
    wps = WpsInfo(state="configured", device_category=4)
    f = one(judge([ap(PHONE_HOTSPOT, ssid="Setup-1234", wps=wps)])[0], "R-CAMHOT")
    assert "Its setup information (WPS) describes it as a camera" in f.evidence


def test_camera_hotspot_quiet_for_ordinary_names_and_the_room_network():
    aps = [ap(ROUTER), ap(ASUS, ssid="Campus-WiFi"), ap(EERO_1, ssid="Cameron's iPhone")]
    assert "R-CAMHOT" not in ids(judge(aps)[0])
    room = RoomNetwork(ssid="SmartCam-Home", bssid=ROUTER, security=WPA2, source="connected")
    assert "R-CAMHOT" not in ids(judge([ap(ROUTER, ssid="SmartCam-Home")], room=room)[0])


# --- hotspot patterns file -----------------------------------------------------------------


def test_every_pattern_matches_its_own_examples():
    hs = load_hotspots()
    for spec, pattern in zip(hs.spec.patterns, hs.patterns, strict=True):
        for example in spec.examples:
            assert pattern.regex.search(example), (spec.id, example)


def test_no_pattern_matches_ordinary_names():
    hs = load_hotspots()
    for name in hs.spec.must_not_match:
        assert hs.match_name(name) is None, name


def test_camera_vendor_regex_over_the_whole_oui_list():
    hs = load_hotspots()
    matched = {n for n in load_oui().values() if hs.camera_vendor_match(n)}
    assert "Ring LLC" in matched
    assert "Hangzhou Hikvision Digital Technology Co.,Ltd." in matched
    assert "Reolink Innovation Limited" in matched
    # Lookalike words in unrelated companies' names must not count.
    for wrong in (
        "Align Engineering LLC",
        "ARLOTTO COMNET, INC.",
        "Hanwha NxMD (Thailand) Co., Ltd.",
    ):
        assert wrong not in matched


def test_hotspot_file_never_says_safe():
    assert not re.search(r"\bsafe(ly|ty)?\b|no risk", HOTSPOT_FILE.read_text("utf-8"), re.I)


# --- R-HIDDEN and R-OPEN -------------------------------------------------------------------


def test_strong_hidden_network_is_low():
    hidden = ap(MESH_EXTRA, ssid=None, rssi=-48)
    f = one(judge([ap(ROUTER), hidden])[0], "R-HIDDEN")
    assert (f.severity, f.nearby_ref) == ("Low", hidden.ref)
    assert "Shown as context, and unconfirmed" in f.next_step


@pytest.mark.parametrize("rssi", [-60, -75])
def test_hidden_network_at_or_below_threshold_is_silent(rssi):
    assert "R-HIDDEN" not in ids(judge([ap(MESH_EXTRA, ssid=None, rssi=rssi)])[0])


def test_open_networks_are_one_info_finding():
    aps = [
        ap(ROUTER),
        ap(ASUS, ssid="Free Cafe", sec=OPEN, rssi=-70),
        ap(EERO_1, ssid="Free Cafe", sec=OPEN, rssi=-60),
        ap(EERO_2, ssid="Library", sec=OPEN, rssi=-80),
        ap(HIKVISION, ssid="Enhanced", sec=OWE),
    ]
    f = one(judge(aps)[0], "R-OPEN")
    assert (f.severity, f.nearby_ref, f.id) == ("Info", None, "R-OPEN:nearby")
    assert f.evidence == [
        '"Free Cafe" has no password (signal -60 dBm)',
        '"Library" has no password (signal -80 dBm)',
    ]


def test_open_list_is_capped():
    aps = [ap(f"00:0c:6e:00:00:{i:02x}", ssid=f"Open{i}", sec=OPEN) for i in range(13)]
    f = one(judge(aps)[0], "R-OPEN")
    assert len(f.evidence) == 11 and f.evidence[-1] == "and 3 more"


# --- R-WPS ---------------------------------------------------------------------------------


def test_wps_on_the_room_network_is_medium():
    wps = WpsInfo(state="configured", config_methods=0x0088, ap_setup_locked=True)
    router = ap(ROUTER, wps=wps, rssi=-40)
    findings, _ = judge([router, ap(MESH_NODE, wps=WpsInfo(state="configured"))])
    f = one(findings, "R-WPS")
    assert (f.severity, f.confidence_band, f.nearby_ref) == ("Medium", "Likely", router.ref)
    assert (
        f.evidence[0]
        == 'An access point called "HomeNet" (TP-Link Systems Inc., 2.4 GHz) advertises WPS'
    )
    assert "It lists PIN entry among its setup methods" in f.evidence
    assert any("locked for now" in e for e in f.evidence)
    # The PIN risk is in why_it_matters only, not repeated in the next step (B4).
    assert f.next_step == "Ask the host whether WPS can be switched off."


def test_wps_on_a_neighbours_network_or_a_weaker_copy_is_not_r_wps():
    wps = WpsInfo(state="configured")
    aps = [ap(ROUTER), ap(ASUS, ssid="Neighbour", wps=wps), ap(PHONE_HOTSPOT, sec=OPEN, wps=wps)]
    assert "R-WPS" not in ids(judge(aps)[0])


# --- R-TRACKER: repeated sightings with a strong signal ------------------------------------

AIRTAG_AWAY = {0x004C: bytes([0x12, 0x19, 0x10]) + bytes(24)}
AIRTAG_NEAR_OWNER = {0x004C: bytes([0x12, 0x02, 0x10, 0x00])}
TILE = ["0000feed-0000-1000-8000-00805f9b34fb"]
SMARTTAG_AWAY = {"0000fd5a-0000-1000-8000-00805f9b34fb": bytes([0x13, 0x00])}
FAST_PAIR = ["0000fe2c-0000-1000-8000-00805f9b34fb"]


def adv(address, rssi, mfg=None, uuids=None, sd=None, name=None):
    return BleAdvert(
        address=address,
        rssi_dbm=rssi,
        manufacturer_data=mfg or {},
        service_uuids=uuids or [],
        service_data=sd or {},
        name=name,
    )


def trackers(rounds):
    return judge([], ble_devices=ble.aggregate(rounds, SALT), rounds=len(rounds))[0]


def test_tracker_away_from_owner_in_repeated_scans_is_flagged():
    a = "D1:22:33:44:55:66"
    findings = trackers(
        [[adv(a, -55, AIRTAG_AWAY)], [adv(a, -58, AIRTAG_AWAY)], [adv(a, -60, AIRTAG_AWAY)]]
    )
    f = one(findings, "R-TRACKER")
    assert (f.severity, f.confidence_band) == ("Medium", "Likely")
    assert f.title == "Item tracker nearby"
    assert "Heard with a strong signal in 3 of 3 scans (strongest -55 dBm)" in f.evidence
    assert any("AirGuard" in e for e in f.evidence)
    assert f.next_step == (
        "If it isn't yours, find it with the locator; a phone's built-in "
        "unknown-tracker alert gives a second opinion."
    )
    assert f.standard_why == "A tracker you don't recognise could be used to follow where you go."


def test_one_sighting_is_not_enough():
    assert "R-TRACKER" not in ids(trackers([[adv("D1:00:00:00:00:01", -40, AIRTAG_AWAY)], [], []]))


def test_repeated_but_weak_is_not_enough():
    a = "D1:00:00:00:00:02"
    rounds = [[adv(a, -85, AIRTAG_AWAY)], [adv(a, -82, AIRTAG_AWAY)], [adv(a, -50, AIRTAG_AWAY)]]
    assert "R-TRACKER" not in ids(trackers(rounds))  # only one strong round


def test_tracker_near_its_owner_is_left_alone():
    a = "D1:00:00:00:00:03"
    rounds = [[adv(a, -45, AIRTAG_NEAR_OWNER)] for _ in range(3)]
    assert "R-TRACKER" not in ids(trackers(rounds))


def test_tracker_that_cannot_say_where_its_owner_is_is_possible():
    a = "E4:00:00:00:00:04"
    f = one(trackers([[adv(a, -60, uuids=TILE)], [adv(a, -62, uuids=TILE)], []]), "R-TRACKER")
    assert f.confidence_band == "Possible"
    assert "This tracker type doesn't show whether its owner is nearby" in f.evidence


def test_rotating_address_still_counts_as_one_tracker():
    rounds = [
        [adv("C1:00:00:00:00:01", -55, sd=SMARTTAG_AWAY)],
        [adv("C2:00:00:00:00:02", -57, sd=SMARTTAG_AWAY)],
        [],
    ]
    f = one(trackers(rounds), "R-TRACKER")
    assert any("address changed during the scan" in e for e in f.evidence)


def test_two_different_trackers_heard_once_each_in_one_scan_are_not_merged():
    rounds = [
        [
            adv("C1:00:00:00:00:01", -55, sd=SMARTTAG_AWAY),
            adv("C3:00:00:00:00:03", -55, sd=SMARTTAG_AWAY),
        ],
        [adv("C2:00:00:00:00:02", -57, sd=SMARTTAG_AWAY)],
        [],
    ]
    assert "R-TRACKER" not in ids(trackers(rounds))


def test_earbuds_are_never_trackers():
    a = "F0:00:00:00:00:05"
    rounds = [[adv(a, -40, uuids=FAST_PAIR, name="Galaxy Buds2")] for _ in range(3)]
    assert trackers(rounds) == []


# --- what is kept --------------------------------------------------------------------------


def test_only_flagged_items_are_kept_without_raw_addresses():
    hotspot = ap(PHONE_HOTSPOT, sec=OPEN, rssi=-42)
    tracker_addr = "D1:22:33:44:55:66"
    survey = NearbySurvey(
        room=CONNECTED,
        access_points=[ap(ROUTER), ap(ASUS, ssid="Neighbour"), hotspot],
        wifi_method="wlanapi",
        ble_devices=ble.aggregate(
            [[adv(tracker_addr, -50, AIRTAG_AWAY), adv("F0:00:00:00:00:09", -40, uuids=FAST_PAIR)]]
            * 2,
            SALT,
        ),
        ble_rounds=2,
    )
    findings = evaluate(RoomFacts(devices=[], network=None, nearby=survey))
    items = flagged_items(survey, findings)
    assert [(i.kind, i.rule_ids) for i in items] == [
        ("wifi", ["R-TWIN"]),
        ("bluetooth", ["R-TRACKER"]),
    ]
    assert items[0].ref == hotspot.ref and items[0].ssid == "HomeNet"
    kept = "".join(i.model_dump_json() for i in items) + "".join(
        f.model_dump_json() for f in findings
    )
    for raw in (PHONE_HOTSPOT, ROUTER, ASUS, tracker_addr, "F0:00:00:00:00:09"):
        assert raw.lower() not in kept.lower()
        assert raw.replace(":", "").lower() not in kept.lower()
    assert "Neighbour" not in kept


# --- R-TWIN-DOWNGRADE: WPA2-only copy of a network that offers WPA3 ------------------------

TP_ROUTER = "00:31:92:aa:00:01"  # TP-Link Systems Inc
TP_NODE = "00:31:92:aa:00:02"
MIXED_ROOM = RoomNetwork(ssid="HomeNet", bssid=TP_ROUTER, security=WPA2, source="connected")


def test_wpa2_only_copy_with_unknown_maker_is_a_possible_downgrade():
    # An iPhone hotspot with Maximise Compatibility: WPA2 only, randomised address.
    hotspot = ap(PHONE_HOTSPOT, rssi=-38, sec=WPA2)
    findings, _ = judge(
        [ap(TP_ROUTER, sec=MIXED), ap(TP_NODE, sec=MIXED), hotspot], room=MIXED_ROOM
    )
    f = one(findings, "R-TWIN-DOWNGRADE")
    assert (f.severity, f.confidence_band, f.nearby_ref) == ("Medium", "Possible", hotspot.ref)
    assert f.title == "Possible downgrade lookalike of your Wi-Fi"
    assert f.evidence[0] == 'Another access point called "HomeNet" offers only WPA2, without WPA3'
    # Windows reported WPA2 for the connection, but the beacon shows the network offers WPA3.
    assert f.evidence[1] == "The access point you're connected to offers WPA2/WPA3"
    assert "R-TWIN" not in ids(findings) and "R-TWIN-VENDOR" not in ids(findings)


def test_same_maker_wpa2_only_node_stays_silent():
    findings, _ = judge(
        [ap(TP_ROUTER, sec=MIXED), ap(TP_NODE, sec=WPA2, rssi=-40)], room=MIXED_ROOM
    )
    assert not {"R-TWIN-DOWNGRADE", "R-TWIN-VENDOR", "R-TWIN"} & set(ids(findings))


def test_different_known_maker_is_left_to_r_twin_vendor():
    findings, _ = judge([ap(TP_ROUTER, sec=MIXED), ap(ASUS, sec=WPA2, rssi=-40)], room=MIXED_ROOM)
    assert "R-TWIN-VENDOR" in ids(findings)
    assert "R-TWIN-DOWNGRADE" not in ids(findings)


def test_weak_wpa2_only_copy_is_silent():
    findings, _ = judge([ap(TP_ROUTER, sec=MIXED), ap(PHONE_HOTSPOT, rssi=-75)], room=MIXED_ROOM)
    assert "R-TWIN-DOWNGRADE" not in ids(findings)


def test_no_downgrade_when_the_room_network_is_wpa2_only():
    findings, _ = judge([ap(ROUTER), ap(PHONE_HOTSPOT, rssi=-38)])
    assert "R-TWIN-DOWNGRADE" not in ids(findings)


def test_enterprise_copy_is_not_a_downgrade():
    ent = make_security("wpa2", enterprise=True, pairwise=["CCMP"])
    findings, _ = judge([ap(TP_ROUTER, sec=MIXED), ap(PHONE_HOTSPOT, sec=ent)], room=MIXED_ROOM)
    assert "R-TWIN-DOWNGRADE" not in ids(findings)


def test_typed_name_uses_registered_wpa3_access_points():
    findings, _ = judge(
        [ap(TP_ROUTER, sec=MIXED), ap(TP_NODE, sec=MIXED), ap(PHONE_HOTSPOT, rssi=-40)],
        room=TYPED,
    )
    f = one(findings, "R-TWIN-DOWNGRADE")
    assert (
        f.evidence[1]
        == '2 access point(s) named "HomeNet" made by TP-Link Systems Inc offer WPA2/WPA3'
    )


def test_randomised_wpa3_nodes_do_not_count_as_proof_of_wpa3():
    # Only randomised nodes offer WPA3: no registered evidence, and Windows says WPA2.
    findings, _ = judge(
        [ap(MESH_EXTRA, sec=WPA3, rssi=-85), ap(PHONE_HOTSPOT, rssi=-40)],
        room=RoomNetwork(ssid="HomeNet", source="typed"),
    )
    assert "R-TWIN-DOWNGRADE" not in ids(findings)


@pytest.mark.parametrize("room", ["connected", "typed"])
def test_live_mesh_from_run_1_stays_silent(room):
    """The 8 "Example-Home" access points heard on 2 Nov (addresses made up, makers kept)."""
    live = [
        ap("00:31:92:00:00:01", ssid="Example-Home", sec=MIXED, rssi=-80),
        ap("cc:ba:bd:00:00:02", ssid="Example-Home", sec=MIXED, rssi=-66),
        ap("da:31:92:00:00:03", ssid="Example-Home", sec=WPA3, rssi=-85, mhz=6115),
        ap("de:31:92:00:00:04", ssid="Example-Home", sec=WPA3, rssi=-86, mhz=6115),
        ap("00:31:92:00:00:05", ssid="Example-Home", sec=MIXED, rssi=-41),
        ap("cc:ba:bd:00:00:06", ssid="Example-Home", sec=MIXED, rssi=-73),
        ap("00:31:92:00:00:07", ssid="Example-Home", sec=MIXED, rssi=-32),
        ap("cc:ba:bd:00:00:08", ssid="Example-Home", sec=MIXED, rssi=-86),
    ]
    rn = (
        RoomNetwork(
            ssid="Example-Home", bssid="00:31:92:00:00:07", security=WPA2, source="connected"
        )
        if room == "connected"
        else RoomNetwork(ssid="Example-Home", source="typed")
    )
    findings, _ = judge(live, room=rn)
    assert not {"R-TWIN", "R-TWIN-VENDOR", "R-TWIN-DOWNGRADE"} & set(ids(findings))
