from datetime import UTC, datetime

from app.discovery.messages import message_for
from app.discovery.models import NetworkInfo, Observation
from app.discovery.netinfo import NoNetworkError
from app.discovery.runner import Collector, _run_one, default_collectors, run_discovery
from app.scanner import ScannerError

NOW = datetime(2026, 11, 2, tzinfo=UTC)

NET = NetworkInfo(
    interface="Wi-Fi",
    own_ip="192.168.1.10",
    own_mac="00:00:00:00:00:10",
    gateway_ip="192.168.1.1",
    netmask="255.255.255.0",
    cidr="192.168.1.0/24",
    prefixlen=24,
    sweep_allowed=True,
)
BIG_NET = NET.model_copy(
    update={
        "netmask": "255.255.0.0",
        "cidr": "192.168.0.0/16",
        "prefixlen": 16,
        "sweep_allowed": False,
    }
)


def o(source, ip, mac=None):
    return Observation(source=source, seen_at=NOW, ip=ip, mac=mac)


def collector(name, result, *, active=False, sweep=False, calls=None):
    def run(net):
        if calls is not None:
            calls.append(name)
        if isinstance(result, Exception):
            raise result
        return result

    return Collector(name, name, active=active, run=run, sweep=sweep)


def fake_clock(*times):
    it = iter(times)
    return lambda: next(it)


def test_full_mode_merges_all_sources_and_drops_own_laptop():
    cols = [
        collector("passive_listen", [o("arp_passive", "192.168.1.10", "00:00:00:00:00:10")]),
        collector(
            "arp_sweep",
            [
                o("arp_sweep", "192.168.1.1", "00:00:00:00:00:01"),
                o("arp_sweep", "192.168.1.64", "00:12:34:56:78:9a"),
            ],
            active=True,
            sweep=True,
        ),
        collector("onvif", [o("onvif", "192.168.1.64")], active=True),
    ]
    r = run_discovery("full", cols, get_network=lambda: NET, clock=fake_clock(0, 61))
    assert [d.ip for d in r.devices] == ["192.168.1.1", "192.168.1.64"]
    assert r.devices[0].is_gateway
    assert r.devices[1].sources == ["arp_sweep", "onvif"]
    assert [c.status for c in r.checks] == ["ran", "ran", "ran"]
    assert [c.found for c in r.checks] == [1, 2, 1]
    assert not r.client_isolation


def test_passive_mode_never_runs_active_collectors():
    calls = []
    cols = [
        collector("passive_listen", [], calls=calls),
        collector("arp_sweep", [], active=True, sweep=True, calls=calls),
        collector("ssdp", [], active=True, calls=calls),
    ]
    r = run_discovery("passive", cols, get_network=lambda: NET, clock=fake_clock(0, 61))
    assert calls == ["passive_listen"]
    assert [c.status for c in r.checks] == ["ran", "skipped", "skipped"]
    assert r.checks[1].reason == message_for("passive_mode")
    assert not r.client_isolation  # no sweep, so no claim about isolation


def test_large_subnet_skips_sweep_but_still_listens():
    calls = []
    cols = [
        collector("passive_listen", [], calls=calls),
        collector("arp_sweep", [], active=True, sweep=True, calls=calls),
        collector("ssdp", [], active=True, calls=calls),
    ]
    r = run_discovery("full", cols, get_network=lambda: BIG_NET, clock=fake_clock(0, 61))
    assert calls.count("arp_sweep") == 0
    assert set(calls) == {"passive_listen", "ssdp"}
    assert r.checks[1].reason == message_for("subnet_too_large")
    assert message_for("subnet_too_large") in r.messages


def test_no_network():
    def no_net():
        raise NoNetworkError

    r = run_discovery("full", [collector("arp_sweep", [])], get_network=no_net)
    assert r.network is None
    assert r.messages == [message_for("no_network")]
    assert r.checks[0].status == "skipped"


def test_one_failure_does_not_stop_others():
    cols = [
        collector("passive_listen", ScannerError("npcap_missing")),
        collector("mdns", [o("mdns", "192.168.1.55")]),
        collector("ssdp", OSError("bind failed"), active=True),
    ]
    r = run_discovery("full", cols, get_network=lambda: NET, clock=fake_clock(0, 61))
    assert [c.status for c in r.checks] == ["failed", "ran", "failed"]
    assert "Npcap" in r.checks[0].reason
    assert r.checks[2].reason == message_for("internal")
    assert [d.ip for d in r.devices] == ["192.168.1.55"]


def test_client_isolation_reported():
    cols = [
        collector(
            "arp_sweep",
            [o("arp_sweep", "192.168.1.1", "00:00:00:00:00:01")],
            active=True,
            sweep=True,
        )
    ]
    r = run_discovery("full", cols, get_network=lambda: NET, clock=fake_clock(0, 75))
    assert r.client_isolation
    assert message_for("client_isolation") in r.messages


def test_missing_scanner_fails_only_scanner_jobs():
    cols = default_collectors(scanner=None, duration_seconds=10)
    by_name = {c.name: c for c in cols}
    assert set(by_name) == {"passive_listen", "mdns", "arp_sweep", "ssdp", "onvif"}
    assert not by_name["passive_listen"].active and not by_name["mdns"].active
    assert by_name["arp_sweep"].active and by_name["arp_sweep"].sweep
    status, _ = _run_one(by_name["arp_sweep"], NET)
    assert status.status == "failed"
    assert status.reason == message_for("scanner_unavailable")


class RecordingScanner:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def run(self, job, params, timeout):
        self.calls.append((job, params))
        return self.result


def test_scanner_jobs_send_only_fixed_parameters():
    scanner = RecordingScanner(
        [o("arp_sweep", "192.168.1.1", "00:00:00:00:00:01").model_dump(mode="json")]
    )
    cols = {c.name: c for c in default_collectors(scanner, duration_seconds=60)}
    cols["arp_sweep"].run(NET)
    found = cols["passive_listen"].run(NET)
    assert scanner.calls == [
        ("arp_sweep", {"gap_seconds": 20.0}),
        ("passive_listen", {"duration_seconds": 60}),
    ]
    assert found[0].mac == "00:00:00:00:00:01"
