from app.discovery.messages import message_for
from app.discovery.models import Service
from app.fingerprint.models import HttpIdentity, RtspIdentity, UpnpIdentity
from app.fingerprint.pipeline import Probes, fingerprint_devices
from app.fingerprint.probes import ProbeError
from app.scanner import ScannerError
from tests.unit import devices as dev


class FakeScanner:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def run(self, job, params, timeout):
        self.calls.append((job, params))
        if self.error:
            raise ScannerError(self.error)
        return self.result


def bare(device):
    """Layer 1 view of a fixture device: no identity yet."""
    device.identity = None
    device.vendor = None
    return device


def camera_l1():
    d = bare(dev.hikvision_camera())
    d.services.append(
        Service(
            kind="ssdp",
            name="upnp:rootdevice",
            detail={"location": "http://192.168.68.64/desc.xml"},
        )
    )
    return d


PORTS = [
    {"ip": "192.168.68.64", "open_ports": [80, 554, 8000], "complete": True},
    {"ip": "192.168.68.53", "open_ports": [], "complete": True},
]


def ok_probes(calls=None):
    def http(ip, port):
        (calls is not None) and calls.append(("http", ip, port))
        return HttpIdentity(port=port, scheme="http", status=200, server="webserver", title="Login")

    def rtsp(ip, port):
        (calls is not None) and calls.append(("rtsp", ip, port))
        return RtspIdentity(port=port, status=401, server="Hikvision-Webs")

    def upnp(location, ip):
        (calls is not None) and calls.append(("upnp", ip, location))
        return UpnpIdentity(manufacturer="Hikvision", model_name="DS-2CD2143G0-I")

    return Probes(http=http, rtsp=rtsp, upnp=upnp)


def statuses(checks):
    return {c.name: c.status for c in checks}


def test_passive_mode_looks_up_vendor_only():
    scanner = FakeScanner(PORTS)
    calls = []
    devices = [camera_l1(), bare(dev.sonos())]
    checks, messages = fingerprint_devices(
        devices, consent=False, scanner=scanner, probe_fns=ok_probes(calls)
    )
    assert scanner.calls == [] and calls == []
    assert statuses(checks) == {
        "vendor_lookup": "ran",
        "port_check": "skipped",
        "identity_check": "skipped",
    }
    assert devices[0].vendor.startswith("Hangzhou Hikvision")
    assert devices[0].identity is None
    # ONVIF and vendor alone: possible camera, from passive evidence only.
    assert devices[0].fingerprint.type == "camera"
    assert devices[0].fingerprint.identification == "passive"
    assert messages == []


def test_consented_scan_identifies_camera():
    scanner = FakeScanner(PORTS)
    calls = []
    devices = [camera_l1(), bare(dev.sonos())]
    checks, messages = fingerprint_devices(
        devices, consent=True, scanner=scanner, probe_fns=ok_probes(calls)
    )
    assert scanner.calls == [("port_scan", {})]
    assert sorted(calls) == [
        ("http", "192.168.68.64", 80),
        ("http", "192.168.68.64", 8000),
        ("rtsp", "192.168.68.64", 554),
        ("upnp", "192.168.68.64", "http://192.168.68.64/desc.xml"),
    ]
    cam, speaker = devices
    assert cam.identity.open_ports == [80, 554, 8000]
    assert cam.identity.upnp.model_name == "DS-2CD2143G0-I"
    assert (cam.fingerprint.type, cam.fingerprint.band) == ("camera", "Likely")
    assert cam.fingerprint.identification == "full"
    assert speaker.fingerprint.type == "speaker"
    assert speaker.fingerprint.identification == "full"
    assert statuses(checks) == {
        "vendor_lookup": "ran",
        "port_check": "ran",
        "identity_check": "ran",
    }
    assert messages == []


