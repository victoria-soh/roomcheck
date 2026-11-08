"""The demo data the screenshots, the page tests and the demo PDF use, made by RoomCheck's own
pipeline from made-up raw scan inputs. Nothing here is hand-written output.

Each check runs the same stages as app/scan.py run_scan: the discovery merge (from made-up
observations), Layer 2 (a fake scanner and probes standing in for nmap and the network), the
Layer 3 checks (fake Wi-Fi, DNS and vulnerability lookups), the nearby survey's aggregation and
room checks, then app/scan.py finish_result: the rules engine, coverage and subjects. Only the
inputs are made up:

  addresses  192.0.2.x (RFC 5737) and MACs 00:00:5E:00:53:xx (RFC 7042, for documentation)
  network    "Example-Home"
  makers     made up, through a made-up maker table in place of the IEEE registry
  CVEs       CVE-2099-0001, made up
  AI text    a made-up AI layer (the demo has AI on); RESULT_AI_OFF uses the standard words

Run `uv run python -m app.demo_data` to write web/src/test/demo/*.json. The page's
fixtures (web/src/test/fixtures.ts) import those files, and tests/unit/test_demo_data.py checks
each file is exactly what the pipeline makes from these inputs. `python -m app --demo` serves
the same checks (app/demo.py), so the demo needs no network and no scans.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import patch

from app.baseline.compare import compare, snapshot
from app.baseline.models import BaselineFacts
from app.baseline.store import BaselineStore
from app.checks.models import CveMatch, DnsResult, WifiStatus
from app.checks.runner import run_network_checks
from app.discovery.models import DiscoveryResult, NetworkInfo, Observation, Service
from app.discovery.runner import Collector, default_collectors, run_discovery
from app.explain.models import (
    AI_LABEL,
    AI_MESSAGE_LABEL,
    Explanation,
    Explanations,
    LandlordMessage,
)
from app.explain.service import explain
from app.fingerprint.models import HttpIdentity, RtspIdentity, UpnpIdentity
from app.fingerprint.pipeline import Probes, fingerprint_devices
from app.handover.session import HandoverSession
from app.rules.models import StayType
from app.scan import finish_result
from app.scanner import ScannerError
from app.wireless import ble
from app.wireless import survey as nearby
from app.wireless.ie import make_security
from app.wireless.models import BleAdvert, BleDevice, BssReading, NearbySurvey, RoomNetwork, WpsInfo

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "src" / "test" / "demo"
SALT = b"roomcheck-demo-salt-made-up-0001"  # fixed, so subjects and match keys are stable

NET = NetworkInfo(
    interface="Wi-Fi",
    own_ip="192.0.2.60",
    own_mac="00:00:5e:00:53:60",
    gateway_ip="192.0.2.1",
    netmask="255.255.255.0",
    cidr="192.0.2.0/24",
    prefixlen=24,
    sweep_allowed=True,
)
ROOM_BSSID = "00:00:5e:00:53:a1"
WPA2 = make_security("wpa2", pairwise=["CCMP"])
OPEN = make_security("open")
CHECK_AT = datetime(2026, 11, 3, 5, 23, 39, tzinfo=UTC)
CHECK_DONE = datetime(2026, 11, 3, 5, 24, 49, tzinfo=UTC)
MOVE_IN_SAVED = datetime(2026, 11, 3, 5, 30, tzinfo=UTC)
LATER = datetime(2026, 11, 20, 9, 0, tzinfo=UTC)

# The made-up maker table, standing in for the IEEE registry (app/fingerprint/oui.py).
MAKERS = {
    "00:00:5e:00:53:01": "Example Routers Ltd",
    "00:00:5e:00:53:58": "Example Camera Co.",
    "00:00:5e:00:53:23": "Example Laptops",
    "00:00:5e:00:53:40": "Example Screens Ltd",
    "00:00:5e:00:53:41": "Example Audio",
    "00:00:5e:00:53:42": "Example Plugs",
    ROOM_BSSID: "Example Routers Ltd",
}


class DemoProtector:
    """Stands in for Windows DPAPI for the demo's own store (made-up data only, in a temporary
    folder): reversible, and never used for real data."""

    def protect(self, data: bytes) -> bytes:
        return b"DEMO:" + bytes(b ^ 0x5A for b in data)

    def unprotect(self, blob: bytes) -> bytes:
        from app.baseline.store import BaselineUnreadable

        if not blob.startswith(b"DEMO:"):
            raise BaselineUnreadable()
        return bytes(b ^ 0x5A for b in blob[5:])


def made_up_maker(mac: str | None) -> str | None:
    return MAKERS.get((mac or "").lower())


def obs(source: str, ip: str | None, mac: str | None, **kw: Any) -> Observation:
    return Observation(source=source, seen_at=CHECK_AT, ip=ip, mac=mac, **kw)  # type: ignore[arg-type]


def mdns(name: str, **txt: str) -> Service:
    return Service(kind="mdns", name=name, detail={f"txt.{k}": v for k, v in txt.items()})


# --- the fake outside world: the scanner, the probes, Wi-Fi, DNS and NVD ------------------------


class FakeScanner:
    """Stands in for the scanner worker: nmap's port list, and the DHCP probe."""

    def __init__(self, ports: dict[str, list[int]], dhcp: list[dict[str, str]] | None) -> None:
        self.ports = ports
        self.dhcp = dhcp

    def run(self, job: str, params: dict[str, Any], timeout: float) -> Any:
        if job == "port_scan":
            return [{"ip": ip, "open_ports": p, "complete": True} for ip, p in self.ports.items()]
        if job == "dhcp_probe":
            if self.dhcp is None:
                raise ScannerError("timeout")  # it took too long and was stopped
            return self.dhcp
        raise ScannerError("internal")


