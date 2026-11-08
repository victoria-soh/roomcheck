"""Step 0: find the interface, own IP, gateway and subnet. Local only, sends nothing."""

from __future__ import annotations

import ipaddress
import socket
from typing import Any

import psutil

from app.discovery.models import NetworkInfo

# Sweep at most a /22 (1,024 addresses). Anything larger is a shared network: listen only.
MAX_SWEEP_PREFIX = 22


class NoNetworkError(Exception):
    """The laptop has no default route, so it isn't connected to a network."""


def scan_scope(ip: str, netmask: str) -> tuple[str, int, bool]:
    """Return (cidr, prefixlen, sweep_allowed) for an address and netmask."""
    net = ipaddress.IPv4Network(f"{ip}/{netmask}", strict=False)
    return str(net), net.prefixlen, net.prefixlen >= MAX_SWEEP_PREFIX


def _find_interface(own_ip: str) -> tuple[str, str, str | None]:
    """Return (interface name, netmask, MAC) for the interface holding own_ip."""
    for name, addrs in psutil.net_if_addrs().items():
        ipv4 = [a for a in addrs if a.family == socket.AF_INET and a.address == own_ip]
        if not ipv4 or not ipv4[0].netmask:
            continue
        mac = next((a.address for a in addrs if a.family == psutil.AF_LINK), None)
        return name, ipv4[0].netmask, normalize_mac(mac) if mac else None
    raise NoNetworkError(f"no interface holds {own_ip}")


def normalize_mac(mac: str) -> str:
    """'AA-BB-CC-DD-EE-FF' or 'aabb.ccdd.eeff' -> 'aa:bb:cc:dd:ee:ff'."""
    hexdigits = "".join(c for c in mac.lower() if c in "0123456789abcdef")
    if len(hexdigits) != 12:
        raise ValueError(f"not a MAC address: {mac!r}")
    return ":".join(hexdigits[i : i + 2] for i in range(0, 12, 2))


def refresh_routes() -> None:
    """Re-read Windows' interfaces and routes into scapy. scapy reads them once, at import, and
    keeps them: after the laptop rejoins Wi-Fi with a new address, the old copy points at an
    address it no longer has. About 50 ms, so it's done on every read, never cached."""
    import scapy.route  # noqa: F401 - populates conf.route
    from scapy.config import conf

    conf.ifaces.reload()
    conf.route.resync()


def default_route() -> tuple[Any, str, str]:
    """(scapy interface, own IP, gateway IP) for the default route, read fresh each call."""
    from scapy.config import conf

    refresh_routes()
    iface, own_ip, gateway = conf.route.route("0.0.0.0")
    if not own_ip or own_ip == "0.0.0.0" or not gateway or gateway == "0.0.0.0":
        raise NoNetworkError("no default route")
    return iface, own_ip, gateway


def get_network_info() -> NetworkInfo:
    _, own_ip, gateway = default_route()
    name, netmask, own_mac = _find_interface(own_ip)
    cidr, prefixlen, sweep_allowed = scan_scope(own_ip, netmask)
    return NetworkInfo(
        interface=name,
        own_ip=own_ip,
        own_mac=own_mac,
        gateway_ip=gateway,
        netmask=netmask,
        cidr=cidr,
        prefixlen=prefixlen,
        sweep_allowed=sweep_allowed,
    )
