"""Rules engine: every rule firing and not firing, mesh-friendly cases, and the room summary."""

import re
from datetime import UTC, datetime, timedelta

import pytest
import yaml
from pydantic import ValidationError

from app.checks.cve import model_queries
from app.checks.models import (
    ArpClaim,
    CveMatch,
    DhcpOffer,
    DnsResult,
    NetworkFacts,
    WifiStatus,
)
from app.discovery.models import CheckStatus, NetworkInfo, Service
from app.fingerprint.facts import device_facts
from app.fingerprint.models import Identity, UpnpIdentity
from app.fingerprint.probes import TLS_MISMATCH_NOTE
from app.fingerprint.scoring import fingerprint
from app.rules.engine import RULES_FILE, RoomFacts, RulesFile, evaluate, load_rules, summarise
from tests.unit import devices as dev

T = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
NET = NetworkInfo(
    interface="Wi-Fi",
    own_ip="192.0.2.60",
    own_mac="c4:0f:08:11:22:33",
    gateway_ip="192.0.2.1",
    netmask="255.255.252.0",
    cidr="192.0.2.0/24",
    prefixlen=22,
    sweep_allowed=True,
)


def scored(d, ident="full"):
    d.fingerprint = fingerprint(device_facts(d), ident)
    return d


def run(devices=(), net=None, checks=()):
    return evaluate(
        RoomFacts(
            devices=list(devices), network=NET, net=net or NetworkFacts(), checks=list(checks)
        )
    )


def rule_ids(findings):
    return [f.rule_id for f in findings]


def one(findings, rule_id):
    [f] = [f for f in findings if f.rule_id == rule_id]
    return f


# --- R-CAM ------------------------------------------------------------------------------------


def test_cam_likely_is_high_with_guidance():
    f = one(run([scored(dev.hikvision_camera())]), "R-CAM")
    assert (f.severity, f.confidence_band, f.title) == ("High", "Likely", "Likely camera")
    assert f.device_ref == "mac:00:bc:99:aa:bb:cc"
    assert f.id == "R-CAM:mac:00:bc:99:aa:bb:cc"
    assert any("ONVIF" in e for e in f.evidence)
    assert "Maker: Hangzhou Hikvision Digital Technology Co.,Ltd." in f.evidence
    assert "Network address: 192.0.2.64" in f.evidence
    assert f.next_step.startswith("Find it physically, then say where it is.")
    assert any("Photograph it" in g for g in f.guidance)


def test_cam_possible_is_medium():
    d = dev.hikvision_camera()
    d.services = []  # no ONVIF: RTSP 0.5 + port 8000 0.3 + maker 0.3 -> 0.755
    f = one(run([scored(d)]), "R-CAM")
    assert (f.severity, f.confidence_band, f.title) == ("Medium", "Possible", "Possible camera")


def test_cam_does_not_fire_for_speaker_laptop_or_tp_link_router():
    devices = [scored(dev.sonos()), scored(dev.macbook()), scored(dev.tp_link_gateway())]
    assert "R-CAM" not in rule_ids(run(devices))


def test_cam_partial_identification_and_tls_note_are_evidence():
    d = dev.hikvision_camera()
    d.identity.notes.append(TLS_MISMATCH_NOTE)
    d.identity.problems.append("Web page on port 80 didn't answer in time")
    f = one(run([scored(d, "partial")]), "R-CAM")
    assert any("outdated firmware" in e for e in f.evidence)
    assert "Partly identified: some checks on this device didn't finish" in f.evidence


# --- R-LOCK -----------------------------------------------------------------------------------


def test_lock_fires_high():
    d = dev.make(
        "192.0.2.90",
        None,
        hostnames=["Front-Door-Lock.local"],
        services=[dev.mdns("_hap._tcp", ci="6")],
    )
    f = one(run([scored(d)]), "R-LOCK")
    assert f.severity == "High"
    assert f.next_step.startswith("Ask the host to remove previous users and codes")