PROBES = Probes(
    http=lambda ip, port: HttpIdentity(port=port, scheme="http", status=200, title="Login"),
    rtsp=lambda ip, port: RtspIdentity(port=port, status=401, server="Example RTSP server"),
    upnp=lambda url, ip: UpnpIdentity(
        manufacturer="Example Routers Ltd",
        model_name="ER-100",
        device_type="urn:schemas-upnp-org:device:InternetGatewayDevice:1",
    ),
)


class FakeNvd:
    """The vulnerability lookup: one made-up issue for the made-up camera model."""

    class _Cache:
        def close(self) -> None:
            pass

    cache = _Cache()

    def lookup(self, word: str, model: str, deadline: float) -> list[CveMatch]:
        if "cam" not in model.lower():
            return []
        return [
            CveMatch(
                model="Example Cam 2",
                cpe="cpe:2.3:o:example:example_cam_2_firmware",
                total=1,
                cve_ids=["CVE-2099-0001"],
            )
        ]


def wifi(_interface: str) -> WifiStatus:
    return WifiStatus(
        interface="Wi-Fi",
        ssid="Example-Home",
        bssid=ROOM_BSSID,
        authentication="WPA2-Personal",
        cipher="CCMP",
    )


def dns() -> DnsResult:
    return DnsResult(
        random_name="rc-demo-0001.example.com", nxdomain=True, checked_domains=["example.org"]
    )


# --- nearby: Wi-Fi readings and Bluetooth adverts ---------------------------------------------


def reading(bssid: str, ssid: str | None, rssi: int, security: Any, **kw: Any) -> BssReading:
    return BssReading(bssid=bssid, ssid=ssid, rssi_dbm=rssi, security=security, **kw)


def ble_device(ref: str, address: str, advert: BleAdvert, rssi: dict[int, int]) -> BleDevice:
    return BleDevice(ref=ref, address=address, cls=ble.classify(advert), round_rssi=rssi)


def short_uuid(n: int) -> str:
    return f"0000{n:04x}-0000-1000-8000-00805f9b34fb"


