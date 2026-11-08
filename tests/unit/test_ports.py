import json

import nmap
import pytest

from app.discovery.models import NetworkInfo
from scannerd import session
from scannerd.jobs import ports
from scannerd.protocol import JobError
from scannerd.server import default_jobs, handle_request
from tests.unit.devices import fixture

NET = NetworkInfo(
    interface="Wi-Fi",
    own_ip="192.0.2.60",
    own_mac=None,
    gateway_ip="192.0.2.1",
    netmask="255.255.252.0",
    cidr="192.0.2.0/24",
    prefixlen=22,
    sweep_allowed=True,
)


@pytest.fixture(autouse=True)
def clean_session():
    session.clear()
    yield
    session.clear()


def test_fixed_ports_and_arguments_match_plan():
    assert ports.PORTS == (23, 80, 443, 554, 8554, 1883, 8883, 6668, 8000, 8080, 8443, 34567, 37777)
    assert ports.NMAP_ARGUMENTS == "-sT -Pn -T3 --max-retries 1 --host-timeout 30s"


def test_job_accepts_no_parameters():
    jobs = default_jobs()
    for params in ({"hosts": "8.8.8.8"}, {"arguments": "-sS -A"}, {"ports": "1-65535"}):
        reply = handle_request(json.dumps({"job": "port_scan", "params": params}).encode(), jobs)
        assert reply == {"ok": False, "error": "bad_params"}


def test_select_targets_stays_in_subnet():
    swept = ["192.0.2.1", "192.0.2.60", "192.0.2.255", "10.0.0.5", "192.0.2.9", "198.51.100.9"]
    assert ports.select_targets(swept, NET.cidr, NET.own_ip) == ["192.0.2.1", "192.0.2.9"]


def test_parse_scan_fixture():
    scan = json.loads(fixture("nmap_scan.json"))
    out = ports.parse_scan(scan, ["192.0.2.1", "192.0.2.64", "192.0.2.53", "192.0.2.77"])
    assert out == [
        {"ip": "192.0.2.1", "open_ports": [80, 443], "complete": True},
        # 9999 isn't on the fixed list and 8554 is filtered, so neither is reported.
        {"ip": "192.0.2.64", "open_ports": [80, 554, 8000], "complete": True},
        {"ip": "192.0.2.53", "open_ports": [], "complete": True},
        # Missing from nmap's output, e.g. skipped after --host-timeout.
        {"ip": "192.0.2.77", "open_ports": [], "complete": False},
    ]


def test_parse_scan_junk():
    assert ports.parse_scan({"scan": "junk"}, ["192.0.2.1"])[0]["complete"] is False
    assert ports.parse_scan(None, ["192.0.2.1"])[0]["complete"] is False  # type: ignore[arg-type]


def test_nmap_missing(monkeypatch):
    monkeypatch.setattr(ports.shutil, "which", lambda name: None)
    with pytest.raises(JobError) as e:
        ports.port_scan(ports.PortScanParams())
    assert e.value.code == "nmap_missing"


class FakeScanner:
    calls: list = []

    def __init__(self, nmap_search_path):
        self.path = nmap_search_path

    def scan(self, hosts, ports, arguments, timeout):
        FakeScanner.calls.append((self.path, hosts, ports, arguments))
        return json.loads(fixture("nmap_scan.json"))


@pytest.fixture
def fake_nmap(monkeypatch):
    FakeScanner.calls = []
    monkeypatch.setattr(ports.shutil, "which", lambda name: r"C:\Nmap\nmap.exe")
    monkeypatch.setattr(ports, "get_network_info", lambda: NET)
    monkeypatch.setattr(nmap, "PortScanner", FakeScanner)
    return FakeScanner


def test_port_scan_targets_only_hosts_scannerd_swept(fake_nmap):
    session.record_swept(["192.0.2.1", "192.0.2.64", "192.0.2.60"])
    out = ports.port_scan(ports.PortScanParams())
    [(path, hosts, port_list, args)] = fake_nmap.calls
    assert path == (r"C:\Nmap\nmap.exe",)
    assert hosts == "192.0.2.1 192.0.2.64"  # own laptop excluded
    assert port_list == ports.PORT_LIST
    assert args == ports.NMAP_ARGUMENTS
    assert [r["ip"] for r in out] == ["192.0.2.1", "192.0.2.64"]


def test_port_scan_without_a_sweep_scans_nothing(fake_nmap):
    assert ports.port_scan(ports.PortScanParams()) == []
    assert fake_nmap.calls == []


def test_new_sweep_replaces_old_hosts(fake_nmap):
    session.record_swept(["192.0.2.20"])
    session.record_swept(["192.0.2.1"])
    ports.port_scan(ports.PortScanParams())
    assert fake_nmap.calls[0][1] == "192.0.2.1"


def test_nmap_timeout_and_errors(monkeypatch, fake_nmap):
    session.record_swept(["192.0.2.1"])

    def raising(exc):
        class S(FakeScanner):
            def scan(self, *a, **k):
                raise exc

        monkeypatch.setattr(nmap, "PortScanner", S)

    raising(nmap.PortScannerTimeout("timeout"))
    with pytest.raises(JobError) as e:
        ports.port_scan(ports.PortScanParams())
    assert e.value.code == "timeout"

    raising(nmap.PortScannerError("Failed to open device"))
    with pytest.raises(JobError) as e:
        ports.port_scan(ports.PortScanParams())
    assert e.value.code == "nmap_failed"