def test_lock_does_not_fire_on_other_devices():
    assert "R-LOCK" not in rule_ids(run([scored(dev.sonos()), scored(dev.hikvision_camera())]))


# --- R-CLOUD ----------------------------------------------------------------------------------


def test_cloud_fires_on_tuya_broadcast():
    d = dev.make(
        "192.0.2.77",
        "10:d5:61:00:00:01",
        services=[Service(kind="tuya", name="tuya-broadcast", detail={"port": "6667"})],
    )
    f = one(run([scored(d)]), "R-CLOUD")
    assert (f.severity, f.confidence_band) == ("Medium", "Likely")
    assert any("Tuya" in e for e in f.evidence)


def test_cloud_fires_on_smart_plug_type():
    d = dev.make("192.0.2.78", None, hostnames=["kasa-plug-1"], identity=Identity(open_ports=[]))
    f = one(run([scored(d)]), "R-CLOUD")
    assert f.confidence_band == "Possible"


def test_cloud_does_not_fire_on_laptop_or_speaker():
    assert "R-CLOUD" not in rule_ids(run([scored(dev.macbook()), scored(dev.sonos())]))


# --- R-TELNET ---------------------------------------------------------------------------------


def test_telnet_fires_high():
    d = dev.tp_link_gateway()
    d.identity.open_ports = [23, 80]
    f = one(run([scored(d)]), "R-TELNET")
    assert f.severity == "High"
    assert "Port 23 (Telnet) is open" in f.evidence


def test_telnet_not_fired_when_closed_or_unchecked():
    unchecked = dev.tp_link_gateway()
    unchecked.identity = None
    assert "R-TELNET" not in rule_ids(run([scored(dev.tp_link_gateway()), scored(unchecked)]))


# --- R-WIFI-ENC -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("auth", "cipher"), [("Open", "None"), ("Shared", "WEP"), ("WPA-Personal", "WEP")]
)
def test_wifi_enc_fires_on_open_or_wep(auth, cipher):
    net = NetworkFacts(
        wifi=WifiStatus(interface="Wi-Fi", ssid="Hotel", authentication=auth, cipher=cipher)
    )
    f = one(run(net=net), "R-WIFI-ENC")
    assert (f.severity, f.device_ref, f.id) == ("High", None, "R-WIFI-ENC:network")
    assert '"Hotel"' in f.evidence[0]


def test_wifi_enc_quiet_on_wpa2_and_when_not_checked():
    net = NetworkFacts(
        wifi=WifiStatus(interface="Wi-Fi", authentication="WPA2-Personal", cipher="CCMP")
    )
    assert "R-WIFI-ENC" not in rule_ids(run(net=net))
    assert "R-WIFI-ENC" not in rule_ids(run(net=NetworkFacts(wifi=None)))


# --- R-UPNP -----------------------------------------------------------------------------------


def test_upnp_fires_once_for_mesh_and_points_at_gateway():
    gw = dev.tp_link_gateway()
    node = dev.make(
        "192.0.2.248",
        "cc:ba:bd:00:10:92",
        services=[Service(kind="ssdp", name="urn:schemas-upnp-org:device:InternetGatewayDevice:1")],
    )
    findings = run([node, gw])
    f = one(findings, "R-UPNP")
    assert f.severity == "Medium"
    assert f.device_ref == gw.id
    assert len(f.evidence) == 2 and "this network's router" in " ".join(f.evidence)


def test_upnp_from_description_device_type():
    d = dev.make(
        "192.0.2.5",
        None,
        identity=Identity(
            upnp=UpnpIdentity(device_type="urn:schemas-upnp-org:device:InternetGatewayDevice:2")
        ),
    )
    assert "R-UPNP" in rule_ids(run([d]))


def test_upnp_quiet_for_media_renderers():
    d = dev.make(
        "192.0.2.5",
        None,
        services=[Service(kind="ssdp", name="urn:schemas-upnp-org:device:MediaRenderer:1")],
    )
    assert "R-UPNP" not in rule_ids(run([d]))