def survey(*, wps: bool, open_neighbour: bool, hidden: bool, tracker: bool) -> NearbySurvey:
    room_ap = reading(
        ROOM_BSSID,
        "Example-Home",
        -42,
        WPA2,
        frequency_mhz=5220,
        channel=44,
        wps=WpsInfo(state="configured", config_methods=0x0108) if wps else None,
    )
    others = [
        reading("00:00:5e:00:53:b1", "Neighbour-5G", -71, WPA2, frequency_mhz=5180, channel=36),
        reading("00:00:5e:00:53:b2", "Neighbour-2G", -76, WPA2, frequency_mhz=2437, channel=6),
        reading("00:00:5e:00:53:b3", "Example-Cafe", -83, WPA2, frequency_mhz=2412, channel=1),
    ]
    if open_neighbour:
        others.append(
            reading("00:00:5e:00:53:b4", "Free-Guest", -79, OPEN, frequency_mhz=2462, channel=11)
        )
    if hidden:
        others.append(reading("00:00:5e:00:53:b5", None, -55, WPA2, frequency_mhz=2437, channel=6))
    rounds = [[room_ap, *others]] * 3
    with patch.object(nearby, "lookup_vendor", made_up_maker):
        aps = nearby.aggregate_wifi(rounds, SALT)
    earbuds = BleAdvert(
        address="00:00:5e:00:53:c1", rssi_dbm=-60, service_uuids=[short_uuid(ble.UUID_FAST_PAIR)]
    )
    devices = [
        ble_device("bluetooth:earbuds-1", "00:00:5e:00:53:c1", earbuds, {0: -60, 1: -61, 2: -60}),
        ble_device("bluetooth:earbuds-2", "00:00:5e:00:53:c2", earbuds, {0: -72, 1: -74}),
        ble_device("bluetooth:earbuds-3", "00:00:5e:00:53:c3", earbuds, {1: -80, 2: -79}),
    ]
    if tracker:
        tile = BleAdvert(
            address="00:00:5e:00:53:d1", rssi_dbm=-55, service_uuids=[short_uuid(ble.UUID_TILE)]
        )
        devices.append(
            ble_device("bluetooth:tracker-1", "00:00:5e:00:53:d1", tile, {0: -56, 1: -55, 2: -57})
        )
    return NearbySurvey(
        room=RoomNetwork(ssid="Example-Home", bssid=ROOM_BSSID, security=WPA2, source="connected"),
        access_points=aps,
        wifi_method="wlanapi",
        ble_devices=devices,
        ble_rounds=3,
    )


# --- one check, through the same stages as run_scan ------------------------------------------


@contextmanager
def made_up_registry() -> Iterator[None]:
    with patch("app.fingerprint.pipeline.lookup_vendor", made_up_maker):
        yield


def _returns(found: list[Observation]) -> Callable[[NetworkInfo], list[Observation]]:
    """A collector that hears exactly these made-up sightings."""
    return lambda _net: list(found)


def run_check(
    *,
    consent: bool,
    observations: dict[str, list[Observation]],
    ports: dict[str, list[int]],
    dhcp: list[dict[str, str]] | None,
    nearby_survey: NearbySurvey,
    started: datetime,
    finished: datetime,
    stay: StayType | None = None,
    baseline: BaselineFacts | None = None,
) -> DiscoveryResult:
    """Discovery, Layer 2, Layer 3, the nearby check, then finish_result, as run_scan does."""
    collectors = [
        Collector(
            name=c.name,
            label=c.label,
            active=c.active,
            sweep=c.sweep,
            run=_returns(observations.get(c.name, [])),
        )
        for c in default_collectors(None)
    ]
    result = run_discovery("full" if consent else "passive", collectors, get_network=lambda: NET)
    scanner = FakeScanner(ports, dhcp)
    with made_up_registry():
        checks, messages = fingerprint_devices(
            result.devices, consent=consent, scanner=scanner, probe_fns=PROBES
        )
    result.checks += checks
    result.messages += messages
    facts, checks, messages = run_network_checks(
        result,
        consent=consent,
        scanner=scanner,
        online=True,
        wifi_fn=wifi,
        dns_fn=dns,
        nvd_factory=lambda: FakeNvd(),  # type: ignore[arg-type,return-value]
    )
    result.network_facts = facts
    result.checks += checks
    result.messages += messages
    nearby_checks = [
        nearby._status("nearby_wifi", "ran", found=len(nearby_survey.access_points or [])),
        nearby._status("bluetooth", "ran", found=len(nearby_survey.ble_devices or [])),
    ]
    result.checks += nearby_checks + nearby.room_checks(nearby_survey)
    result = finish_result(
        result, nearby_survey, baseline=baseline, match_salt=SALT, stay_type=stay
    )
    result.started_at, result.finished_at = started, finished
    result.observations = []  # raw sightings never leave the check
    return result


# --- the environments -------------------------------------------------------------------------


def _camera_onvif() -> Service:
    return Service(
        kind="onvif",
        name="NetworkVideoTransmitter",
        detail={
            "types": "NetworkVideoTransmitter Device",
            "scopes": "onvif://www.onvif.org/hardware/ExampleCam2 onvif://www.onvif.org/name/ExampleCam",
        },
    )


