"""Step 4: SSDP / UPnP M-SEARCH (ssdp:all). Active multicast; only run after consent.

Uses a plain UDP socket rather than ssdpy so the parser stays a small pure function with
explicit size caps. Fetching the LOCATION description XML is Layer 2.
"""

from __future__ import annotations

import ipaddress
import socket
import time
from datetime import UTC, datetime

from app.discovery.models import NetworkInfo, Observation, Service

SSDP_ADDR = ("239.255.255.250", 1900)
MX_SECONDS = 2
MAX_DATAGRAM = 4096
MAX_RESPONSES = 512
_KEPT_HEADERS = ("st", "nt", "server", "location", "usn")
_MAX_HEADER_VALUE = 256

M_SEARCH = (
    "M-SEARCH * HTTP/1.1\r\n"
    "HOST: 239.255.255.250:1900\r\n"
    'MAN: "ssdp:discover"\r\n'
    f"MX: {MX_SECONDS}\r\n"
    "ST: ssdp:all\r\n"
    "\r\n"
).encode("ascii")


def parse_ssdp_response(data: bytes) -> dict[str, str] | None:
    """Parse an SSDP search response into lower-cased headers, or None if it isn't one."""
    text = data[:MAX_DATAGRAM].decode("utf-8", errors="replace")
    lines = text.split("\r\n") if "\r\n" in text else text.split("\n")
    if not lines or not lines[0].upper().startswith("HTTP/1.1 200"):
        return None
    headers: dict[str, str] = {}
    for line in lines[1:]:
        name, sep, value = line.partition(":")
        if not sep:
            continue
        key = name.strip().lower()
        if key in _KEPT_HEADERS and key not in headers:
            headers[key] = value.strip()[:_MAX_HEADER_VALUE]
    return headers if ("st" in headers or "nt" in headers) else None


def observation_from_response(ip: str, headers: dict[str, str], now: datetime) -> Observation:
    target = headers.get("st") or headers.get("nt") or "unknown"
    detail = {k: v for k, v in headers.items() if k in ("server", "location", "usn")}
    return Observation(
        source="ssdp",
        seen_at=now,
        ip=ip,
        services=[Service(kind="ssdp", name=target, detail=detail)],
    )


def search(net: NetworkInfo, listen_seconds: float = MX_SECONDS + 2) -> list[Observation]:
    subnet = ipaddress.IPv4Network(net.cidr)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(net.own_ip))
        sock.bind((net.own_ip, 0))
        sock.settimeout(0.5)
        for _ in range(2):  # UDP is lossy; send twice
            sock.sendto(M_SEARCH, SSDP_ADDR)

        results: list[Observation] = []
        deadline = time.monotonic() + listen_seconds
        while time.monotonic() < deadline and len(results) < MAX_RESPONSES:
            try:
                data, (ip, _port) = sock.recvfrom(MAX_DATAGRAM)
            except TimeoutError:
                continue
            if ipaddress.IPv4Address(ip) not in subnet:
                continue
            headers = parse_ssdp_response(data)
            if headers:
                results.append(observation_from_response(ip, headers, datetime.now(UTC)))
        return results
    finally:
        sock.close()
