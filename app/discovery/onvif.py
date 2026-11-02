"""Step 5: ONVIF WS-Discovery probe for NetworkVideoTransmitter. Active multicast.

A plain UDP socket and a defusedxml parser instead of the WSDiscovery package: device XML is
untrusted input, so it is parsed with defusedxml and capped in size.
"""

from __future__ import annotations

import ipaddress
import socket
import time
import uuid
from datetime import UTC, datetime

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from app.discovery.models import NetworkInfo, Observation, Service

WSD_ADDR = ("239.255.255.250", 3702)
MAX_DATAGRAM = 65507
MAX_RESPONSES = 256
_MAX_ITEMS = 20
_MAX_ITEM_LEN = 200

NVT = "NetworkVideoTransmitter"


def probe_message(message_id: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"'
        ' xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"'
        ' xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"'
        ' xmlns:dn="http://www.onvif.org/ver10/network/wsdl">'
        "<e:Header>"
        f"<w:MessageID>uuid:{message_id}</w:MessageID>"
        "<w:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>"
        "<w:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>"
        "</e:Header>"
        "<e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body>"
        "</e:Envelope>"
    ).encode()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _split(text: str | None) -> list[str]:
    return [t[:_MAX_ITEM_LEN] for t in (text or "").split()][:_MAX_ITEMS]


def parse_probe_matches(data: bytes) -> list[dict[str, list[str]]]:
    """Return one {types, xaddrs, scopes} dict per ProbeMatch. Malformed or hostile XML -> []."""
    try:
        root = ElementTree.fromstring(data[:MAX_DATAGRAM])
    except (ElementTree.ParseError, DefusedXmlException, ValueError):
        return []
    matches = []
    for el in root.iter():
        if _local(el.tag) != "ProbeMatch":
            continue
        fields: dict[str, list[str]] = {"types": [], "xaddrs": [], "scopes": []}
        for child in el:
            name = _local(child.tag)
            if name == "Types":
                fields["types"] = [_local(t.split(":")[-1]) for t in _split(child.text)]
            elif name == "XAddrs":
                fields["xaddrs"] = _split(child.text)
            elif name == "Scopes":
                fields["scopes"] = _split(child.text)
        matches.append(fields)
    return matches


def observation_from_match(ip: str, match: dict[str, list[str]], now: datetime) -> Observation:
    name = NVT if NVT in match["types"] else (match["types"][0] if match["types"] else "unknown")
    detail = {
        "types": " ".join(match["types"]),
        "xaddrs": " ".join(match["xaddrs"]),
        "scopes": " ".join(match["scopes"]),
    }
    return Observation(
        source="onvif",
        seen_at=now,
        ip=ip,
        services=[Service(kind="onvif", name=name, detail={k: v for k, v in detail.items() if v})],
    )


def probe(net: NetworkInfo, listen_seconds: float = 4.0) -> list[Observation]:
    subnet = ipaddress.IPv4Network(net.cidr)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    try:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(net.own_ip))
        sock.bind((net.own_ip, 0))
        sock.settimeout(0.5)
        msg = probe_message(str(uuid.uuid4()))
        for _ in range(2):
            sock.sendto(msg, WSD_ADDR)

        results: list[Observation] = []
        deadline = time.monotonic() + listen_seconds
        while time.monotonic() < deadline and len(results) < MAX_RESPONSES:
            try:
                data, (ip, _port) = sock.recvfrom(MAX_DATAGRAM)
            except TimeoutError:
                continue
            if ipaddress.IPv4Address(ip) not in subnet:
                continue
            now = datetime.now(UTC)
            results.extend(observation_from_match(ip, m, now) for m in parse_probe_matches(data))
        return results
    finally:
        sock.close()
