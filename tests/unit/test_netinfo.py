import subprocess
import sys

import pytest

from app.discovery import netinfo
from app.discovery.netinfo import NoNetworkError, scan_scope


@pytest.mark.parametrize(
    ("ip", "mask", "cidr", "prefix", "allowed"),
    [
        ("192.168.1.23", "255.255.255.0", "192.168.1.0/24", 24, True),
        ("192.168.69.60", "255.255.252.0", "192.168.68.0/22", 22, True),  # exactly the limit
        ("10.20.30.40", "255.255.248.0", "10.20.24.0/21", 21, False),
        ("172.16.5.5", "255.255.0.0", "172.16.0.0/16", 16, False),
    ],
)
def test_scan_scope(ip, mask, cidr, prefix, allowed):
    assert scan_scope(ip, mask) == (cidr, prefix, allowed)


def test_no_default_route_raises(monkeypatch):
    import scapy.route  # noqa: F401 - populates conf.route
    from scapy.config import conf

    monkeypatch.setattr(conf.route, "route", lambda dst: ("lo", "0.0.0.0", "0.0.0.0"))
    with pytest.raises(NoNetworkError):
        netinfo.default_route()


def test_default_route_works_in_a_fresh_interpreter():
    """conf.route is lazy in scapy; a fresh process must still get a route or NoNetworkError."""
    code = (
        "from app.discovery.netinfo import NoNetworkError, default_route\n"
        "try:\n"
        "    default_route()\n"
        "except NoNetworkError:\n"
        "    pass\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