def full_check(stay: StayType = "short_stay") -> DiscoveryResult:
    """A short stay, checked with permission: a camera that answers like one (with a made-up
    known issue), the router with WPS and UPnP, a tracker nearby, an open and a hidden network.
    The DHCP probe took too long, so one check didn't run."""
    router = ("192.0.2.1", "00:00:5e:00:53:01")
    camera = ("192.0.2.58", "00:00:5e:00:53:58")
    phone = ("192.0.2.21", "02:00:5e:00:53:21")
    igd = Service(
        kind="ssdp",
        name="urn:schemas-upnp-org:device:InternetGatewayDevice:1",
        detail={"location": "http://192.0.2.1:1900/rootDesc.xml"},
    )
    observations = {
        "passive_listen": [
            obs("arp_passive", *router),
            obs("dhcp", *camera, hostname="cam-hallway"),
            obs("arp_passive", *phone),
        ],
        "arp_sweep": [
            obs("arp_sweep", *router),
            obs("arp_sweep", *camera),
            obs("arp_sweep", *phone),
        ],
        "ssdp": [obs("ssdp", *router, services=[igd])],
        "onvif": [obs("onvif", *camera, services=[_camera_onvif()])],
    }
    ports = {"192.0.2.1": [80, 443], "192.0.2.58": [80, 554, 8000], "192.0.2.21": []}
    return run_check(
        consent=True,
        observations=observations,
        ports=ports,
        dhcp=None,
        nearby_survey=survey(wps=True, open_neighbour=True, hidden=True, tracker=True),
        started=CHECK_AT,
        finished=CHECK_DONE,
        stay=stay,
    )


def _quiet_observations() -> dict[str, list[Observation]]:
    """Nine devices that announce themselves, none of them flagged by any rule."""
    return {
        "passive_listen": [
            obs("arp_passive", "192.0.2.1", "00:00:5e:00:53:01"),
            obs("arp_passive", "192.0.2.21", "02:00:5e:00:53:21"),
            obs("dhcp", "192.0.2.22", "02:00:5e:00:53:22", hostname="Pixel-Phone"),
            obs("dhcp", "192.0.2.23", "00:00:5e:00:53:23", hostname="Example-Laptop"),
            # A name with "cam" in it: a weak camera clue, not enough to flag.
            obs("dhcp", "192.0.2.62", "00:00:5e:00:53:61", hostname="Porch-Cam"),
            obs("arp_passive", "192.0.2.61", "00:00:5e:00:53:62"),
        ],
        "mdns": [
            obs(
                "mdns",
                "192.0.2.40",
                "00:00:5e:00:53:40",
                hostname="Living-Room-TV.local",
                services=[mdns("_googlecast._tcp"), mdns("_androidtvremote2._tcp")],
            ),
            obs(
                "mdns",
                "192.0.2.41",
                "00:00:5e:00:53:41",
                hostname="Speaker-Lounge.local",
                services=[mdns("_sonos._tcp"), mdns("_spotify-connect._tcp")],
            ),
            obs(
                "mdns",
                "192.0.2.24",
                "02:00:5e:00:53:24",
                hostname="iPhone.local",
                services=[mdns("_companion-link._tcp")],
            ),
        ],
    }


def listening_check(stay: StayType | None = None) -> DiscoveryResult:
    """Listening only, nothing flagged: what it heard, and what it skipped."""
    return run_check(
        stay=stay,
        consent=False,
        observations=_quiet_observations(),
        ports={},
        dhcp=None,
        nearby_survey=survey(wps=False, open_neighbour=False, hidden=False, tracker=False),
        started=CHECK_AT,
        finished=CHECK_DONE,
    )


def quiet_full_check() -> DiscoveryResult:
    """With permission, nothing flagged, every check ran."""
    observations = _quiet_observations()
    observations["arp_sweep"] = [
        obs("arp_sweep", o.ip, o.mac) for o in observations["passive_listen"] + observations["mdns"]
    ]
    ports: dict[str, list[int]] = {o.ip: [] for o in observations["arp_sweep"] if o.ip}
    return run_check(
        consent=True,
        observations=observations,
        ports=ports,
        dhcp=[
            {
                "server_id": "192.0.2.1",
                "server_mac": "00:00:5e:00:53:01",
                "offered_ip": "192.0.2.60",
            }
        ],
        nearby_survey=survey(wps=False, open_neighbour=False, hidden=False, tracker=False),
        started=CHECK_AT,
        finished=CHECK_DONE,
    )


# --- Compare: a move-in scan, then a later listening-only check --------------------------------