def test_nmap_missing_skips_port_check_but_still_reads_upnp():
    calls = []
    devices = [camera_l1()]
    checks, _ = fingerprint_devices(
        devices, consent=True, scanner=FakeScanner(error="nmap_missing"), probe_fns=ok_probes(calls)
    )
    port = next(c for c in checks if c.name == "port_check")
    assert port.status == "skipped"
    assert port.reason == message_for("nmap_missing") and "Nmap" in port.reason
    assert [c[0] for c in calls] == ["upnp"]  # no HTTP/RTSP without knowing ports are open
    assert devices[0].identity.open_ports is None
    assert devices[0].fingerprint.type == "camera"


def test_scanner_unavailable_fails_port_check_only():
    checks, _ = fingerprint_devices(
        [bare(dev.sonos())], consent=True, scanner=None, probe_fns=ok_probes()
    )
    assert statuses(checks)["port_check"] == "failed"
    assert statuses(checks)["identity_check"] == "ran"


def test_device_timeout_and_junk_mean_partly_identified():
    def http(ip, port):
        raise ProbeError("didn't answer in time")

    def rtsp(ip, port):
        raise ProbeError("sent a reply we couldn't read")

    def upnp(location, ip):
        raise RuntimeError("parser exploded")  # unexpected errors are contained too

    devices = [camera_l1(), bare(dev.sonos())]
    checks, messages = fingerprint_devices(
        devices, consent=True, scanner=FakeScanner(PORTS), probe_fns=Probes(http, rtsp, upnp)
    )
    cam = devices[0]
    assert cam.fingerprint.identification == "partial"
    assert sorted(cam.identity.problems) == [
        "Device description sent a reply we couldn't read",
        "Video stream check on port 554 sent a reply we couldn't read",
        "Web page on port 80 didn't answer in time",
        "Web page on port 8000 didn't answer in time",
    ]
    # Still scored from what was gathered: ONVIF, maker and open camera port.
    assert cam.fingerprint.type == "camera"
    assert {e.signal for e in cam.fingerprint.evidence} == {
        "onvif_nvt",
        "camera_vendor",
        "camera_ports",
    }
    assert messages == [message_for("partly_identified")]
    assert devices[1].fingerprint.identification == "full"


def test_port_check_incomplete_host_is_partial():
    results = [{"ip": "192.168.68.53", "open_ports": [], "complete": False}]
    devices = [bare(dev.sonos())]
    _, messages = fingerprint_devices(
        devices, consent=True, scanner=FakeScanner(results), probe_fns=ok_probes()
    )
    assert devices[0].fingerprint.identification == "partial"
    assert messages == [message_for("partly_identified")]


def test_upnp_location_on_another_host_is_never_fetched():
    calls = []
    d = bare(dev.sonos())
    d.services.append(
        Service(
            kind="ssdp", name="upnp:rootdevice", detail={"location": "http://192.168.68.1/x.xml"}
        )
    )
    fingerprint_devices([d], consent=True, scanner=FakeScanner(PORTS), probe_fns=ok_probes(calls))
    assert calls == []


def test_tls_mismatch_is_a_note_not_a_problem():
    from app.fingerprint.probes import TLS_MISMATCH_NOTE, TlsMismatchError

    def http(ip, port):
        raise TlsMismatchError()

    base = ok_probes()
    devices = [camera_l1()]
    results = [{"ip": "192.168.68.64", "open_ports": [443, 554], "complete": True}]
    _, messages = fingerprint_devices(
        devices,
        consent=True,
        scanner=FakeScanner(results),
        probe_fns=Probes(http=http, rtsp=base.rtsp, upnp=base.upnp),
    )
    cam = devices[0]
    assert cam.identity.notes == [TLS_MISMATCH_NOTE]
    assert cam.identity.problems == []
    assert cam.fingerprint.notes == [TLS_MISMATCH_NOTE]
    assert cam.fingerprint.identification == "full"
    assert messages == []
    # Evidence only: it adds no weight to any type.
    assert all("encryption" not in e.text for e in cam.fingerprint.evidence)