# --- R-DNS ------------------------------------------------------------------------------------


def test_dns_fires_on_nxdomain_hijack():
    net = NetworkFacts(
        dns=DnsResult(
            random_name="roomcheck-ab.example.com",
            nxdomain=False,
            random_name_answers=["198.51.100.7"],
        )
    )
    f = one(run(net=net), "R-DNS")
    assert f.severity == "High"
    assert "roomcheck-ab.example.com" in f.evidence[0] and "198.51.100.7" in f.evidence[0]


def test_dns_fires_on_private_answer():
    net = NetworkFacts(
        dns=DnsResult(
            random_name="x", nxdomain=True, non_public_answers={"example.com": ["10.0.0.1"]}
        )
    )
    assert "R-DNS" in rule_ids(run(net=net))


def test_dns_quiet_when_honest_or_unclear():
    honest = NetworkFacts(
        dns=DnsResult(random_name="x", nxdomain=True, checked_domains=["example.com"])
    )
    unclear = NetworkFacts(dns=DnsResult(random_name="x", nxdomain=None))
    assert "R-DNS" not in rule_ids(run(net=honest))
    assert "R-DNS" not in rule_ids(run(net=unclear))


# --- R-ARP ------------------------------------------------------------------------------------


def claim(mac, vendor, minutes=0):
    return ArpClaim(
        ip="192.0.2.1",
        mac=mac,
        vendor=vendor,
        first_seen=T,
        last_seen=T + timedelta(minutes=minutes),
    )


def test_arp_fires_high_when_another_maker_claims_the_gateway():
    net = NetworkFacts(
        arp_claims=[
            claim("cc:ba:bd:00:10:d8", "TP-Link Systems Inc."),
            claim("02:11:22:33:44:55", None),
        ]
    )
    f = one(run([dev.tp_link_gateway()], net=net), "R-ARP")
    assert (f.severity, f.confidence_band, f.title) == (
        "High",
        "Likely",
        "More than one device answers for the router",
    )
    assert f.next_step == "Possible interception. Disconnect and use mobile data."
    assert f.device_ref == dev.tp_link_gateway().id


def test_arp_same_maker_is_medium_possible_mesh_friendly():
    net = NetworkFacts(
        arp_claims=[
            claim("cc:ba:bd:00:10:d8", "TP-Link Systems Inc."),
            claim("cc:ba:bd:00:10:d9", "TP-Link Systems Inc."),
        ]
    )
    f = one(run(net=net), "R-ARP")
    assert (f.severity, f.confidence_band) == ("Medium", "Possible")
    assert "mesh system" in f.next_step


def test_arp_quiet_with_one_mac_or_vrrp_virtual_mac():
    single = NetworkFacts(arp_claims=[claim("cc:ba:bd:00:10:d8", "TP-Link Systems Inc.")])
    vrrp = NetworkFacts(
        arp_claims=[
            claim("cc:ba:bd:00:10:d8", "TP-Link Systems Inc."),
            claim("00:00:5e:00:01:01", None),
        ]
    )
    assert "R-ARP" not in rule_ids(run(net=single))
    assert "R-ARP" not in rule_ids(run(net=vrrp))


def test_arp_ignores_claims_for_other_addresses():
    other = ArpClaim(ip="192.0.2.50", mac="02:00:00:00:00:09", first_seen=T, last_seen=T)
    net = NetworkFacts(arp_claims=[claim("cc:ba:bd:00:10:d8", "TP-Link"), other])
    assert "R-ARP" not in rule_ids(run(net=net))


# --- R-DHCP -----------------------------------------------------------------------------------


def test_dhcp_fires_on_two_servers():
    net = NetworkFacts(
        dhcp_offers=[
            DhcpOffer(server_id="192.0.2.1", server_mac="cc:ba:bd:00:10:d8"),
            DhcpOffer(server_id="192.0.2.250", server_mac="02:00:00:00:00:66"),
        ]
    )
    f = one(run(net=net), "R-DHCP")
    assert f.severity == "High" and len(f.evidence) == 2