def _move_in() -> DiscoveryResult:
    observations = {
        "passive_listen": [
            obs("arp_passive", "192.0.2.1", "00:00:5e:00:53:01"),
            obs("dhcp", "192.0.2.23", "02:00:5e:00:53:23", hostname="Example-Laptop"),
            obs("arp_passive", "192.0.2.42", "00:00:5e:00:53:42"),
            obs("arp_passive", "192.0.2.25", "02:00:5e:00:53:25"),
        ],
        "mdns": [
            obs(
                "mdns",
                "192.0.2.40",
                "00:00:5e:00:53:40",
                hostname="Living-Room-TV.local",
                services=[mdns("_googlecast._tcp"), mdns("_androidtvremote2._tcp")],
            ),
            obs(
                "mdns",
                "192.0.2.41",
                "00:00:5e:00:53:41",
                hostname="Speaker-Lounge.local",
                services=[mdns("_sonos._tcp"), mdns("_spotify-connect._tcp")],
            ),
        ],
    }
    observations["arp_sweep"] = [
        obs("arp_sweep", o.ip, o.mac) for o in observations["passive_listen"]
    ]
    return run_check(
        consent=True,
        observations=observations,
        ports={o.ip: [] for o in observations["arp_sweep"] if o.ip},
        dhcp=[
            {
                "server_id": "192.0.2.1",
                "server_mac": "00:00:5e:00:53:01",
                "offered_ip": "192.0.2.60",
            }
        ],
        nearby_survey=survey(wps=False, open_neighbour=False, hidden=False, tracker=False),
        started=MOVE_IN_SAVED - timedelta(minutes=5),
        finished=MOVE_IN_SAVED - timedelta(minutes=4),
    )


def _later(baseline: BaselineFacts) -> DiscoveryResult:
    observations = {
        "passive_listen": [
            obs("arp_passive", "192.0.2.1", "00:00:5e:00:53:01"),
            obs("dhcp", "192.0.2.23", "02:00:5e:00:53:23", hostname="Example-Laptop"),
            # The plug now sends Tuya / Smart Life broadcasts: cloud-run.
            obs(
                "tuya",
                "192.0.2.42",
                "00:00:5e:00:53:42",
                services=[Service(kind="tuya", name="tuya-broadcast", detail={"port": "6667"})],
            ),
            obs("arp_passive", "192.0.2.25", "02:00:5e:00:53:25"),
        ],
        "mdns": [
            # The TV answered with fewer of its services this time.
            obs(
                "mdns",
                "192.0.2.40",
                "00:00:5e:00:53:40",
                hostname="Living-Room-TV.local",
                services=[mdns("_googlecast._tcp")],
            ),
            # New since the move-in scan: a device that says it's a HomeKit camera.
            obs(
                "mdns",
                "192.0.2.58",
                "00:00:5e:00:53:58",
                hostname="cam-hallway.local",
                services=[mdns("_hap._tcp", ci="17")],
            ),
        ],
    }
    return run_check(
        consent=False,
        observations=observations,
        ports={},
        dhcp=None,
        nearby_survey=survey(wps=False, open_neighbour=False, hidden=False, tracker=False),
        started=LATER - timedelta(minutes=1),
        finished=LATER,
        baseline=baseline,
    )


def comparison() -> dict[str, Any]:
    move_in = _move_in()
    base = snapshot(move_in, SALT, MOVE_IN_SAVED)
    later = _later(BaselineFacts.of(base, SALT))
    out = compare(base, later, SALT)
    info = {
        "state": "saved",
        "saved_at": MOVE_IN_SAVED,
        "devices": len(base.devices) + base.unkeyed_devices,
        "nearby": len(base.nearby),
        "message": None,
    }
    return {"state": "ready", "baseline": info, "comparison": out.model_dump(mode="json")}


# --- AI explanations (made up: the demo has AI on) and handover --------------------------------

AI_TEXT = {
    "R-CAM": (
        "A device on this network may be a camera.",
        "A camera could record you. You have a right to know where it is.",
    ),
    "R-CVE": (
        "Problems have been reported publicly for this camera's model. "
        "It isn't confirmed that they affect this device.",
        "If its software is out of date, other people could get into it.",
    ),
    "R-WPS": (
        "Your Wi-Fi router advertises WPS, a quick way to join the network.",
        "If PIN-based WPS is enabled, the PIN could be guessed by trying many codes.",
    ),
    "R-TRACKER": (
        "An item tracker kept showing up nearby with a strong signal. "
        "Do you recognise this tracker?",
        "A tracker you don't recognise could be used to follow where you go.",
    ),
    "R-UPNP": (
        "The router lets devices on this network open connections from the internet by themselves.",
        "A device could then be reached from outside without anyone noticing.",
    ),
    "R-HIDDEN": (
        "A Wi-Fi network nearby doesn't show its name, and its signal is strong.",
        "Many routers hide a second network. It is worth asking what it is.",
    ),
    "R-OPEN": (
        "There are Wi-Fi networks nearby with no password.",
        "Anything sent over them could be read by others nearby.",
    ),
}
AI_MESSAGE = (
    "Hello, I checked the room's devices and have a few questions. Could you tell me what the "
    "device that looks like a camera is, and who can view it? Could you also turn off WPS on the "
    "Wi-Fi router? Thank you."
)


