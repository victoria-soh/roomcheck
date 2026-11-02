"""Merge observations from every collector into one record per device, keyed by MAC."""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable

from app.discovery.messages import RANDOM_MAC_NOTE
from app.discovery.models import Device, Observation, Service
from app.discovery.netinfo import normalize_mac

# Seconds the scan must have run before an empty result counts as client isolation.
ISOLATION_MIN_SECONDS = 60

_IGNORED_MACS = {"00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff"}


def is_random_mac(mac: str) -> bool:
    """True if the locally administered bit (0x02 in the first octet) is set."""
    return bool(int(normalize_mac(mac)[:2], 16) & 0x02)


def _clean_mac(mac: str | None) -> str | None:
    if not mac:
        return None
    try:
        mac = normalize_mac(mac)
    except ValueError:
        return None
    # Multicast MACs (low bit of first octet) never identify a single host.
    if mac in _IGNORED_MACS or int(mac[:2], 16) & 0x01:
        return None
    return mac


def _clean_ip(ip: str | None) -> str | None:
    if not ip:
        return None
    try:
        addr = ipaddress.IPv4Address(ip)
    except ValueError:
        return None
    if addr.is_unspecified or addr.is_multicast or addr.is_loopback or ip == "255.255.255.255":
        return None
    return ip


def _service_key(s: Service) -> tuple[str, str, tuple[tuple[str, str], ...]]:
    return s.kind, s.name, tuple(sorted(s.detail.items()))


def _ip_sort_key(d: Device) -> tuple[int, int]:
    return (0, int(ipaddress.IPv4Address(d.ip))) if d.ip else (1, 0)


def merge_observations(
    observations: Iterable[Observation],
    *,
    gateway_ip: str | None = None,
    exclude_ips: Iterable[str] = (),
    exclude_macs: Iterable[str] = (),
) -> list[Device]:
    """Fold observations into Devices.

    Observations with a MAC are keyed by it. Those with only an IP (mDNS, SSDP, ONVIF) are
    attached to the device that ARP or DHCP tied to that IP, or else kept under an IP key.
    The laptop's own addresses are excluded.
    """
    obs = sorted(observations, key=lambda o: o.seen_at)
    skip_ips = {ip for ip in exclude_ips if ip}
    skip_macs = {m for m in (_clean_mac(x) for x in exclude_macs) if m}

    ip_to_mac: dict[str, str] = {}
    for o in obs:
        ip, mac = _clean_ip(o.ip), _clean_mac(o.mac)
        if ip and mac:
            ip_to_mac[ip] = mac  # latest wins

    devices: dict[str, Device] = {}
    service_keys: dict[str, set[tuple[str, str, tuple[tuple[str, str], ...]]]] = {}
    for o in obs:
        ip, mac = _clean_ip(o.ip), _clean_mac(o.mac)
        mac = mac or (ip_to_mac.get(ip) if ip else None)
        if (ip and ip in skip_ips) or (mac and mac in skip_macs):
            continue
        if mac:
            key = f"mac:{mac}"
        elif ip:
            key = f"ip:{ip}"
        else:
            continue

        dev = devices.get(key)
        if dev is None:
            random = is_random_mac(mac) if mac else False
            dev = Device(
                id=key,
                ip=ip,
                mac=mac,
                mac_is_random=random,
                notes=[RANDOM_MAC_NOTE] if random else [],
                first_seen=o.seen_at,
                last_seen=o.seen_at,
            )
            devices[key] = dev
            service_keys[key] = set()

        if ip:
            dev.ip = ip
        dev.last_seen = max(dev.last_seen, o.seen_at)
        if o.source not in dev.sources:
            dev.sources.append(o.source)
        if o.hostname and o.hostname not in dev.hostnames:
            dev.hostnames.append(o.hostname)
        for s in o.services:
            k = _service_key(s)
            if k not in service_keys[key]:
                service_keys[key].add(k)
                dev.services.append(s)

    for dev in devices.values():
        dev.is_gateway = gateway_ip is not None and dev.ip == gateway_ip
    return sorted(devices.values(), key=_ip_sort_key)


def detect_client_isolation(
    devices: Iterable[Device],
    *,
    gateway_ip: str,
    elapsed_seconds: float,
    sweep_ran: bool,
) -> bool:
    """True if, after a full minute with the sweep running, only the gateway was seen."""
    if not sweep_ran or elapsed_seconds < ISOLATION_MIN_SECONDS:
        return False
    return all(d.ip == gateway_ip for d in devices)
