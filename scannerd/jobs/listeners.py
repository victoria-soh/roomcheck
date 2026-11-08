"""Steps 2 and 6: passive ARP, DHCP and Tuya broadcast listener for the whole scan.

Reads headers only. Tuya payloads are encrypted and are never decoded or kept.
"""

from __future__ import annotations

import ipaddress
import json
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from scapy.layers.dhcp import BOOTP, DHCP
from scapy.layers.inet import IP, UDP
from scapy.layers.l2 import ARP, Ether
from scapy.packet import Packet

from app.discovery.models import Observation, Service
from app.discovery.netinfo import NoNetworkError, default_route, get_network_info
from scannerd import session
from scannerd.jobs.arp import observation_from_arp
from scannerd.protocol import JobError, require_pcap

TUYA_PORTS = (6666, 6667)
BPF_FILTER = "arp or (udp and (port 67 or port 68 or port 6666 or port 6667))"
MAX_DISTINCT = 2000
_MAX_STR = 100

DHCP_ACK = 5


class PassiveListenParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    duration_seconds: float = Field(default=60.0, ge=1, le=120)


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    return str(value).strip("\x00 ")[:_MAX_STR]


def _dhcp_options(pkt: Packet) -> dict[str, Any]:
    dhcp = pkt.getlayer(DHCP)
    if dhcp is None:
        return {}
    return {o[0]: o[1] for o in dhcp.options if isinstance(o, tuple) and len(o) >= 2}


def _chaddr_mac(bootp: Packet) -> str | None:
    raw = bytes(bootp.chaddr or b"")[:6]
    return ":".join(f"{b:02x}" for b in raw) if len(raw) == 6 else None


def observation_from_dhcp(pkt: Packet, now: datetime) -> Observation | None:
    """Client requests give hostname (12), parameter list (55) and vendor class (60)."""
    bootp = pkt.getlayer(BOOTP)
    if bootp is None:
        return None
    mac = _chaddr_mac(bootp)
    opts = _dhcp_options(pkt)

    if bootp.op == 1:  # client -> server
        ip = opts.get("requested_addr") or (bootp.ciaddr if bootp.ciaddr != "0.0.0.0" else None)
        detail: dict[str, str] = {}
        if "vendor_class_id" in opts:
            detail["vendor_class"] = _text(opts["vendor_class_id"])
        prl = opts.get("param_req_list")
        if isinstance(prl, list | tuple | bytes):
            detail["param_req_list"] = ",".join(str(int(x)) for x in prl)[:_MAX_STR]
        hostname = _text(opts["hostname"]) if "hostname" in opts else None
        return Observation(
            source="dhcp",
            seen_at=now,
            ip=ip,
            mac=mac,
            hostname=hostname or None,
            services=[Service(kind="dhcp", name="dhcp-client", detail=detail)] if detail else [],
        )
    if bootp.op == 2 and opts.get("message-type") == DHCP_ACK and bootp.yiaddr != "0.0.0.0":
        return Observation(source="dhcp", seen_at=now, ip=bootp.yiaddr, mac=mac)
    return None


def observation_from_tuya(pkt: Packet, now: datetime) -> Observation | None:
    udp = pkt.getlayer(UDP)
    if udp is None or udp.dport not in TUYA_PORTS or pkt.getlayer(IP) is None:
        return None
    mac = pkt[Ether].src if pkt.getlayer(Ether) is not None else None
    return Observation(
        source="tuya",
        seen_at=now,
        ip=pkt[IP].src,
        mac=mac,
        services=[Service(kind="tuya", name="tuya-broadcast", detail={"port": str(udp.dport)})],
    )


def observation_from_packet(pkt: Packet, now: datetime) -> Observation | None:
    if pkt.getlayer(ARP) is not None:
        return observation_from_arp(pkt, "arp_passive", now)
    if pkt.getlayer(BOOTP) is not None:
        return observation_from_dhcp(pkt, now)
    if pkt.getlayer(UDP) is not None:
        return observation_from_tuya(pkt, now)
    return None


class ObservationLog:
    """Keeps the first and latest sighting of each distinct observation, up to a cap.

    Two sightings are enough for first_seen/last_seen, and keeping each distinct IP-MAC pair
    lets Layer 3 spot a gateway IP claimed by more than one MAC.
    """

    def __init__(self, subnet: ipaddress.IPv4Network, cap: int = MAX_DISTINCT) -> None:
        self.subnet = subnet
        self.cap = cap
        self._first: dict[str, Observation] = {}
        self._last: dict[str, Observation] = {}

    def add(self, obs: Observation | None) -> None:
        if obs is None:
            return
        if obs.ip and ipaddress.IPv4Address(obs.ip) not in self.subnet:
            return
        key = json.dumps(obs.model_dump(mode="json", exclude={"seen_at"}), sort_keys=True)
        if key in self._first:
            self._last[key] = obs
        elif len(self._first) < self.cap:
            self._first[key] = obs

    def observations(self) -> list[Observation]:
        return list(self._first.values()) + list(self._last.values())


def passive_listen(params: PassiveListenParams) -> list[dict[str, Any]]:
    from scapy.sendrecv import sniff

    require_pcap()
    try:
        iface, _, _ = default_route()
        net = get_network_info()
    except NoNetworkError as e:
        raise JobError("no_network") from e

    log = ObservationLog(ipaddress.IPv4Network(net.cidr))
    sniff(
        iface=iface,
        filter=BPF_FILTER,
        prn=lambda pkt: log.add(observation_from_packet(pkt, datetime.now(UTC))),
        store=False,
        timeout=params.duration_seconds,
    )
    observations = log.observations()
    # Port-check targets too (only once a consented sweep has run): see scannerd/session.py.
    session.record_heard([o.ip for o in observations if o.ip])
    return [o.model_dump(mode="json") for o in observations]