def test_dhcp_one_server_through_mesh_nodes_is_quiet():
    # Mesh / relay: the same server id arriving via two MACs is still one server.
    net = NetworkFacts(
        dhcp_offers=[
            DhcpOffer(server_id="192.0.2.1", server_mac="cc:ba:bd:00:10:d8"),
            DhcpOffer(server_id="192.0.2.1", server_mac="cc:ba:bd:00:10:92"),
        ]
    )
    assert "R-DHCP" not in rule_ids(run(net=net))
    assert "R-DHCP" not in rule_ids(run(net=NetworkFacts(dhcp_offers=None)))


# --- R-CVE ------------------------------------------------------------------------------------


def cve_net(device, exploited):
    return NetworkFacts(
        cves={
            device.id: [
                CveMatch(
                    model="hikvision DS-2CD2143G2-I",
                    cpe="cpe:2.3:o:hikvision:ds-2cd2143g2-i_firmware",
                    total=3,
                    cve_ids=["CVE-2021-36260", "CVE-2017-7921"],
                    exploited=exploited,
                )
            ]
        }
    )


def test_cve_exploited_is_medium_and_phrased_as_reported_for_model():
    d = scored(dev.hikvision_camera())
    f = one(run([d], net=cve_net(d, ["CVE-2021-36260"])), "R-CVE")
    assert (f.severity, f.confidence_band) == ("Medium", "Possible")
    assert f.title == "Known issues reported for this model"
    assert f.evidence[0].startswith("Known issues reported for this model")
    assert any("actively exploited" in e for e in f.evidence)


def test_cve_reported_only_is_info():
    d = scored(dev.hikvision_camera())
    assert one(run([d], net=cve_net(d, [])), "R-CVE").severity == "Info"


def test_cve_quiet_without_matches():
    assert "R-CVE" not in rule_ids(run([scored(dev.hikvision_camera())]))


def test_model_queries_only_from_device_reported_models():
    d = dev.hikvision_camera()
    assert model_queries(d) == []  # ONVIF without scopes, no UPnP: nothing to look up
    d.identity.upnp = UpnpIdentity(manufacturer="Hikvision", model_name="DS-2CD2143G2-I")
    d.services[0].detail["scopes"] = (
        "onvif://www.onvif.org/hardware/DS-2CD2143G2-I onvif://www.onvif.org/name/HIKVISION"
    )
    assert model_queries(d) == [("hikvision", "DS-2CD2143G2-I")]
    assert model_queries(dev.sonos()) == []


# --- summary ----------------------------------------------------------------------------------


def test_findings_sorted_high_first():
    d = scored(dev.hikvision_camera())
    findings = run(
        [d],
        net=NetworkFacts(
            cves=cve_net(d, []).cves,
            wifi=WifiStatus(interface="w", authentication="Open", cipher="None"),
        ),
    )
    assert [f.severity for f in findings] == sorted(
        [f.severity for f in findings], key=["High", "Medium", "Low", "Info"].index
    )


def test_summary_needs_attention_with_any_high():
    findings = run([scored(dev.hikvision_camera())])
    s = summarise(findings, [])
    assert (s.status, s.high) == ("Needs attention", 1)


def test_summary_check_items_with_only_medium():
    d = dev.hikvision_camera()
    d.services = []
    s = summarise(run([scored(d)]), [])
    assert (s.status, s.high, s.medium) == ("Check these items", 0, 1)


def test_summary_nothing_found_lists_what_was_not_checked():
    checks = [
        CheckStatus(
            name="dhcp",
            label="Checking for a second device",
            status="skipped",
            reason="Skipped because you chose a listen-only check.",
        ),
        CheckStatus(name="dns", label="Checking DNS", status="ran"),
    ]
    s = summarise(run([scored(dev.sonos())]), checks)
    assert s.status == "Not detected by these checks"
    assert (
        s.not_checked[0]
        == "Checking for a second device: Skipped because you chose a listen-only check."
    )
    assert any("unconfirmed: clues, not proof" in x for x in s.cant_see)  # Layer 4 blind spot
    assert any("memory card" in x for x in s.cant_see)


