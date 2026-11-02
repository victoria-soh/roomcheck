from datetime import UTC, datetime, timedelta

import pytest

from app.discovery.merge import detect_client_isolation, is_random_mac, merge_observations
from app.discovery.messages import RANDOM_MAC_NOTE
from app.discovery.models import Observation, Service
from app.discovery.netinfo import normalize_mac

T0 = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


def obs(source, *, ip=None, mac=None, hostname=None, services=(), t=0):
    return Observation(
        source=source,
        seen_at=T0 + timedelta(seconds=t),
        ip=ip,
        mac=mac,
        hostname=hostname,
        services=list(services),
    )


@pytest.mark.parametrize(
    ("mac", "expected"),
    [
        ("00:11:22:33:44:55", False),
        ("02:11:22:33:44:55", True),
        ("DA-A1-19-00-00-01", True),  # 0xDA has the 0x02 bit set
        ("a4:83:e7:00:00:01", False),
    ],
)
def test_is_random_mac(mac, expected):
    assert is_random_mac(mac) is expected


def test_normalize_mac_formats():
    assert normalize_mac("AA-BB-CC-DD-EE-FF") == "aa:bb:cc:dd:ee:ff"
    assert normalize_mac("aabb.ccdd.eeff") == "aa:bb:cc:dd:ee:ff"
    with pytest.raises(ValueError):
        normalize_mac("not-a-mac")


def test_merges_by_mac_and_attaches_ip_only_sources():
    cam = Service(kind="onvif", name="NetworkVideoTransmitter")
    devices = merge_observations(
        [
            obs("arp_sweep", ip="192.168.1.20", mac="00:11:22:33:44:55", t=0),
            obs("onvif", ip="192.168.1.20", services=[cam], t=5),
            obs("mdns", ip="192.168.1.20", hostname="cam-hall.local", t=7),
            obs("arp_passive", ip="192.168.1.20", mac="00-11-22-33-44-55", t=40),
        ]
    )
    assert len(devices) == 1
    d = devices[0]
    assert d.id == "mac:00:11:22:33:44:55"
    assert d.sources == ["arp_sweep", "onvif", "mdns", "arp_passive"]
    assert d.hostnames == ["cam-hall.local"]
    assert d.services == [cam]
    assert d.first_seen == T0
    assert d.last_seen == T0 + timedelta(seconds=40)


def test_ip_only_observation_attaches_even_if_arp_comes_later():
    devices = merge_observations(
        [
            obs("ssdp", ip="192.168.1.30", t=0),
            obs("arp_sweep", ip="192.168.1.30", mac="00:aa:bb:cc:dd:ee", t=10),
        ]
    )
    assert [d.id for d in devices] == ["mac:00:aa:bb:cc:dd:ee"]
    assert devices[0].first_seen == T0


def test_ip_only_device_without_arp_is_kept_by_ip():
    devices = merge_observations([obs("mdns", ip="192.168.1.40", hostname="tv.local")])
    assert devices[0].id == "ip:192.168.1.40"
    assert devices[0].mac is None
    assert devices[0].mac_is_random is False


def test_duplicate_services_collapse():
    s = Service(kind="ssdp", name="upnp:rootdevice", detail={"server": "Linux UPnP/1.0"})
    devices = merge_observations(
        [obs("ssdp", ip="192.168.1.1", services=[s]), obs("ssdp", ip="192.168.1.1", services=[s])]
    )
    assert devices[0].services == [s]
    assert devices[0].sources == ["ssdp"]


def test_random_mac_gets_low_confidence_note():
    devices = merge_observations([obs("arp_sweep", ip="192.168.1.50", mac="da:a1:19:00:00:01")])
    assert devices[0].mac_is_random
    assert devices[0].notes == [RANDOM_MAC_NOTE]


def test_excludes_own_laptop_and_junk_addresses():
    devices = merge_observations(
        [
            obs("arp_passive", ip="192.168.1.10", mac="00:00:00:00:00:10"),  # the laptop
            obs("arp_passive", ip="0.0.0.0", mac="ff:ff:ff:ff:ff:ff"),
            obs("ssdp", ip="239.255.255.250"),
            obs("dhcp", mac="01:00:5e:00:00:fb"),  # multicast MAC
            obs("arp_passive", ip="192.168.1.11", mac="00:00:00:00:00:11"),
        ],
        exclude_ips=["192.168.1.10"],
        exclude_macs=["00-00-00-00-00-10"],
    )
    assert [d.ip for d in devices] == ["192.168.1.11"]


def test_mac_only_dhcp_device():
    devices = merge_observations([obs("dhcp", mac="00:11:22:33:44:66", hostname="ESP_1A2B3C")])
    assert devices[0].ip is None
    assert devices[0].hostnames == ["ESP_1A2B3C"]


def test_gateway_flag_and_sorting_by_ip():
    devices = merge_observations(
        [
            obs("arp_sweep", ip="192.168.1.100", mac="00:00:00:00:01:00"),
            obs("arp_sweep", ip="192.168.1.9", mac="00:00:00:00:00:09"),
            obs("arp_sweep", ip="192.168.1.1", mac="00:00:00:00:00:01"),
        ],
        gateway_ip="192.168.1.1",
    )
    assert [d.ip for d in devices] == ["192.168.1.1", "192.168.1.9", "192.168.1.100"]
    assert [d.is_gateway for d in devices] == [True, False, False]


def test_device_ip_follows_latest_sighting():
    devices = merge_observations(
        [
            obs("arp_sweep", ip="192.168.1.20", mac="00:11:22:33:44:55", t=0),
            obs("dhcp", ip="192.168.1.21", mac="00:11:22:33:44:55", t=30),
        ]
    )
    assert devices[0].ip == "192.168.1.21"


def _gateway_only():
    return merge_observations([obs("arp_sweep", ip="10.0.0.1", mac="00:00:00:00:00:01")])


def test_client_isolation_detected_after_a_minute_with_only_gateway():
    assert detect_client_isolation(
        _gateway_only(), gateway_ip="10.0.0.1", elapsed_seconds=61, sweep_ran=True
    )


def test_client_isolation_needs_full_minute_and_sweep():
    gw = _gateway_only()
    assert not detect_client_isolation(
        gw, gateway_ip="10.0.0.1", elapsed_seconds=30, sweep_ran=True
    )
    assert not detect_client_isolation(
        gw, gateway_ip="10.0.0.1", elapsed_seconds=90, sweep_ran=False
    )


def test_no_client_isolation_when_other_hosts_seen():
    devices = merge_observations(
        [
            obs("arp_sweep", ip="10.0.0.1", mac="00:00:00:00:00:01"),
            obs("arp_sweep", ip="10.0.0.7", mac="00:00:00:00:00:07"),
        ]
    )
    assert not detect_client_isolation(
        devices, gateway_ip="10.0.0.1", elapsed_seconds=90, sweep_ran=True
    )
