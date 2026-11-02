from datetime import UTC, datetime

from app.discovery.mdns import observation_from_service

NOW = datetime(2026, 11, 2, tzinfo=UTC)


def test_observation_from_googlecast_service():
    [o] = observation_from_service(
        "_googlecast._tcp.local.",
        "Living-Room-TV-abc123._googlecast._tcp.local.",
        ["192.168.1.55", "fe80::1"],
        "abc123.local.",
        {b"md": b"Chromecast", b"fn": b"Living Room TV", b"empty": None},
        NOW,
    )
    assert o.source == "mdns"
    assert o.ip == "192.168.1.55"
    assert o.hostname == "abc123.local"
    s = o.services[0]
    assert s.name == "_googlecast._tcp"
    assert s.detail["instance"] == "Living-Room-TV-abc123"
    assert s.detail["txt.md"] == "Chromecast"
    assert s.detail["txt.empty"] == ""


def test_txt_records_are_capped():
    props = {f"k{i}".encode(): b"v" * 500 for i in range(50)}
    [o] = observation_from_service(
        "_hap._tcp.local.", "x._hap._tcp.local.", ["10.0.0.2"], None, props, NOW
    )
    txt = {k: v for k, v in o.services[0].detail.items() if k.startswith("txt.")}
    assert len(txt) == 20
    assert all(len(v) <= 100 for v in txt.values())
    assert o.hostname is None


def test_ipv6_only_service_gives_no_observation():
    assert (
        observation_from_service(
            "_hap._tcp.local.", "x._hap._tcp.local.", ["fe80::2"], None, {}, NOW
        )
        == []
    )
