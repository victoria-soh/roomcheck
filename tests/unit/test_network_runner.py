"""Layer 3 runner: which checks run in each mode, and the failure messages."""

from datetime import UTC, datetime

from app.checks import cve
from app.checks.models import DnsResult, WifiStatus
from app.checks.runner import gateway_claims, run_network_checks
from app.checks.wifi import WifiCheckError
from app.discovery.messages import message_for
from app.discovery.models import CheckStatus, DiscoveryResult, NetworkInfo, Observation
from app.fingerprint.models import UpnpIdentity
from app.scanner import ScannerError
from tests.unit import devices as dev

T = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
NET = NetworkInfo(
    interface="Wi-Fi",
    own_ip="192.168.68.60",
    own_mac="c4:0f:08:11:22:33",
    gateway_ip="192.168.68.1",
    netmask="255.255.252.0",
    cidr="192.168.68.0/22",
    prefixlen=22,
    sweep_allowed=True,
)
WPA2 = WifiStatus(interface="Wi-Fi", ssid="HomeNet", authentication="WPA2-Personal", cipher="CCMP")
HONEST = DnsResult(random_name="x", nxdomain=True, checked_domains=["example.com"])


def result(mode="full", devices=(), observations=(), ran=("passive_listen", "arp_sweep", "ssdp")):
    checks = [CheckStatus(name=n, label=n, status="ran") for n in ran]
    if "ssdp" not in ran:
        checks.append(
            CheckStatus(
                name="ssdp", label="ssdp", status="skipped", reason=message_for("passive_mode")
            )
        )
    return DiscoveryResult(
        started_at=T,
        finished_at=T,
        mode=mode,
        network=NET,
        devices=list(devices),
        checks=checks,
        observations=list(observations),
    )


class FakeScanner:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def run(self, job, params, timeout):
        self.calls.append((job, params))
        if self.error:
            raise ScannerError(self.error)
        return self.result


class FakeNvd:
    def __init__(self, error=None):
        self.error, self.calls = error, []
        self.cache = type("C", (), {"close": lambda self: None})()

    def lookup(self, word, model, deadline):
        self.calls.append((word, model))
        if self.error:
            raise self.error
        return [
            cve.CveMatch(model=f"{word} {model}", cpe="cpe:2.3:o:x:y", total=1, cve_ids=["CVE-1"])
        ]


def statuses(checks):
    return {c.name: c.status for c in checks}


def reasons(checks):
    return {c.name: c.reason for c in checks}


def go(
    res, consent=True, scanner=None, online=True, wifi=lambda i: WPA2, dns=lambda: HONEST, nvd=None
):
    nvd = nvd or FakeNvd()
    return run_network_checks(
        res,
        consent=consent,
        scanner=scanner if scanner is not None else FakeScanner([]),
        online=online,
        wifi_fn=wifi,
        dns_fn=dns,
        nvd_factory=lambda: nvd,
    )


def test_passive_mode_runs_only_local_and_listening_checks():
    scanner = FakeScanner([])
    nvd = FakeNvd()
    facts, checks, _ = go(
        result("passive", ran=("passive_listen",)), consent=False, scanner=scanner, nvd=nvd
    )
    assert statuses(checks) == {
        "wifi_encryption": "ran",
        "dns": "ran",
        "arp": "ran",
        "dhcp": "skipped",
        "upnp": "skipped",
        "cve": "skipped",
    }
    assert scanner.calls == [] and nvd.calls == []
    assert reasons(checks)["dhcp"] == message_for("passive_mode")
    assert facts.dhcp_offers is None


def test_consent_runs_dhcp_probe_with_no_parameters():
    scanner = FakeScanner(
        [
            {
                "server_id": "192.168.68.1",
                "server_mac": "cc:ba:bd:ac:94:d8",
                "offered_ip": "192.168.68.60",
            }
        ]
    )
    facts, checks, _ = go(result(), scanner=scanner)
    assert scanner.calls == [("dhcp_probe", {})]
    assert facts.dhcp_offers[0].server_id == "192.168.68.1"
    assert statuses(checks)["dhcp"] == "ran"


