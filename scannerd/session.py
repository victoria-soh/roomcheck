"""Hosts scannerd itself saw this session: by its ARP sweep, and by its passive listener.

The port check scans only these, so its targets never come from the app. The sweep only runs
after the user consents, so an unconsented session has nothing to port-check: hosts the
listener heard count only once a sweep has run.

Why the listener counts too: a device can miss one run's sweep (asleep, or slow to answer)
while still being heard another way. Before, such a device got no port evidence in that run,
so the same camera read "Likely" in one check and "Possible" in another. Every host scannerd
saw on the network now gets the same service check, whichever way it was seen.
"""

from __future__ import annotations

import ipaddress
import threading

_lock = threading.Lock()
_swept: set[str] = set()
_heard: set[str] = set()
_sweep_ran = False


def _valid(ip: str) -> bool:
    try:
        ipaddress.IPv4Address(ip)
    except ValueError:
        return False
    return True


def record_swept(ips: list[str]) -> None:
    """Replace the list with the latest sweep, so hosts from an earlier scan are never checked."""
    global _sweep_ran
    with _lock:
        _swept.clear()
        _swept.update(ip for ip in ips if _valid(ip))
        _sweep_ran = True


def record_heard(ips: list[str]) -> None:
    """Replace the hosts the latest passive listen heard (ARP and DHCP senders)."""
    with _lock:
        _heard.clear()
        _heard.update(ip for ip in ips if _valid(ip))


def swept_hosts() -> list[str]:
    with _lock:
        return sorted(_swept, key=lambda ip: int(ipaddress.IPv4Address(ip)))


def port_targets() -> list[str]:
    """Every host this session saw, swept or heard; nothing until a sweep has run."""
    with _lock:
        if not _sweep_ran:
            return []
        return sorted(_swept | _heard, key=lambda ip: int(ipaddress.IPv4Address(ip)))


def clear() -> None:
    global _sweep_ran
    with _lock:
        _swept.clear()
        _heard.clear()
        _sweep_ran = False