def with_ai(result: DiscoveryResult) -> DiscoveryResult:
    """The made-up AI layer: one explanation per finding, labelled as AI."""
    out = result.model_copy(deep=True)
    out.explanations = Explanations(
        ai_status="used",
        items=[
            Explanation(
                finding_id=f.id,
                explanation=AI_TEXT[f.rule_id][0],
                why_it_matters=AI_TEXT[f.rule_id][1],
                source="ai",
                label=AI_LABEL,
            )
            for f in out.findings
        ],
        landlord_message=LandlordMessage(
            text=AI_MESSAGE,
            source="ai",
            label=AI_MESSAGE_LABEL,
            note="RoomCheck never sends anything. Edit this message, then send it yourself.",
        ),
    )
    return out


def with_standard_words(result: DiscoveryResult) -> DiscoveryResult:
    out = result.model_copy(deep=True)
    out.explanations = explain(out.findings, out.devices, out.nearby_items, online=False)
    return out


def handover_states(result: DiscoveryResult) -> dict[str, Any]:
    """The handover data for the demo check, from a real (temporary) handover session."""
    with tempfile.TemporaryDirectory() as tmp:
        session = HandoverSession(BaselineStore(Path(tmp) / "demo.db", DemoProtector()))
        session.salt = SALT
        tasks = session.state_for(result).tasks
        wps = next(t for t in tasks if t.rule_id == "R-WPS")
        session.update_task(
            wps.id,
            "asked",
            "Emailed the host on Monday.",
            now=datetime(2026, 11, 4, 9, 30, tzinfo=UTC),
            check_at=CHECK_AT,
        )
        state = session.state_for(result)
        camera = next(f for f in result.findings if f.rule_id == "R-CAM")
        session.set_answer(camera.subject or "", "mine")
        mine = session.state_for(result)
        session.set_answer(camera.subject or "", None)
        # The demo PDF also shows a finished physical check.
        session.set_physical_item("smoke_detector", True, None)
        session.set_physical_item("chargers", True, None)
        session.set_physical_item("mirrors", True, "Bathroom mirror: nothing behind it")
        session.finish_physical(True, now=datetime(2026, 11, 3, 6, 0, tzinfo=UTC))
        report = session.state_for(result)
    return {"handover": state, "handover_mine": mine, "handover_report": report}


def handover_for(result: DiscoveryResult) -> Any:
    """A fresh handover session's data for a check, nothing answered yet: what the header's
    "Handover · N" counts for that check."""
    with tempfile.TemporaryDirectory() as tmp:
        session = HandoverSession(BaselineStore(Path(tmp) / "demo.db", DemoProtector()))
        session.salt = SALT
        return session.state_for(result)


# --- writing the files -----------------------------------------------------------------------


def _json(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(
            mode="json", exclude={"observations"} if isinstance(value, DiscoveryResult) else None
        )
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {k: _json(v) for k, v in value.items()}
    return value


def build() -> dict[str, Any]:
    """Every demo file, by name: what the pipeline makes from the inputs above."""
    full = full_check()
    states = handover_states(full)
    listening = with_standard_words(listening_check())
    quiet = with_standard_words(quiet_full_check())
    return {
        "result_full": with_ai(full),
        "result_ai_off": with_standard_words(full),
        "result_listening": listening,
        "result_quiet_full": quiet,
        # Each nothing-found check has its own handover data, so the header's count matches it.
        "handover_listening": handover_for(listening),
        "handover_quiet_full": handover_for(quiet),
        "compare": comparison(),
        "handover": states["handover"],
        "handover_mine": states["handover_mine"],
        "handover_report": states["handover_report"],
    }


def render(files: dict[str, Any]) -> dict[str, str]:
    return {
        name: json.dumps(_json(value), indent=1, ensure_ascii=False) + "\n"
        for name, value in files.items()
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, text in render(build()).items():
        (OUT / f"{name}.json").write_text(text, encoding="utf-8")
        print(f"wrote {OUT / name}.json")


if __name__ == "__main__":
    main()