def test_info_findings_do_not_raise_the_status():
    d = scored(dev.sonos())
    net = NetworkFacts(
        cves={
            d.id: [
                CveMatch(
                    model="sonos One",
                    cpe="cpe:2.3:o:sonos:one_firmware",
                    total=1,
                    cve_ids=["CVE-1"],
                )
            ]
        }
    )
    s = summarise(run([d], net=net), [])
    assert (s.status, s.other) == ("Not detected by these checks", 1)


# --- rules file -------------------------------------------------------------------------------


def test_rules_file_has_the_layer3_and_layer4_rules():
    assert [r.id for r in load_rules().rules] == [
        "R-CAM",
        "R-NEW-CAMERA",  # Layer 6: new since the move-in scan
        "R-LOCK",
        "R-CLOUD",
        "R-TELNET",
        "R-WIFI-ENC",
        "R-UPNP",
        "R-DNS",
        "R-ARP",
        "R-DHCP",
        "R-CVE",
        "R-TWIN",
        "R-TWIN-VENDOR",
        "R-TWIN-DOWNGRADE",
        "R-WPS",
        "R-CAMHOT",
        "R-TRACKER",
        "R-HIDDEN",
        "R-OPEN",
    ]


def test_rules_file_rejects_unknown_predicates_and_fields():
    data = yaml.safe_load(RULES_FILE.read_text(encoding="utf-8"))
    data["rules"][0]["when"] = {"__import__": {"name": "os"}}
    with pytest.raises(ValidationError):
        RulesFile.model_validate(data)
    data = yaml.safe_load(RULES_FILE.read_text(encoding="utf-8"))
    data["rules"][0]["evidence_fields"] = ["mac_address"]
    with pytest.raises(ValidationError):
        RulesFile.model_validate(data)


_SAFE = re.compile(r"\bsafe(ly|ty)?\b|no risk", re.IGNORECASE)
# Every sentence the dashboard says itself (Layer 7 frontend).
WEB_STRINGS_FILE = RULES_FILE.parents[2] / "web" / "src" / "strings" / "en.json"


def _strings(node):
    if isinstance(node, dict):
        for v in node.values():
            yield from _strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings(v)
    else:
        yield str(node)


def test_never_says_safe():
    assert not _SAFE.search(RULES_FILE.read_text(encoding="utf-8"))
    d = scored(dev.hikvision_camera())
    findings = run([d, scored(dev.sonos())], net=cve_net(d, ["CVE-2021-36260"]))
    s = summarise(findings, [])
    assert not _SAFE.search(" ".join(f.model_dump_json() for f in findings) + s.model_dump_json())
    assert not _SAFE.search(summarise([], []).model_dump_json())
    # The frontend's strings file, every sentence in it.
    import json

    sentences = list(_strings(json.loads(WEB_STRINGS_FILE.read_text(encoding="utf-8"))))
    assert len(sentences) > 50
    # It's reading the current file: the Start screen's permission choices and limitation.
    assert "Results are clues, not proof. Some devices won't be detected." in sentences
    assert "RoomCheck only listens. You can ask your host for permission." in sentences
    assert [t for t in sentences if _SAFE.search(t)] == []


def test_findings_carry_their_rules_scope():
    d = scored(dev.hikvision_camera())
    findings = run([d], net=cve_net(d, ["CVE-2021-36260"]))
    assert {f.rule_id: f.scope for f in findings}["R-CAM"] == "device"
    scopes = {r.id: r.scope for r in load_rules().rules}
    assert all(f.scope == scopes[f.rule_id] for f in findings)


