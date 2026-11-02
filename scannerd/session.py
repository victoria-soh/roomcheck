"""Hosts scannerd itself found by ARP sweep this session.

The port check scans only these, so its targets never come from the app. The sweep only runs
after the user consents, so an unconsented session has nothing to port-check.
"""

from __future__ import annotations

import ipaddress
import threading

_lock = threading.Lock()
_swept: set[str] = set()


def record_swept(ips: list[str]) -> None:
    """Replace the list with the latest sweep, so hosts from an earlier scan are never checked."""
    with _lock:
        _swept.clear()
        _swept.update(ips)


def swept_hosts() -> list[str]:
    with _lock:
        return sorted(_swept, key=lambda ip: int(ipaddress.IPv4Address(ip)))


def clear() -> None:
    with _lock:
        _swept.clear()
