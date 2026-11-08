"""Device fixtures for Layer 2 tests, modelled on real devices."""

from datetime import UTC, datetime
from pathlib import Path

from app.discovery.models import Device, Service
from app.fingerprint.models import HttpIdentity, Identity, RtspIdentity
from app.fingerprint.oui import lookup_vendor

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "fingerprint"
T = datetime(2026, 11, 2, tzinfo=UTC)


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def make(ip, mac, *, hostnames=(), services=(), gateway=False, identity=None, random=False):
    d = Device(
        id=f"mac:{mac}" if mac else f"ip:{ip}",
        ip=ip,
        mac=mac,
        mac_is_random=random,
        is_gateway=gateway,
        hostnames=list(hostnames),
        services=list(services),
        sources=["arp_sweep"],
        first_seen=T,
        last_seen=T,
        identity=identity,
    )
    d.vendor = lookup_vendor(mac)
    return d


def mdns(name, **txt):
    return Service(kind="mdns", name=name, detail={f"txt.{k}": v for k, v in txt.items()})


def sonos():
    """Matches the Sonos speaker seen on the user's network in the Layer 1 live run."""
    return make(
        "192.0.2.53",
        "38:42:0b:00:00:84",
        hostnames=["Sonos-38420B000084.local"],
        services=[
            mdns("_sonos._tcp"),
            mdns("_spotify-connect._tcp"),
            mdns("_raop._tcp", am="One"),
            mdns("_airplay._tcp", model="One"),
        ],
        identity=Identity(open_ports=[]),
    )


def macbook():
    return make(
        "192.0.2.54",
        "00:0a:95:12:34:56",  # Apple, Inc. prefix
        hostnames=["MacBook-Air-3.local"],
        services=[mdns("_airplay._tcp"), mdns("_raop._tcp"), mdns("_rfb._tcp"), mdns("_smb._tcp")],
        identity=Identity(open_ports=[]),
    )


def windows_laptop():
    return make(
        "192.0.2.70",
        "da:a1:19:20:30:40",
        random=True,
        hostnames=["DESKTOP-EXAMPLE1"],
        services=[Service(kind="dhcp", name="dhcp-client", detail={"vendor_class": "MSFT 5.0"})],
        identity=Identity(open_ports=[]),
    )


def hikvision_camera():
    return make(
        "192.0.2.64",
        "00:bc:99:aa:bb:cc",  # Hangzhou Hikvision prefix
        services=[
            Service(
                kind="onvif",
                name="NetworkVideoTransmitter",
                detail={"types": "NetworkVideoTransmitter Device"},
            )
        ],
        identity=Identity(
            open_ports=[80, 554, 8000],
            http=[
                HttpIdentity(port=80, scheme="http", status=200, server="webserver", title="Login")
            ],
            rtsp=[RtspIdentity(port=554, status=401, server="Hikvision-Webs")],
        ),
    )


def phone_ip_camera_app():
    """An old phone running an IP-camera app (the demo's stand-in camera)."""
    return make(
        "192.0.2.80",
        "aa:bb:cc:00:11:22",  # 0xAA has the local bit set: private address
        random=True,
        identity=Identity(
            open_ports=[8080, 8554],
            http=[HttpIdentity(port=8080, scheme="http", status=200, title="IP Webcam")],
            rtsp=[RtspIdentity(port=8554, status=200, server="IP Webcam")],
        ),
    )


def tp_link_gateway():
    return make(
        "192.0.2.1",
        "cc:ba:bd:00:00:01",
        gateway=True,
        services=[Service(kind="ssdp", name="urn:schemas-upnp-org:device:InternetGatewayDevice:1")],
        identity=Identity(open_ports=[80, 443]),
    )