def test_model_queries_from_live_run_cases():
    # Tapo camera: URL-encoded ONVIF name; the registered MAC maker is used as the maker.
    tapo = dev.make(
        "192.0.2.58",
        "34:60:f9:00:53:58",
        services=[
            Service(
                kind="onvif",
                name="NetworkVideoTransmitter",
                detail={
                    "scopes": "onvif://www.onvif.org/name/tapo%20tc70 "
                    "onvif://www.onvif.org/hardware/TC70"
                },
            )
        ],
    )
    assert model_queries(tapo) == [("tp-link", "TC70")]
    # Same camera on a private MAC: fall back to the decoded ONVIF name.
    tapo.vendor = None
    assert model_queries(tapo) == [("tapo", "TC70")]
    # Sonos: the maker isn't repeated in the model.
    sonos = dev.sonos()
    sonos.identity.upnp = UpnpIdentity(manufacturer="Sonos, Inc.", model_name="Sonos Arc")
    assert model_queries(sonos) == [("sonos", "Arc")]


def window(mac, start_min, end_min, vendor="TP-Link Systems Inc."):
    return ArpClaim(
        ip="192.0.2.1",
        mac=mac,
        vendor=vendor,
        first_seen=T + timedelta(minutes=start_min),
        last_seen=T + timedelta(minutes=end_min),
    )


def test_arp_same_maker_clean_handover_stays_medium():
    # A answers, stops, then B takes over (e.g. mesh failover): no switching back.
    net = NetworkFacts(
        arp_claims=[window("cc:ba:bd:00:10:d8", 0, 1), window("cc:ba:bd:00:10:d9", 2, 3)]
    )
    f = one(run(net=net), "R-ARP")
    assert (f.severity, f.confidence_band) == ("Medium", "Possible")
    assert not any("switching" in e for e in f.evidence)


def test_arp_same_maker_flip_flop_is_high():
    # A seen before and after B: the answer switched back and forth.
    net = NetworkFacts(
        arp_claims=[window("cc:ba:bd:00:10:d8", 0, 3), window("cc:ba:bd:00:10:d9", 1, 2)]
    )
    f = one(run(net=net), "R-ARP")
    assert (f.severity, f.confidence_band) == ("High", "Likely")
    assert f.title == "The device answering for the router keeps switching"
    assert f.next_step == "Possible interception. Disconnect and use mobile data."
    assert any("switching back and forth" in e for e in f.evidence)


def test_arp_flip_flop_found_among_three_claims():
    net = NetworkFacts(
        arp_claims=[
            window("cc:ba:bd:00:10:d8", 0, 1),
            window("cc:ba:bd:00:10:d9", 2, 5),
            window("cc:ba:bd:00:10:da", 3, 4),
        ]
    )
    assert one(run(net=net), "R-ARP").severity == "High"


def test_arp_different_makers_stay_high_without_flip_flop():
    net = NetworkFacts(
        arp_claims=[window("cc:ba:bd:00:10:d8", 0, 1), window("02:11:22:33:44:55", 2, 3, None)]
    )
    f = one(run(net=net), "R-ARP")
    assert f.severity == "High"
    assert f.title == "More than one device answers for the router"


def test_rule_texts_never_guess_where_a_device_is():
    """RoomCheck knows a device is on this network or heard nearby, never where it is. The same
    exact-phrase check the AI text gets (app/explain/validator.py) runs on every rule's own
    standard explanation and why-it-matters text."""
    from app.explain.validator import _LOCATION

    for rule in load_rules().rules:
        for field in ("explanation", "why_it_matters"):
            value = getattr(rule, field)
            texts = value.values() if isinstance(value, dict) else [value]
            for text in texts:
                assert not _LOCATION.search(text or ""), (rule.id, field, text)


def test_tracker_why_it_matters_has_no_location_guess():
    tracker = next(r for r in load_rules().rules if r.id == "R-TRACKER")
    expected = "A tracker you don't recognise could be used to follow where you go."
    assert tracker.why_it_matters == expected