def test_dhcp_failures_have_messages():
    _, checks, _ = go(result(), scanner=FakeScanner(error="npcap_missing"))
    assert statuses(checks)["dhcp"] == "failed"
    assert "Npcap" in reasons(checks)["dhcp"]
    _, checks, _ = go(result(), scanner=FakeScanner([]))
    assert reasons(checks)["dhcp"] == message_for("no_dhcp_offer")


def test_wired_and_unreadable_wifi():
    _, checks, _ = go(result(), wifi=lambda i: None)
    assert (statuses(checks)["wifi_encryption"], reasons(checks)["wifi_encryption"]) == (
        "skipped",
        message_for("not_wifi"),
    )

    def unreadable(i):
        raise WifiCheckError("unreadable")

    _, checks, _ = go(result(), wifi=unreadable)
    assert statuses(checks)["wifi_encryption"] == "failed"
    assert "language" in reasons(checks)["wifi_encryption"]


def test_dns_failure_and_unclear():
    def boom():
        raise OSError("no resolver")

    _, checks, _ = go(result(), dns=boom)
    assert (statuses(checks)["dns"], reasons(checks)["dns"]) == (
        "failed",
        message_for("dns_unclear"),
    )
    _, checks, _ = go(result(), dns=lambda: DnsResult(random_name="x", nxdomain=None))
    assert statuses(checks)["dns"] == "failed"


def test_arp_needs_the_listener():
    _, checks, _ = go(result(ran=()), consent=True)
    assert (statuses(checks)["arp"], reasons(checks)["arp"]) == (
        "skipped",
        message_for("no_listener"),
    )


def test_gateway_claims_track_first_and_last_sighting_per_mac():
    obs = [
        Observation(source="arp_passive", seen_at=T, ip="192.168.68.1", mac="cc:ba:bd:ac:94:d8"),
        Observation(
            source="arp_sweep",
            seen_at=T.replace(minute=1),
            ip="192.168.68.1",
            mac="CC-BA-BD-AC-94-D8",
        ),
        Observation(
            source="arp_passive",
            seen_at=T.replace(minute=2),
            ip="192.168.68.1",
            mac="02:11:22:33:44:55",
        ),
        Observation(source="arp_passive", seen_at=T, ip="192.168.68.53", mac="38:42:0b:42:c1:84"),
        Observation(source="dhcp", seen_at=T, ip="192.168.68.1", mac="aa:aa:aa:aa:aa:aa"),
    ]
    claims = {c.mac: c for c in gateway_claims(result(observations=obs))}
    assert set(claims) == {"cc:ba:bd:ac:94:d8", "02:11:22:33:44:55"}
    assert claims["cc:ba:bd:ac:94:d8"].vendor == "TP-Link Systems Inc."
    assert claims["cc:ba:bd:ac:94:d8"].last_seen == T.replace(minute=1)
    assert claims["02:11:22:33:44:55"].vendor is None


def camera_with_model():
    d = dev.hikvision_camera()
    d.identity.upnp = UpnpIdentity(manufacturer="Hikvision", model_name="DS-2CD2143G2-I")
    return d


def test_cve_lookup_only_for_reported_models():
    nvd = FakeNvd()
    facts, checks, _ = go(result(devices=[camera_with_model(), dev.sonos()]), nvd=nvd)
    assert nvd.calls == [("hikvision", "DS-2CD2143G2-I")]
    assert list(facts.cves) == [camera_with_model().id]
    assert statuses(checks)["cve"] == "ran"


def test_cve_no_models_offline_and_rate_limited():
    _, checks, _ = go(result(devices=[dev.sonos()]))
    assert reasons(checks)["cve"] == message_for("no_models")
    _, checks, _ = go(result(devices=[camera_with_model()]), online=False)
    assert (statuses(checks)["cve"], reasons(checks)["cve"]) == ("skipped", message_for("offline"))
    _, checks, _ = go(
        result(devices=[camera_with_model()]), nvd=FakeNvd(error=cve.NvdUnavailable("HTTP 403"))
    )
    assert (statuses(checks)["cve"], reasons(checks)["cve"]) == (
        "skipped",
        "Vulnerability lookup skipped for now.",
    )


def test_no_network_skips_everything():
    r = result()
    r.network = None
    _, checks, _ = go(r)
    assert set(statuses(checks).values()) == {"skipped"}
